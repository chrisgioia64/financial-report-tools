# Financial Report Downloader & Analysis Tools

A comprehensive suite of tools for downloading, comparing, and analyzing financial reports from multiple sources including the Federal Audit Clearinghouse (FAC) API, Google Search, and EMMA.

## Features

### 1. Financial Report Downloader
- **Multi-source search**: FAC API, Google Search, EMMA
- **Smart search algorithms**:
  - Abbreviation expansion (SF → San Francisco, LA → Los Angeles, etc.)
  - Word-order independent matching
  - Intelligent result scoring with location priority
- **Flexible entity name matching**: Works with various name formats
- **Batch processing**: Download reports for multiple entities at once

### 2. Web Frontend (Port 5003)
- User-friendly interface for batch downloading
- Real-time progress tracking with session management
- FAC metadata display showing all search results
- Expandable details for each downloaded entity
- ZIP file export for batch downloads

### 3. ZIP File Comparison Tool (Port 5002)
- Compare two ZIP files with matching filenames
- Byte-by-byte comparison with SHA256 hash verification
- Generate detailed CSV reports with match percentages
- Visual progress tracking
- Summary statistics (identical files, differences, missing files)

### 4. PDF Revenue Scraper (Port 5001)
- Extract revenue data from financial report PDFs
- Table detection and text extraction using pdfplumber
- Upload ZIP files containing multiple PDFs
- Export extracted data to CSV

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd sample-project
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure API keys in `config.py`:
```python
FAC_API_KEY = "your_fac_api_key"
SERPAPI_KEY = "your_serpapi_key"  # Optional, for Google search
```

## Usage

### Command Line Interface

Download a single financial report:
```bash
python download_financial_report.py "Housing Authority San Francisco" -s fac
```

Download from all sources:
```bash
python download_financial_report.py "San Francisco Housing Authority" -s all
```

Batch download from CSV file:
```bash
python batch_download_reports.py entities.csv
```

### Web Applications

Start the Financial Report Downloader web app:
```bash
python web_app.py
# Access at http://localhost:5003
```

Start the ZIP Comparison Tool:
```bash
python zip_compare_app.py
# Access at http://localhost:5002
```

Start the PDF Revenue Scraper:
```bash
python revenue_extractor_app.py
# Access at http://localhost:5001
```

## Smart Search Features

### Abbreviation Expansion
The system automatically expands common abbreviations:
- SF → San Francisco
- LA → Los Angeles
- NYC → New York City
- & → and

### Intelligent Result Scoring
When multiple results are found, the system scores each result:
- +1 point for each matching keyword
- +10 bonus points for exact location phrase matches
- Results sorted by score, then by fiscal year

### Word Order Independence
The search works regardless of word order:
- "Housing Authority San Francisco" ✓
- "San Francisco Housing Authority" ✓
- "Housing Authority of the City & County of SF" ✓

All find: "HOUSING AUTHORITY OF THE CITY AND COUNTY OF SAN FRANCISCO"

## Project Structure

```
sample-project/
├── download_financial_report.py  # Main CLI tool
├── web_app.py                     # Web frontend (port 5003)
├── zip_compare_app.py             # ZIP comparison tool (port 5002)
├── revenue_extractor_app.py       # PDF revenue scraper (port 5001)
├── batch_download_reports.py      # Batch processing script
├── config.py                      # API configuration
├── requirements.txt               # Python dependencies
├── templates/                     # HTML templates
│   ├── index.html                # Financial downloader UI
│   ├── zip_compare.html          # ZIP comparison UI
│   └── revenue_extractor.html    # Revenue scraper UI
└── README.md                      # This file
```

## API Sources

### Federal Audit Clearinghouse (FAC)
- API: https://api.fac.gov/
- Most reliable source for housing authorities and federal grant recipients
- Returns up to 5 recent audits per entity

### Google Search (via SerpAPI)
- Searches for CAFR/ACFR reports
- Validates entity type and jurisdiction matching
- Optional - requires SerpAPI key

### EMMA (Municipal Securities)
- Website: https://emma.msrb.org
- Uses Selenium for web automation
- Good for municipal entities and bond issuers

## Requirements

- Python 3.7+
- Flask
- requests
- pdfplumber
- selenium (optional, for EMMA)
- google-search-results (optional, for Google search)

See `requirements.txt` for complete list.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

[Add your license here]

## Acknowledgments

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
