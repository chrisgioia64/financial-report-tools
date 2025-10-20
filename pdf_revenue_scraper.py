"""
PDF Financial Report Revenue Scraper

This script extracts total revenue from financial PDF reports by:
1. Finding the "Total operating revenue" line
2. Extracting all positive nonoperating income items
3. Summing them together for total revenue
"""

import re
import sys
from typing import Dict, List, Optional, Tuple
import argparse


def is_large_number_row(row_text: str) -> bool:
    """Check if row contains a large number (7+ digits) with minimal text."""
    has_large_number = bool(re.search(r'\d[\d\s,]{6,}', row_text))
    word_count = len(re.findall(r'[a-zA-Z]{4,}', row_text))
    return has_large_number and word_count <= 1


def has_expense_marker_nearby(table: List, row_idx: int) -> bool:
    """Check if any of the next 3 rows mention 'expense' or 'loss'."""
    for offset in range(1, 4):
        if row_idx + offset < len(table):
            next_row = table[row_idx + offset]
            next_text = ' '.join([str(cell).strip() if cell else '' for cell in next_row])
            if re.search(r'expense|operat.*loss', next_text, re.IGNORECASE):
                return True
    return False


def extract_number_from_row(row_cells: List) -> Optional[float]:
    """Extract the first valid number from a table row (skipping small numbers)."""
    # Process each cell to find the first large number
    for cell in row_cells:
        if not cell:
            continue

        cell_text = str(cell).strip()

        # Pattern to match a number with optional parentheses (negative), commas, spaces
        # Match formats: 1,234  or  1 234  or  (1,234)  or  $1,234.56
        pattern = r'\$?\s*(\()?[\s]*([\d,\s]+)[\s]*(\))?'
        match = re.search(pattern, cell_text)

        if not match:
            continue

        open_paren = match.group(1)
        num_str = match.group(2)
        close_paren = match.group(3)

        # Clean the number - remove commas and spaces
        clean_num = num_str.replace(',', '').replace(' ', '').strip()

        if not clean_num or not clean_num.isdigit():
            continue

        try:
            value = float(clean_num)

            # Skip very small values (likely row numbers, page numbers, percentages)
            if abs(value) < 1000:
                continue

            # Apply negative sign if in parentheses
            if open_paren and close_paren:
                value = -value

            return value
        except ValueError:
            continue

    return None


def process_table_for_revenues(
    table: List,
    page_num: int,
    in_operating_section: bool,
    in_nonoperating_section: bool,
    page_has_nonoperating: bool,
    show_tables: bool = False
) -> Tuple[Optional[float], List[Dict], bool, bool]:
    """
    Process a single table to extract operating revenue and nonoperating items.

    Returns:
        Tuple of (operating_revenue, nonoperating_items, in_operating_section, in_nonoperating_section)
    """
    operating_revenue = None
    nonoperating_items = []

    for row_idx, row in enumerate(table):
        if not row:
            continue

        row_cells = [str(cell).strip() if cell else '' for cell in row]
        row_text = ' '.join(row_cells)

        # Update section tracking based on row content
        if re.search(r'operating\s+revenue', row_text, re.IGNORECASE):
            if not re.search(r'non.*operating', row_text, re.IGNORECASE):
                in_operating_section = True
                in_nonoperating_section = False
        # Match "nonoperating income" or "nonoperating revenues" with flexible word splitting
        # Handles: "noperating rev en ues" or "Nonoperating income" or "nonoperating revenues"
        elif re.search(r'noperating.*(income|revenue|rev.*ues)', row_text, re.IGNORECASE):
            in_nonoperating_section = True
            in_operating_section = False
        elif re.search(r'operating\s+expenses:', row_text, re.IGNORECASE):
            in_operating_section = False

        # Auto-start nonoperating section after operating revenues end
        if not in_operating_section and not in_nonoperating_section and page_has_nonoperating:
            if re.search(r'(interest\s+income|investment|gain|rental)', row_text, re.IGNORECASE):
                in_nonoperating_section = True

        # Extract operating revenue
        if in_operating_section and not operating_revenue:
            # Method 1: Explicit "Total operating revenue" label (flexible for split words)
            # Matches: "total operating revenue" or "total ope rat ing revenue"
            # Pattern allows for spaces/breaks in "operating": ope.*rat.*ing or operating
            if re.search(r'total.*(ope.*rat.*ing|operating).*revenue', row_text, re.IGNORECASE):
                value = extract_number_from_row(row_cells)
                if value and value > 1000:
                    operating_revenue = value
                    in_operating_section = False
                    if show_tables:
                        print(f"  Operating revenue found (labeled): ${value:,.2f} on row {row_idx}")
            # Method 2: Structural detection (large number + expense marker)
            elif is_large_number_row(row_text) and has_expense_marker_nearby(table, row_idx):
                value = extract_number_from_row(row_cells)
                if value and value > 1000:
                    operating_revenue = value
                    in_operating_section = False
                    if show_tables:
                        print(f"  Operating revenue found (structural): ${value:,.2f} on row {row_idx}")

        # Extract nonoperating items
        if in_nonoperating_section:
            # Skip total/summary rows and position/balance rows
            # Flexible matching for split words like "net pos iti on" or "ange in net pos iti on"
            # Match partial words: "ange" (from "change"), "position", "balance"
            is_summary = re.search(r'(total|position|balance|ange.*net|net.*position)', row_text, re.IGNORECASE)
            has_descriptive_text = bool(re.search(r'[a-zA-Z]{3,}', row_text))

            # End section if we hit position/balance/change rows (even if words are split)
            if re.search(r'(position|balance|ange.*net)', row_text, re.IGNORECASE):
                in_nonoperating_section = False
                continue

            if not is_summary and has_descriptive_text:
                value = extract_number_from_row(row_cells)
                # Only include positive (non-negative) values
                if value and value > 0:
                    nonoperating_items.append({
                        'value': value,
                        'page': page_num,
                        'label': row_text.strip()[:60]
                    })
                    if show_tables:
                        print(f"  Nonoperating item: ${value:,.2f}")

    return operating_revenue, nonoperating_items, in_operating_section, in_nonoperating_section


