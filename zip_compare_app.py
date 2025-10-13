"""
ZIP File Comparison Web Application

Flask web app that accepts two ZIP files ("correct" and "test"),
compares files with matching filenames, and generates a CSV report
showing the match percentage between file contents.
"""

from flask import Flask, render_template, request, jsonify, send_file
import os
from pathlib import Path
import zipfile
import tempfile
import csv
import hashlib
from datetime import datetime
import threading
import shutil

app = Flask(__name__)

# Configure upload folder
UPLOAD_FOLDER = Path('./zip_compare_uploads')
UPLOAD_FOLDER.mkdir(exist_ok=True)

# Store processing status for progress tracking
processing_status = {}

# Maximum file size (500 MB)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024


@app.route('/')
def index():
    """Render the ZIP comparison page."""
    return render_template('zip_compare.html')


def calculate_file_hash(file_path):
    """Calculate SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def calculate_match_percentage(correct_file, test_file):
    """
    Calculate match percentage between two files.
    Returns 100.0 if files are identical, otherwise calculates byte-by-byte match.
    """
    # First check if files are identical using hash
    correct_hash = calculate_file_hash(correct_file)
    test_hash = calculate_file_hash(test_file)

    if correct_hash == test_hash:
        return 100.0

    # If not identical, calculate byte-by-byte match percentage
    with open(correct_file, 'rb') as f1, open(test_file, 'rb') as f2:
        correct_bytes = f1.read()
        test_bytes = f2.read()

    # Compare byte by byte
    max_length = max(len(correct_bytes), len(test_bytes))
    min_length = min(len(correct_bytes), len(test_bytes))

    matching_bytes = 0
    for i in range(min_length):
        if correct_bytes[i] == test_bytes[i]:
            matching_bytes += 1

    # Calculate percentage
    if max_length == 0:
        return 100.0

    return (matching_bytes / max_length) * 100.0


def compare_zips_background(session_id, correct_zip_path, test_zip_path):
    """
    Background task to compare two ZIP files.

    Args:
        session_id: Unique session identifier
        correct_zip_path: Path to the "correct" ZIP file
        test_zip_path: Path to the "test" ZIP file
    """
    global processing_status

    correct_temp_dir = None
    test_temp_dir = None

    try:
        # Extract both ZIP files
        correct_temp_dir = UPLOAD_FOLDER / f'correct_{session_id}'
        test_temp_dir = UPLOAD_FOLDER / f'test_{session_id}'
        correct_temp_dir.mkdir(exist_ok=True)
        test_temp_dir.mkdir(exist_ok=True)

        print(f"Extracting correct ZIP: {correct_zip_path}")
        with zipfile.ZipFile(correct_zip_path, 'r') as zip_ref:
            zip_ref.extractall(correct_temp_dir)

        print(f"Extracting test ZIP: {test_zip_path}")
        with zipfile.ZipFile(test_zip_path, 'r') as zip_ref:
            zip_ref.extractall(test_temp_dir)

        # Get all files from correct ZIP (recursively)
        correct_files = {}
        for file_path in correct_temp_dir.rglob('*'):
            if file_path.is_file():
                relative_path = file_path.relative_to(correct_temp_dir)
                correct_files[str(relative_path)] = file_path

        # Get all files from test ZIP (recursively)
        test_files = {}
        for file_path in test_temp_dir.rglob('*'):
            if file_path.is_file():
                relative_path = file_path.relative_to(test_temp_dir)
                test_files[str(relative_path)] = file_path

        # All unique filenames
        all_filenames = set(correct_files.keys()) | set(test_files.keys())
        total_files = len(all_filenames)

        print(f"Found {len(correct_files)} files in correct ZIP")
        print(f"Found {len(test_files)} files in test ZIP")
        print(f"Total unique filenames: {total_files}")

        processing_status[session_id]['total'] = total_files

        results = []

        for idx, filename in enumerate(sorted(all_filenames), 1):
            processing_status[session_id]['current'] = idx
            processing_status[session_id]['current_file'] = filename

            print(f"\n[{idx}/{total_files}] Comparing: {filename}")

            result = {
                'filename': filename,
                'status': '',
                'match_percentage': 0.0,
                'correct_size': 0,
                'test_size': 0
            }

            # Check if file exists in both ZIPs
            in_correct = filename in correct_files
            in_test = filename in test_files

            if in_correct and in_test:
                # Both files exist - compare them
                correct_file = correct_files[filename]
                test_file = test_files[filename]

                result['correct_size'] = correct_file.stat().st_size
                result['test_size'] = test_file.stat().st_size

                try:
                    match_percentage = calculate_match_percentage(correct_file, test_file)
                    result['match_percentage'] = match_percentage

                    if match_percentage == 100.0:
                        result['status'] = 'identical'
                        print(f"  Status: IDENTICAL")
                    else:
                        result['status'] = 'different'
                        print(f"  Status: DIFFERENT ({match_percentage:.2f}% match)")

                except Exception as e:
                    result['status'] = 'error'
                    result['error'] = str(e)
                    print(f"  Error comparing files: {e}")

            elif in_correct and not in_test:
                result['status'] = 'missing_in_test'
                result['correct_size'] = correct_files[filename].stat().st_size
                print(f"  Status: MISSING IN TEST")

            elif in_test and not in_correct:
                result['status'] = 'missing_in_correct'
                result['test_size'] = test_files[filename].stat().st_size
                print(f"  Status: MISSING IN CORRECT")

            results.append(result)
            processing_status[session_id]['results'].append(result)

        # Calculate overall statistics
        identical_count = sum(1 for r in results if r['status'] == 'identical')
        different_count = sum(1 for r in results if r['status'] == 'different')
        missing_in_test_count = sum(1 for r in results if r['status'] == 'missing_in_test')
        missing_in_correct_count = sum(1 for r in results if r['status'] == 'missing_in_correct')
        error_count = sum(1 for r in results if r['status'] == 'error')

        # Calculate overall match percentage
        # Only consider files that exist in both ZIPs
        comparable_files = [r for r in results if r['status'] in ['identical', 'different']]
        if comparable_files:
            overall_match = sum(r['match_percentage'] for r in comparable_files) / len(comparable_files)
        else:
            overall_match = 0.0

        processing_status[session_id]['stats'] = {
            'identical': identical_count,
            'different': different_count,
            'missing_in_test': missing_in_test_count,
            'missing_in_correct': missing_in_correct_count,
            'errors': error_count,
            'overall_match': overall_match
        }

        # Generate CSV file
        csv_filename = f"zip_comparison_{session_id}.csv"
        csv_path = UPLOAD_FOLDER / csv_filename

        with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['filename', 'status', 'match_percentage', 'correct_size_bytes', 'test_size_bytes', 'notes']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()

            for result in results:
                notes = ''
                if result['status'] == 'identical':
                    notes = 'Files are identical'
                elif result['status'] == 'different':
                    notes = f"{result['match_percentage']:.2f}% match"
                elif result['status'] == 'missing_in_test':
                    notes = 'File exists in correct ZIP but missing in test ZIP'
                elif result['status'] == 'missing_in_correct':
                    notes = 'File exists in test ZIP but missing in correct ZIP'
                elif result['status'] == 'error':
                    notes = f"Error: {result.get('error', 'Unknown error')}"

                writer.writerow({
                    'filename': result['filename'],
                    'status': result['status'],
                    'match_percentage': f"{result['match_percentage']:.2f}" if result['match_percentage'] > 0 else '',
                    'correct_size_bytes': result['correct_size'] if result['correct_size'] > 0 else '',
                    'test_size_bytes': result['test_size'] if result['test_size'] > 0 else '',
                    'notes': notes
                })

            # Add summary row
            writer.writerow({})
            writer.writerow({
                'filename': 'SUMMARY',
                'status': '',
                'match_percentage': '',
                'correct_size_bytes': '',
                'test_size_bytes': '',
                'notes': ''
            })
            writer.writerow({
                'filename': 'Overall Match Percentage',
                'status': '',
                'match_percentage': f"{overall_match:.2f}",
                'correct_size_bytes': '',
                'test_size_bytes': '',
                'notes': f"Based on {len(comparable_files)} comparable files"
            })
            writer.writerow({
                'filename': 'Identical Files',
                'status': '',
                'match_percentage': '',
                'correct_size_bytes': identical_count,
                'test_size_bytes': '',
                'notes': ''
            })
            writer.writerow({
                'filename': 'Different Files',
                'status': '',
                'match_percentage': '',
                'correct_size_bytes': different_count,
                'test_size_bytes': '',
                'notes': ''
            })
            writer.writerow({
                'filename': 'Missing in Test',
                'status': '',
                'match_percentage': '',
                'correct_size_bytes': missing_in_test_count,
                'test_size_bytes': '',
                'notes': ''
            })
            writer.writerow({
                'filename': 'Missing in Correct',
                'status': '',
                'match_percentage': '',
                'correct_size_bytes': missing_in_correct_count,
                'test_size_bytes': '',
                'notes': ''
            })

        print(f"\nCSV file generated: {csv_path}")
        print(f"Overall match: {overall_match:.2f}%")

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
        # Clean up temporary directories
        try:
            if correct_temp_dir and correct_temp_dir.exists():
                shutil.rmtree(correct_temp_dir)
            if test_temp_dir and test_temp_dir.exists():
                shutil.rmtree(test_temp_dir)
            # Also clean up the uploaded ZIP files
            if correct_zip_path.exists():
                correct_zip_path.unlink()
            if test_zip_path.exists():
                test_zip_path.unlink()
        except:
            pass


@app.route('/compare_zips', methods=['POST'])
def compare_zips():
    """
    Start ZIP comparison process in background.
    Returns session ID for progress tracking.
    """
    if 'correct_zip' not in request.files or 'test_zip' not in request.files:
        return jsonify({'error': 'Both ZIP files are required'}), 400

    correct_zip = request.files['correct_zip']
    test_zip = request.files['test_zip']

    if correct_zip.filename == '' or test_zip.filename == '':
        return jsonify({'error': 'Both files must be selected'}), 400

    if not correct_zip.filename.endswith('.zip') or not test_zip.filename.endswith('.zip'):
        return jsonify({'error': 'Both files must be ZIP archives'}), 400

    try:
        # Create session ID
        session_id = datetime.now().strftime('%Y%m%d_%H%M%S_%f')

        # Save both ZIP files
        correct_zip_path = UPLOAD_FOLDER / f'correct_{session_id}.zip'
        test_zip_path = UPLOAD_FOLDER / f'test_{session_id}.zip'

        correct_zip.save(str(correct_zip_path))
        test_zip.save(str(test_zip_path))

        print(f"Saved correct ZIP: {correct_zip_path}")
        print(f"Saved test ZIP: {test_zip_path}")

        # Initialize status tracking
        processing_status[session_id] = {
            'total': 0,
            'current': 0,
            'current_file': '',
            'in_progress': True,
            'results': [],
            'stats': {}
        }

        # Start background processing
        thread = threading.Thread(
            target=compare_zips_background,
            args=(session_id, correct_zip_path, test_zip_path)
        )
        thread.daemon = True
        thread.start()

        # Return session ID for progress tracking
        return jsonify({
            'session_id': session_id
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
        'stats': status.get('stats', {}),
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
    app.run(debug=True, host='0.0.0.0', port=5002, use_reloader=False)
