"""
Revenue Extractor Web Application

Flask web app that accepts a ZIP file of PDFs, extracts total revenues
from each PDF, and generates a CSV file with results.
"""

from flask import Flask, render_template, request, jsonify, send_file
import os
from pathlib import Path
import zipfile
import tempfile
import csv
import io
from datetime import datetime
import threading
import shutil

# Import the revenue extraction function
from pdf_revenue_scraper import extract_revenue_from_pdf, format_currency

app = Flask(__name__)

# Configure upload folder
UPLOAD_FOLDER = Path('./revenue_uploads')
UPLOAD_FOLDER.mkdir(exist_ok=True)

# Store processing status for progress tracking
processing_status = {}

# Maximum file size (500 MB) - increased to handle larger ZIP files
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024


@app.route('/')
def index():
    """Render the revenue extractor page."""
    return render_template('revenue_extractor.html')


def process_pdfs_background(session_id, pdf_files, pdf_dir_to_keep):
    """
    Background task to process PDFs and extract revenues.

    Args:
        session_id: Unique session identifier
        pdf_files: List of PDF file paths
        pdf_dir_to_keep: Directory containing PDFs (will be cleaned up after processing)
    """
    global processing_status

    try:
        results = []
        errors = []

        for idx, pdf_path in enumerate(pdf_files, 1):
            # Update progress
            processing_status[session_id]['current'] = idx
            processing_status[session_id]['current_file'] = pdf_path.name

            try:
                print(f"\n[{idx}/{len(pdf_files)}] Processing: {pdf_path.name}")

                # Extract revenue from PDF
                result = extract_revenue_from_pdf(str(pdf_path), show_tables=False)

                # Prepare result data
                entity_name = result.get('entity_name') or pdf_path.stem
                total_revenue = result.get('total_revenue')
                page_number = result.get('page_number')
                is_consolidated = result.get('is_consolidated', False)

                result_data = {
                    'filename': pdf_path.name,
                    'entity_name': entity_name,
                    'total_revenue': total_revenue,
                    'total_revenue_formatted': format_currency(total_revenue) if total_revenue else 'Not found',
                    'page_number': page_number,
                    'is_consolidated': is_consolidated,
                    'status': 'success'
                }

                results.append(result_data)
                processing_status[session_id]['results'].append(result_data)

                print(f"  Entity: {entity_name}")
                print(f"  Revenue: {format_currency(total_revenue) if total_revenue else 'Not found'}")

            except Exception as e:
                print(f"  Error processing {pdf_path.name}: {e}")
                error_data = {
                    'filename': pdf_path.name,
                    'error': str(e),
                    'status': 'error'
                }
                errors.append(error_data)
                processing_status[session_id]['errors'].append(error_data)

        # Generate CSV file
        csv_filename = f"revenue_extraction_{session_id}.csv"
        csv_path = UPLOAD_FOLDER / csv_filename

        with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['filename', 'entity_name', 'total_revenue', 'page_number', 'is_consolidated', 'status']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()

            # Write successful results
            for result in results:
                writer.writerow({
                    'filename': result['filename'],
                    'entity_name': result['entity_name'],
                    'total_revenue': result['total_revenue'] if result['total_revenue'] else '',
                    'page_number': result['page_number'] if result['page_number'] else '',
                    'is_consolidated': 'Yes' if result.get('is_consolidated') else 'No',
                    'status': result['status']
                })

            # Write errors
            for error in errors:
                writer.writerow({
                    'filename': error['filename'],
                    'entity_name': '',
                    'total_revenue': '',
                    'page_number': '',
                    'is_consolidated': '',
                    'status': f"error: {error['error']}"
                })

        print(f"\nCSV file generated: {csv_path}")

        # Update status to complete
        processing_status[session_id]['in_progress'] = False
        processing_status[session_id]['csv_filename'] = csv_filename
        processing_status[session_id]['csv_download_url'] = f'/download_csv/{csv_filename}'

    except Exception as e:
        print(f"Error in background processing: {e}")
        import traceback
        traceback.print_exc()
        processing_status[session_id]['in_progress'] = False
        processing_status[session_id]['error'] = str(e)

    finally:
        # Clean up the temporary directory
        try:
            if pdf_dir_to_keep.exists():
                shutil.rmtree(pdf_dir_to_keep.parent)
        except:
            pass


@app.route('/extract_revenues', methods=['POST'])
def extract_revenues():
    """
    Start revenue extraction process in background.
    Returns session ID for progress tracking.
    """
    if 'zip_file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    zip_file = request.files['zip_file']

    if zip_file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if not zip_file.filename.endswith('.zip'):
        return jsonify({'error': 'File must be a ZIP archive'}), 400

    try:
        # Create a persistent temporary directory for this session
        session_id = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        temp_dir = UPLOAD_FOLDER / f'temp_{session_id}'
        temp_dir.mkdir(exist_ok=True)

        # Save the ZIP file
        zip_path = temp_dir / 'uploaded.zip'
        zip_file.save(str(zip_path))

        # Extract the ZIP file
        pdf_dir = temp_dir / 'pdfs'
        pdf_dir.mkdir(exist_ok=True)

        print(f"Extracting ZIP file: {zip_path}")

        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(pdf_dir)

        # Find all PDF files in the extracted directory
        pdf_files = list(pdf_dir.rglob('*.pdf'))

        if not pdf_files:
            shutil.rmtree(temp_dir)
            return jsonify({'error': 'No PDF files found in ZIP archive'}), 400

        print(f"Found {len(pdf_files)} PDF file(s)")

        # Initialize status tracking
        processing_status[session_id] = {
            'total': len(pdf_files),
            'current': 0,
            'current_file': '',
            'in_progress': True,
            'results': [],
            'errors': []
        }

        # Start background processing
        thread = threading.Thread(
            target=process_pdfs_background,
            args=(session_id, pdf_files, pdf_dir)
        )
        thread.daemon = True
        thread.start()

        # Return session ID for progress tracking
        return jsonify({
            'session_id': session_id,
            'total_files': len(pdf_files)
        })

    except zipfile.BadZipFile:
        return jsonify({'error': 'Invalid ZIP file'}), 400
    except Exception as e:
        print(f"Error processing request: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Server error: {str(e)}'}), 500


@app.route('/status/<session_id>')
def get_status(session_id):
    """Get processing status for a session."""
    if session_id not in processing_status:
        return jsonify({'error': 'Session not found'}), 404

    status = processing_status[session_id]

    return jsonify({
        'total': status['total'],
        'current': status['current'],
        'current_file': status['current_file'],
        'in_progress': status['in_progress'],
        'results': status['results'],
        'errors': status['errors'],
        'csv_filename': status.get('csv_filename'),
        'csv_download_url': status.get('csv_download_url'),
        'error': status.get('error')
    })


@app.route('/download_csv/<filename>')
def download_csv(filename):
    """Download the generated CSV file."""
    csv_path = UPLOAD_FOLDER / filename

    if not csv_path.exists():
        return "CSV file not found", 404

    return send_file(
        csv_path,
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename
    )


if __name__ == '__main__':
    # Disable reloader to prevent status dict from being cleared
    app.run(debug=True, host='0.0.0.0', port=5001, use_reloader=False)