def extract_revenue_from_pdf(pdf_path: str, show_tables: bool = False) -> Dict:
    """
    Extract total revenue from a financial PDF report.

    Args:
        pdf_path: Path to the PDF file
        show_tables: If True, print debugging information

    Returns:
        Dictionary containing revenue information
    """
    try:
        import pdfplumber
    except ImportError:
        print("Error: pdfplumber library not installed.")
        print("Please install it using: pip install pdfplumber")
        sys.exit(1)

    result = {
        'entity_name': None,
        'total_revenue': None,
        'operating_revenue': None,
        'non_operating_revenue': None,
        'non_operating_items': [],
        'page_number': None,
    }

    try:
        with pdfplumber.open(pdf_path) as pdf:
            print(f"Processing PDF: {pdf_path}")
            print(f"Total pages: {len(pdf.pages)}\n")

            # Track sections across pages
            in_operating_section = False
            in_nonoperating_section = False

            for page_num, page in enumerate(pdf.pages, 1):
                text = page.extract_text()
                if not text:
                    continue

                # Check if this page has relevant sections
                page_has_operating = bool(re.search(r'operating\s+revenue(s)?:?', text, re.IGNORECASE))
                page_has_nonoperating = bool(re.search(r'nonoperating\s+(income|revenue)', text, re.IGNORECASE))

                # Reset section tracking for each new page unless we're still on the revenue statement page
                if page_num != result.get('page_number'):
                    in_operating_section = False
                    in_nonoperating_section = False

                # Set initial section state based on page content
                if page_has_operating and not result['operating_revenue']:
                    in_operating_section = True

                # Extract tables - try text strategy first as it's more reliable
                table_settings = {
                    "vertical_strategy": "text",
                    "horizontal_strategy": "text",
                }
                tables = page.extract_tables(table_settings)

                # Fall back to default if text strategy fails
                if not tables or (tables and len(tables[0]) == 0):
                    tables = page.extract_tables()

                if show_tables and tables:
                    print(f"\n--- Page {page_num}: Found {len(tables)} table(s) ---")

                # Process each table
                for table_idx, table in enumerate(tables):
                    op_rev, nonop_items, in_op, in_nonop = process_table_for_revenues(
                        table, page_num, in_operating_section, in_nonoperating_section,
                        page_has_nonoperating, show_tables
                    )

                    # Update section states
                    in_operating_section = in_op
                    in_nonoperating_section = in_nonop

                    # Store operating revenue
                    if op_rev and not result['operating_revenue']:
                        result['operating_revenue'] = op_rev
                        result['page_number'] = page_num

                    # Collect nonoperating items
                    result['non_operating_items'].extend(nonop_items)

        # Calculate final totals
        if result['non_operating_items']:
            result['non_operating_revenue'] = sum(item['value'] for item in result['non_operating_items'])

        if result['operating_revenue'] and result['non_operating_revenue']:
            result['total_revenue'] = result['operating_revenue'] + result['non_operating_revenue']
        elif result['operating_revenue']:
            result['total_revenue'] = result['operating_revenue']

    except FileNotFoundError:
        print(f"Error: File not found: {pdf_path}")
        sys.exit(1)
    except Exception as e:
        print(f"Error processing PDF: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    return result


def format_currency(amount: float) -> str:
    """Format a number as currency."""
    return f"${amount:,.2f}"


def main():
    parser = argparse.ArgumentParser(
        description='Extract total revenue from financial PDF reports'
    )
    parser.add_argument('pdf_path', help='Path to the PDF file to process')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='Show detailed extraction information')
    parser.add_argument('-t', '--show-tables', action='store_true',
                       help='Show table extraction debugging information')

    args = parser.parse_args()

    result = extract_revenue_from_pdf(args.pdf_path, show_tables=args.show_tables)

    print("\n" + "="*60)
    print("FINANCIAL REPORT ANALYSIS")
    print("="*60)

    if result['entity_name']:
        print(f"Entity: {result['entity_name']}")

    if result['total_revenue']:
        print(f"Total Revenue: {format_currency(result['total_revenue'])}")

        # Show breakdown if we have both components
        if result['operating_revenue'] and result['non_operating_revenue']:
            print(f"\nRevenue Breakdown:")
            print(f"  Operating Revenue:     {format_currency(result['operating_revenue'])}")
            print(f"  Non-Operating Income:  {format_currency(result['non_operating_revenue'])} ({len(result['non_operating_items'])} items)")

            if args.verbose and result['non_operating_items']:
                print(f"\n  Non-Operating Income Items:")
                for item in result['non_operating_items']:
                    label = item['label'][:50]
                    print(f"    - {label}: {format_currency(item['value'])}")

            print(f"\n  Total Revenue:         {format_currency(result['total_revenue'])}")
        elif result['operating_revenue']:
            print(f"  (Operating Revenue Only)")

        if result['page_number']:
            print(f"\nFound on page: {result['page_number']}")
    else:
        print("Total Revenue: Not found")
        print("\nNo revenue information could be extracted from the PDF.")

    print("\n" + "="*60)


if __name__ == "__main__":
    main()
