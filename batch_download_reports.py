"""
Batch Financial Report Downloader

Reads a list of entities from a CSV file and downloads their financial reports.
"""

import csv
import argparse
import sys
from pathlib import Path

# Import the search functions from download_financial_report.py
from download_financial_report import search_fac_api, search_google, search_emma


def batch_download(csv_file: str, source: str = 'fac', output_dir: str = '.'):
    """
    Download financial reports for multiple entities listed in a CSV file.

    Args:
        csv_file: Path to CSV file with entity_name and output_filename columns
        source: Which source to use ('fac', 'google', 'emma', or 'all')
        output_dir: Directory to save downloaded PDFs
    """

    # Create output directory if it doesn't exist
    output_path = Path(output_dir).resolve()
    output_path.mkdir(parents=True, exist_ok=True)

    print("="*70)
    print("BATCH FINANCIAL REPORT DOWNLOADER")
    print("="*70)
    print(f"CSV File: {csv_file}")
    print(f"Source: {source}")
    print(f"Output Directory: {output_path}")
    print("="*70)

    # Read CSV file
    try:
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)

            # Verify required columns
            if 'entity_name' not in reader.fieldnames:
                print("ERROR: CSV file must have 'entity_name' column")
                sys.exit(1)

            entities = list(reader)

        if not entities:
            print("ERROR: CSV file is empty or has no data rows")
            sys.exit(1)

        print(f"\nFound {len(entities)} entities to process\n")

    except FileNotFoundError:
        print(f"ERROR: CSV file not found: {csv_file}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR reading CSV file: {e}")
        sys.exit(1)

    # Track results
    successful = []
    failed = []

    # Process each entity
    for idx, row in enumerate(entities, 1):
        entity_name = row.get('entity_name', '').strip()

        if not entity_name:
            print(f"[{idx}/{len(entities)}] Skipping empty entity name")
            continue

        # Determine output filename
        if 'output_filename' in row and row['output_filename'].strip():
            output_filename = row['output_filename'].strip()
        else:
            # Auto-generate filename from entity name
            safe_name = entity_name.replace(' ', '_').replace(',', '').replace('/', '_')
            output_filename = f"{safe_name}_Report.pdf"

        # Full output path
        full_output_path = output_path / output_filename

        print(f"\n{'='*70}")
        print(f"[{idx}/{len(entities)}] Processing: {entity_name}")
        print(f"Output: {output_filename}")
        print(f"{'='*70}")

        # Try to download based on source
        success = False

        sources_to_try = {
            'fac': search_fac_api,
            'google': search_google,
            'emma': search_emma
        }

        if source == 'all':
            source_list = ['fac', 'google', 'emma']
        else:
            source_list = [source]

        for src in source_list:
            if success:
                break

            source_func = sources_to_try[src]
            try:
                success = source_func(entity_name, str(full_output_path))
                if success:
                    print(f"\n[SUCCESS] Downloaded from {src.upper()}")
                    successful.append((entity_name, output_filename, src))
                    break
            except Exception as e:
                print(f"\n[ERROR] Error with {src}: {e}")

        if not success:
            print(f"\n[FAILED] Could not download from any source")
            failed.append(entity_name)

    # Print summary
    print("\n" + "="*70)
    print("DOWNLOAD SUMMARY")
    print("="*70)
    print(f"Total Entities: {len(entities)}")
    print(f"Successful Downloads: {len(successful)}")
    print(f"Failed Downloads: {len(failed)}")
    print("="*70)

    if successful:
        print("\n[+] Successfully Downloaded:")
        for entity, filename, src in successful:
            print(f"  - {entity}")
            print(f"    File: {filename} (Source: {src})")

    if failed:
        print("\n[-] Failed to Download:")
        for entity in failed:
            print(f"  - {entity}")

    print(f"\n{'='*70}")
    print(f"Files saved to: {output_path}")
    print(f"{'='*70}")


def main():
    parser = argparse.ArgumentParser(
        description='Batch download financial reports from a CSV file'
    )
    parser.add_argument('csv_file',
                       help='Path to CSV file with entity_name column (and optional output_filename column)')
    parser.add_argument('-s', '--source',
                       choices=['fac', 'google', 'emma', 'all'],
                       default='fac',
                       help='Which source(s) to try (default: fac)')
    parser.add_argument('-o', '--output-dir',
                       default='./downloaded_reports',
                       help='Output directory for downloaded PDFs (default: ./downloaded_reports)')

    args = parser.parse_args()

    batch_download(args.csv_file, args.source, args.output_dir)


if __name__ == "__main__":
    main()
