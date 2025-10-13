"""Quick test to see what's on page 94 of the PDF"""
import pdfplumber

pdf_path = "Oakland_Housing.pdf"

with pdfplumber.open(pdf_path) as pdf:
    page = pdf.pages[93]  # Page 94 (0-indexed)

    print("=" * 80)
    print("TEXT EXTRACTION:")
    print("=" * 80)
    text = page.extract_text()

    # Find the revenue section
    lines = text.split('\n')
    for i, line in enumerate(lines):
        if 'total operating revenue' in line.lower():
            # Print context around this line
            start = max(0, i - 3)
            end = min(len(lines), i + 4)
            print(f"\nFound at line {i}:")
            print("-" * 80)
            for j in range(start, end):
                marker = ">>> " if j == i else "    "
                print(f"{marker}{lines[j]}")

    print("\n" + "=" * 80)
    print("TABLE EXTRACTION:")
    print("=" * 80)

    # Try different table extraction settings
    tables = page.extract_tables()
    print(f"Default settings: Found {len(tables)} tables")

    # Try with different settings
    table_settings = {
        "vertical_strategy": "lines",
        "horizontal_strategy": "lines",
    }
    tables2 = page.extract_tables(table_settings)
    print(f"Lines strategy: Found {len(tables2)} tables")

    table_settings3 = {
        "vertical_strategy": "text",
        "horizontal_strategy": "text",
    }
    tables3 = page.extract_tables(table_settings3)
    print(f"Text strategy: Found {len(tables3)} tables")

    if tables3:
        print(f"\nShowing first table with text strategy:")
        for i, row in enumerate(tables3[0][:20]):  # First 20 rows
            print(f"Row {i}: {row}")
