"""
Web Frontend for Financial Report Downloader

Flask web application that allows users to input entity names and download
their financial reports.
"""

from flask import Flask, render_template, request, jsonify, send_file, send_from_directory
import os
from pathlib import Path
import zipfile
import io
from datetime import datetime
import threading
import csv

# Import the search functions
from download_financial_report import search_fac_api, search_google, search_emma

app = Flask(__name__)

# Configure upload folder
DOWNLOAD_FOLDER = Path('./web_downloads')
DOWNLOAD_FOLDER.mkdir(exist_ok=True)

# Store download status for progress tracking
download_status = {}


def process_entities(entities_list, sources=None, session_id=''):
    """
    Process a list of entities and download their reports.

    Args:
        entities_list: List of entity names
        sources: List of sources to try (e.g., ['fac', 'emma']) or None for default
        session_id: Unique session identifier
    """
    global download_status

    session_folder = DOWNLOAD_FOLDER / session_id
    session_folder.mkdir(exist_ok=True)

    download_status[session_id] = {
        'total': len(entities_list),
        'current': 0,
        'successful': [],
        'failed': [],
        'in_progress': True,
        'current_entity': '',
        'fac_details': {}  # Store FAC metadata for each entity
    }

    sources_to_try = {
        'fac': search_fac_api,
        'google': search_google,
        'emma': search_emma
    }

    # Use provided sources or default to FAC only
    if sources is None or len(sources) == 0:
        source_list = ['fac']
    else:
        source_list = sources

    for idx, entity_name in enumerate(entities_list, 1):
        entity_name = entity_name.strip()

        if not entity_name:
            continue

        download_status[session_id]['current'] = idx
        download_status[session_id]['current_entity'] = entity_name

        # Generate filename
        safe_name = entity_name.replace(' ', '_').replace(',', '').replace('/', '_')
        output_filename = f"{safe_name}_Report.pdf"
        full_output_path = session_folder / output_filename

        # Try to download
        success = False
        source_used = None

        for src in source_list:
            if success:
                break

            source_func = sources_to_try[src]
            try:
                # For FAC API, request metadata
                if src == 'fac':
                    result = source_func(entity_name, str(full_output_path), return_metadata=True)
                    if isinstance(result, tuple):
                        success, metadata = result
                        if success:
                            # Store FAC metadata for this entity
                            download_status[session_id]['fac_details'][entity_name] = metadata
                    else:
                        success = result
                else:
                    success = source_func(entity_name, str(full_output_path))

                if success:
                    source_used = src
                    download_status[session_id]['successful'].append({
                        'entity': entity_name,
                        'filename': output_filename,
                        'source': src
                    })
                    break
            except Exception as e:
                print(f"Error with {src}: {e}")

        if not success:
            download_status[session_id]['failed'].append(entity_name)

    download_status[session_id]['in_progress'] = False


@app.route('/')
def index():
    """Render the main page."""
    return render_template('index.html')


@app.route('/download', methods=['POST'])
def download():
    """Handle download request."""
    data = request.json
    entities_text = data.get('entities', '')
    sources = data.get('sources', ['fac'])  # Get array of sources

    # Split by newlines and filter empty lines
    entities_list = [e.strip() for e in entities_text.split('\n') if e.strip()]

    if not entities_list:
        return jsonify({'error': 'No entities provided'}), 400

    # Create unique session ID
    session_id = datetime.now().strftime('%Y%m%d_%H%M%S')

    # Start download process in background thread
    thread = threading.Thread(
        target=process_entities,
        args=(entities_list, sources, session_id)
    )
    thread.daemon = True
    thread.start()

    return jsonify({
        'session_id': session_id,
        'total': len(entities_list)
    })


@app.route('/status/<session_id>')
def status(session_id):
    """Get download status for a session."""
    if session_id not in download_status:
        return jsonify({'error': 'Session not found'}), 404

    return jsonify(download_status[session_id])


def generate_csv_report(session_id):
    """
    Generate CSV report of download status.

    Args:
        session_id: Unique session identifier

    Returns:
        String containing CSV data
    """
    if session_id not in download_status:
        return None

    status = download_status[session_id]
    output = io.StringIO()
    writer = csv.writer(output)

    # Write header
    writer.writerow(['Entity Name', 'Status', 'Filename', 'Source'])

    # Write successful downloads
    for item in status['successful']:
        writer.writerow([
            item['entity'],
            'Success',
            item['filename'],
            item['source'].upper()
        ])

    # Write failed downloads
    for entity in status['failed']:
        writer.writerow([
            entity,
            'Failed',
            'N/A',
            'N/A'
        ])

    return output.getvalue()


@app.route('/download_csv/<session_id>')
def download_csv(session_id):
    """Download CSV report of download status."""
    csv_data = generate_csv_report(session_id)

    if csv_data is None:
        return "Session not found", 404

    # Create in-memory file
    memory_file = io.BytesIO()
    memory_file.write(csv_data.encode('utf-8'))
    memory_file.seek(0)

    return send_file(
        memory_file,
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'download_report_{session_id}.csv'
    )


@app.route('/download_zip/<session_id>')
def download_zip(session_id):
    """Download all PDFs as a ZIP file with CSV report."""
    session_folder = DOWNLOAD_FOLDER / session_id

    if not session_folder.exists():
        return "Session not found", 404

    # Create ZIP file in memory
    memory_file = io.BytesIO()

    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Add all PDF files
        for pdf_file in session_folder.glob('*.pdf'):
            zf.write(pdf_file, pdf_file.name)

        # Add CSV report
        csv_data = generate_csv_report(session_id)
        if csv_data:
            zf.writestr(f'download_report_{session_id}.csv', csv_data)

    memory_file.seek(0)

    return send_file(
        memory_file,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'financial_reports_{session_id}.zip'
    )


@app.route('/download_file/<session_id>/<filename>')
def download_file(session_id, filename):
    """Download individual PDF file."""
    session_folder = DOWNLOAD_FOLDER / session_id

    if not session_folder.exists():
        return "Session not found", 404

    return send_from_directory(session_folder, filename, as_attachment=True)


if __name__ == '__main__':
    # Disable reloader to prevent status dict from being cleared
    app.run(debug=True, host='0.0.0.0', port=5003, use_reloader=False)
