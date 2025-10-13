"""
PDF Financial Report Revenue Scraper

This script extracts total revenue from housing authority financial PDF reports.
Example: Housing Authority of the City of Oakland
"""

import re
import sys
from typing import Optional, Dict, List
import argparse


def extract_revenue_from_pdf(pdf_path: str, show_tables: bool = False) -> Dict[str, any]:
    """
    Extract total revenue from a financial PDF report.

    Args:
        pdf_path: Path to the PDF file
        show_tables: If True, print table contents for debugging

    Returns:
        Dictionary containing entity name and revenue information
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
        'revenue_line': None,
        'page_number': None,
        'all_revenue_matches': [],
        'table_matches': []
    }

    # Common patterns for total revenue in financial statements
    revenue_patterns = [
        r'total\s+revenue[s]?\s*[\$\:]?\s*([\d,]+\.?\d*)',
        r'total\s+operating\s+revenue[s]?\s*[\$\:]?\s*([\d,]+\.?\d*)',
        r'revenue[s]?\s+total\s*[\$\:]?\s*([\d,]+\.?\d*)',
        r'total\s+income\s*[\$\:]?\s*([\d,]+\.?\d*)',
        r'gross\s+revenue[s]?\s*[\$\:]?\s*([\d,]+\.?\d*)',
    ]

    # Pattern for entity name (housing authority)
    entity_patterns = [
        r'housing\s+authority\s+of\s+(?:the\s+)?(?:city\s+of\s+)?([A-Za-z\s]+)',
        r'([A-Za-z\s]+)\s+housing\s+authority',
    ]

    try:
        with pdfplumber.open(pdf_path) as pdf:
            print(f"Processing PDF: {pdf_path}")
            print(f"Total pages: {len(pdf.pages)}\n")

            for page_num, page in enumerate(pdf.pages, 1):
                text = page.extract_text()

                if not text:
                    continue

                # Try to extract entity name if not found yet
                if not result['entity_name']:
                    for pattern in entity_patterns:
                        match = re.search(pattern, text, re.IGNORECASE)
                        if match:
                            result['entity_name'] = match.group(0).strip()
                            print(f"Found entity: {result['entity_name']}")
                            break

                # Search for revenue in text
                for pattern in revenue_patterns:
                    matches = re.finditer(pattern, text, re.IGNORECASE)
                    for match in matches:
                        # Extract the full line for context
                        line_start = max(0, match.start() - 50)
                        line_end = min(len(text), match.end() + 50)
                        context = text[line_start:line_end].strip()

                        # Clean up the revenue value
                        revenue_str = match.group(1).replace(',', '')
                        try:
                            revenue_value = float(revenue_str)

                            match_info = {
                                'page': page_num,
                                'value': revenue_value,
                                'context': context,
                                'pattern': pattern
                            }
                            result['all_revenue_matches'].append(match_info)

                            # Keep the first or largest revenue found
                            if result['total_revenue'] is None or revenue_value > result['total_revenue']:
                                result['total_revenue'] = revenue_value
                                result['revenue_line'] = context
                                result['page_number'] = page_num
                        except ValueError:
                            continue

                # Extract and analyze tables with enhanced logic
                # Try multiple extraction strategies
                tables = page.extract_tables()

                # If default doesn't find tables, try text-based strategy
                if not tables:
                    table_settings = {
                        "vertical_strategy": "text",
                        "horizontal_strategy": "text",
                    }
                    tables = page.extract_tables(table_settings)

                if show_tables and tables:
                    print(f"\n--- Page {page_num}: Found {len(tables)} table(s) ---")

                for table_idx, table in enumerate(tables):
                    if show_tables:
                        print(f"\nTable {table_idx + 1} on page {page_num}:")
                        for row_idx, row in enumerate(table):
                            print(f"  Row {row_idx}: {row}")

                    # Process each row in the table
                    for row_idx, row in enumerate(table):
                        if not row:
                            continue

                        # Clean and join non-None cells
                        row_cells = [str(cell).strip() if cell else '' for cell in row]
                        row_text = ' '.join(row_cells)

                        # Check if this row contains revenue-related keywords
                        # Note: some PDFs split words across cells, so we need flexible patterns
                        revenue_keywords = [
                            r'total\s+operating\s+revenue',
                            r'total\s+operatin.*revenue',  # Handles split words like "operatin" + "g revenues"
                            r'total.*revenue',
                            r'operating\s+revenue.*total',
                            r'revenue.*total'
                        ]

                        is_revenue_row = False
                        for keyword in revenue_keywords:
                            if re.search(keyword, row_text, re.IGNORECASE):
                                is_revenue_row = True
                                break

                        if is_revenue_row:
                            # Check if this page is a consolidated/combining statement or a detail
                            page_text_lower = text.lower()
                            is_consolidated = False
                            is_detail_page = False

                            # Look for "total" column header in the table to determine if consolidated
                            # Check a few rows up from the revenue row to find headers
                            header_rows = table[max(0, row_idx - 10):row_idx]
                            for header_row in header_rows:
                                header_text = ' '.join([str(cell).lower() if cell else '' for cell in header_row])
                                if 'total' in header_text and any(word in header_text for word in ['federal', 'programs', 'eliminations']):
                                    is_consolidated = True
                                    break

                            # Also check page text for consolidated indicators
                            if not is_consolidated:
                                consolidated_keywords = ['federal, other housing and general', 'combining schedule']
                                for keyword in consolidated_keywords:
                                    if keyword in page_text_lower:
                                        is_consolidated = True
                                        break

                            # Check for detail/breakdown indicators
                            detail_keywords = ['other housing programs', 'federal programs only', 'detail']
                            for keyword in detail_keywords:
                                if keyword in page_text_lower and 'federal, other housing and general' not in page_text_lower:
                                    is_detail_page = True
                                    break

                            # Extract all numeric values from the row
                            # Look for numbers with optional commas, decimals, and dollar signs
                            number_pattern = r'\$?\s*([\d,]+(?:\.\d+)?)'
                            numbers = re.findall(number_pattern, row_text)

                            if show_tables:
                                print(f"  -> REVENUE ROW FOUND: {row_text[:100]}")
                                print(f"     Consolidated: {is_consolidated}, Detail: {is_detail_page}")
                                print(f"     Extracted numbers: {numbers}")

                            # For consolidated statements, take the LAST/rightmost number (the total column)
                            # For detail pages, we may still want to see them but deprioritize
                            if is_consolidated and numbers:
                                # Take only the last (rightmost/total) number
                                numbers_to_process = [numbers[-1]]
                                priority_boost = 1000000000  # Boost consolidated totals
                            else:
                                numbers_to_process = numbers
                                priority_boost = 0

                            # Process each number found
                            for num_str in numbers_to_process:
                                try:
                                    # Clean the number string
                                    num_str_clean = num_str.replace(',', '').replace('$', '').strip()
                                    if not num_str_clean:
                                        continue

                                    revenue_value = float(num_str_clean)

                                    # Filter out very small values (likely row numbers, percentages, etc.)
                                    if revenue_value > 1000:
                                        match_info = {
                                            'page': page_num,
                                            'value': revenue_value,
                                            'context': row_text,
                                            'source': 'table',
                                            'table_index': table_idx,
                                            'row_index': row_idx,
                                            'row_cells': row_cells,
                                            'is_consolidated': is_consolidated,
                                            'is_detail': is_detail_page,
                                            'priority': revenue_value + priority_boost
                                        }
                                        result['all_revenue_matches'].append(match_info)
                                        result['table_matches'].append(match_info)

                                        # Update the main total revenue prioritizing consolidated statements
                                        current_priority = result.get('revenue_priority', 0)
                                        if result['total_revenue'] is None or match_info['priority'] > current_priority:
                                            result['total_revenue'] = revenue_value
                                            result['revenue_line'] = row_text
                                            result['page_number'] = page_num
                                            result['revenue_priority'] = match_info['priority']
                                            result['is_consolidated'] = is_consolidated

                                            if show_tables:
                                                print(f"     -> NEW MAX REVENUE: {format_currency(revenue_value)} (Priority: {match_info['priority']})")
                                except (ValueError, AttributeError):
                                    continue

    except FileNotFoundError:
        print(f"Error: File not found: {pdf_path}")
        sys.exit(1)
    except Exception as e:
        print(f"Error processing PDF: {e}")
        sys.exit(1)

    return result


def format_currency(amount: float) -> str:
    """Format a number as currency."""
    return f"${amount:,.2f}"


def main():
    parser = argparse.ArgumentParser(
        description='Extract total revenue from housing authority financial PDF reports'
    )
    parser.add_argument('pdf_path', help='Path to the PDF file to process')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='Show all revenue matches found')
    parser.add_argument('-t', '--show-tables', action='store_true',
                       help='Show detailed table extraction debugging information')

    args = parser.parse_args()

    result = extract_revenue_from_pdf(args.pdf_path, show_tables=args.show_tables)

    print("\n" + "="*60)
    print("FINANCIAL REPORT ANALYSIS")
    print("="*60)

    if result['entity_name']:
        print(f"Entity: {result['entity_name']}")
    else:
        print("Entity: Unable to determine")

    if result['total_revenue']:
        print(f"Total Revenue: {format_currency(result['total_revenue'])}")
        print(f"Found on page: {result['page_number']}")
        if result.get('is_consolidated'):
            print(f"Source: Consolidated/Combining Statement [TOTAL]")
        print(f"\nContext: {result['revenue_line'][:200]}")
    else:
        print("Total Revenue: Not found")
        print("\nNo revenue information could be extracted from the PDF.")
        print("This may be due to:")
        print("  - PDF is scanned/image-based (OCR required)")
        print("  - Revenue is labeled differently than expected")
        print("  - PDF structure is non-standard")

    if args.verbose and result['all_revenue_matches']:
        print(f"\n\nAll revenue matches found ({len(result['all_revenue_matches'])}):")
        print("-"*60)
        for i, match in enumerate(result['all_revenue_matches'], 1):
            source = match.get('source', 'text')
            consolidated_flag = " [CONSOLIDATED]" if match.get('is_consolidated') else ""
            detail_flag = " [DETAIL]" if match.get('is_detail') else ""
            print(f"\n{i}. Page {match['page']}: {format_currency(match['value'])} [Source: {source}]{consolidated_flag}{detail_flag}")
            print(f"   Context: {match['context'][:150]}...")
            if source == 'table':
                print(f"   Table {match.get('table_index', '?') + 1}, Row {match.get('row_index', '?')}")

    # Show table-specific summary
    if result['table_matches']:
        print(f"\n\nTable Revenue Matches ({len(result['table_matches'])}):")
        print("-"*60)
        for i, match in enumerate(result['table_matches'], 1):
            print(f"{i}. Page {match['page']}, Table {match.get('table_index', 0) + 1}: {format_currency(match['value'])}")
            print(f"   Row cells: {match.get('row_cells', [])[:5]}...")  # Show first 5 cells

    print("\n" + "="*60)


if __name__ == "__main__":
    main()
