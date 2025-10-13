"""
Financial Report Downloader

Downloads financial reports for civic entities (housing authorities, transit agencies,
water districts, municipalities, etc.) from multiple sources: FAC API, Google Search, and EMMA.
"""

import argparse
import requests
import json
import re
import sys
import time
from urllib.parse import quote, urljoin
from pathlib import Path

# Import API keys from config
try:
    from config import FAC_API_KEY, SERPAPI_KEY
except ImportError:
    # Fallback if config.py doesn't exist
    FAC_API_KEY = "F6pOX4Hz6T4b7qMbMSHA5onhsVmfKRTE4IG4wRzh"
    SERPAPI_KEY = "your_serpapi_key_here"


def sanitize_filename(name: str) -> str:
    """Convert entity name to safe filename."""
    # Remove special characters, replace spaces with underscores
    safe_name = re.sub(r'[^\w\s-]', '', name)
    safe_name = re.sub(r'[-\s]+', '_', safe_name)
    return safe_name.strip('_')


def download_file(url: str, filename: str) -> bool:
    """Download a file from URL and save it."""
    try:
        print(f"  Downloading from: {url}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=30, stream=True)
        response.raise_for_status()

        # Check if it's actually a PDF
        content_type = response.headers.get('content-type', '').lower()
        if 'pdf' not in content_type and not url.lower().endswith('.pdf'):
            # Check the first few bytes for PDF signature
            first_bytes = response.content[:4] if len(response.content) >= 4 else b''
            if first_bytes != b'%PDF':
                print(f"  Warning: Downloaded file may not be a PDF")

        with open(filename, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        file_size = Path(filename).stat().st_size
        print(f"  Successfully downloaded: {filename} ({file_size:,} bytes)")
        return True
    except Exception as e:
        print(f"  Error downloading: {e}")
        return False


def search_fac_api(entity_name: str, output_filename: str, return_metadata: bool = False):
    """
    Search the Federal Audit Clearinghouse API for Single Audit reports.
    API Documentation: https://api.fac.gov/

    Args:
        entity_name: Name of the entity to search for
        output_filename: Path to save the downloaded PDF
        return_metadata: If True, returns (success, metadata) tuple; if False, returns bool

    Returns:
        If return_metadata=False: bool (success status)
        If return_metadata=True: tuple of (bool, dict) where dict contains search metadata
    """
    print(f"\n[1] Searching Federal Audit Clearinghouse API...")

    metadata = {
        'found_count': 0,
        'all_entries': [],
        'downloaded_entry': None
    }

    try:
        # FAC API requires an API key
        base_url = "https://api.fac.gov/general"

        headers = {
            "X-Api-Key": FAC_API_KEY
        }

        # Escape single quotes for SQL query
        escaped_name = entity_name.replace("'", "''")

        # Try multiple search strategies to find the entity
        # Strategy 1: Exact phrase match (most precise)
        # Strategy 2: Key words with wildcards (more flexible)

        # Expand common abbreviations before processing
        expanded_name = entity_name.lower()
        abbreviation_map = {
            r'\bsf\b': 'san francisco',
            r'\bla\b': 'los angeles',
            r'\bnyc\b': 'new york city',
            r'\bny\b': 'new york',
            r'\bdc\b': 'district columbia',
            r'\b&\b': 'and'
        }

        for abbrev, full in abbreviation_map.items():
            expanded_name = re.sub(abbrev, full, expanded_name)

        # Extract key identifying words (remove common filler words)
        common_words = {'the', 'of', 'and', 'a', 'an', 'for', 'in', 'at', 'to', 'by'}
        words = expanded_name.split()
        key_words = [w for w in words if w not in common_words and len(w) > 2]

        # Build search patterns
        search_patterns = [
            # Exact phrase
            f"auditee_name=ilike.*{escaped_name}*"
        ]

        # Add flexible pattern with key words if we have multiple words
        if len(key_words) > 1:
            # Escape quotes in key words and join with wildcards
            # Note: Use % for wildcards in PostgreSQL ilike, not *
            escaped_key_words = [w.replace("'", "''") for w in key_words]

            # Strategy 2a: Original word order
            flexible_pattern = '%'.join(escaped_key_words)
            search_patterns.append(f"auditee_name=ilike.%{flexible_pattern}%")

            # Strategy 2b: Smart word reordering - identify entity types vs location names
            # Entity type keywords: housing, authority, transit, water, district, agency, etc.
            entity_type_keywords = {'housing', 'authority', 'transit', 'water', 'district',
                                   'agency', 'commission', 'board', 'department', 'service',
                                   'redevelopment', 'development', 'port', 'airport', 'utility'}

            # Separate entity type words from location/other words
            entity_type_words = []
            other_words = []
            for word in key_words:
                if word.lower() in entity_type_keywords:
                    entity_type_words.append(word)
                else:
                    other_words.append(word)

            # If we have both entity type and location words, try entity type first
            if entity_type_words and other_words:
                # Rearrange: entity type words first, then location words
                reordered_escaped = [w.replace("'", "''") for w in (entity_type_words + other_words)]
                reordered_pattern = '%'.join(reordered_escaped)
                if reordered_pattern != flexible_pattern:
                    search_patterns.append(f"auditee_name=ilike.%{reordered_pattern}%")

        # Remove None values
        search_patterns = [p for p in search_patterns if p]

        print(f"  Querying API with entity name: {entity_name}")

        # Try each search pattern
        response = None
        audits = []

        for idx, pattern in enumerate(search_patterns):
            search_url = f"{base_url}?{pattern}&limit=5&order=fy_end_date.desc"

            if idx > 0:
                print(f"  Trying alternative search pattern {idx + 1}...")

            response = requests.get(search_url, headers=headers, timeout=30)

            if response.status_code == 200:
                audits = response.json()
                if audits and len(audits) > 0:
                    break  # Found results, stop trying other patterns

        if response and response.status_code == 200:
            if audits and len(audits) > 0:
                metadata['found_count'] = len(audits)
                print(f"  Found {len(audits)} audit(s)")

                # Score each audit result based on how well it matches the search query
                # This helps prioritize the best match when multiple results are returned
                scored_audits = []
                for audit in audits:
                    auditee_name = audit.get('auditee_name', 'Unknown')
                    auditee_lower = auditee_name.lower()

                    # Calculate match score based on key words from expanded name
                    score = 0
                    for keyword in key_words:
                        if keyword in auditee_lower:
                            score += 1

                    # Bonus points for exact location matches (helps distinguish SF from Denver)
                    # Check for multi-word location phrases
                    if 'san' in key_words and 'francisco' in key_words:
                        if 'san francisco' in auditee_lower or 'san-francisco' in auditee_lower:
                            score += 10  # Strong bonus for exact location match
                    if 'los' in key_words and 'angeles' in key_words:
                        if 'los angeles' in auditee_lower:
                            score += 10
                    if 'new' in key_words and 'york' in key_words:
                        if 'new york' in auditee_lower:
                            score += 10

                    scored_audits.append((score, audit))

                # Sort by score (descending), then by fiscal year (descending)
                scored_audits.sort(key=lambda x: (-x[0], x[1].get('fy_end_date', '')), reverse=True)

                # Store all entries (in scored order)
                for idx, (score, audit) in enumerate(scored_audits):
                    auditee_name = audit.get('auditee_name', 'Unknown')
                    fy_end = audit.get('fy_end_date', 'Unknown')
                    report_id = audit.get('report_id')

                    entry_info = {
                        'index': idx + 1,
                        'auditee_name': auditee_name,
                        'fiscal_year': fy_end,
                        'report_id': report_id
                    }
                    metadata['all_entries'].append(entry_info)

                    print(f"  - {auditee_name} (FY {fy_end}) - Report ID: {report_id} [Score: {score}]")

                # Try to download from the best-scored audits first
                for idx, (score, audit) in enumerate(scored_audits):
                    auditee_name = audit.get('auditee_name', 'Unknown')
                    fy_end = audit.get('fy_end_date', 'Unknown')
                    report_id = audit.get('report_id')

                    if report_id:
                        # Use the working PDF URL pattern from gpha.py
                        pdf_url = f"https://app.fac.gov/dissemination/report/pdf/{report_id}"

                        print(f"  Attempting to download from: {pdf_url}")

                        try:
                            pdf_response = requests.get(pdf_url, timeout=30)

                            if pdf_response.status_code == 200:
                                # Save the PDF
                                with open(output_filename, 'wb') as f:
                                    f.write(pdf_response.content)

                                file_size = Path(output_filename).stat().st_size
                                print(f"  Successfully downloaded: {output_filename} ({file_size:,} bytes)")

                                metadata['downloaded_entry'] = {
                                    'index': idx + 1,
                                    'auditee_name': auditee_name,
                                    'fiscal_year': fy_end,
                                    'report_id': report_id
                                }

                                if return_metadata:
                                    return True, metadata
                                return True
                            else:
                                print(f"  Failed to download PDF (status: {pdf_response.status_code})")
                        except Exception as e:
                            print(f"  Download error: {e}")
                            continue

                print("  Could not download PDF from any audit")
            else:
                print("  No audits found for this entity")
        else:
            print(f"  API returned status code: {response.status_code}")
            if response.status_code == 403:
                print("  Note: API key may be invalid or expired")

    except Exception as e:
        print(f"  Error accessing FAC API: {e}")

    if return_metadata:
        return False, metadata
    return False


def search_google(entity_name: str, output_filename: str) -> bool:
    """
    Search Google for financial reports (CAFR/ACFR) for the entity using SerpAPI.
    """
    print(f"\n[2] Searching Google for financial reports (via SerpAPI)...")

    try:
        from serpapi import GoogleSearch
    except ImportError:
        print("  Error: SerpAPI library not installed.")
        print("  Please install it using: pip install google-search-results")
        return False

    try:
        # Check if SerpAPI key is configured
        if SERPAPI_KEY == "your_serpapi_key_here" or not SERPAPI_KEY:
            print("  Warning: SerpAPI key not configured")
            print("  Get a free API key from https://serpapi.com/")
            print("  Update SERPAPI_KEY in download_financial_report.py")
            return False

        # Construct search queries with increasing specificity
        search_terms = [
            f'"{entity_name}" ACFR filetype:pdf',  # Exact phrase match
            f"{entity_name} ACFR filetype:pdf",
            f'"{entity_name}" annual comprehensive financial report filetype:pdf',
            f"{entity_name} annual comprehensive financial report filetype:pdf",
            f'"{entity_name}" CAFR filetype:pdf',
            f"{entity_name} CAFR filetype:pdf"
        ]

        for search_query in search_terms:
            print(f"  Trying: {search_query}")

            # Search using SerpAPI
            params = {
                "q": search_query,
                "api_key": SERPAPI_KEY,
                "num": 10  # Get top 10 results
            }

            search = GoogleSearch(params)
            results = search.get_dict()

            # Extract organic results
            organic_results = results.get("organic_results", [])

            if not organic_results:
                print(f"  No results found")
                continue

            print(f"  Found {len(organic_results)} result(s)")

            # Try each result
            for idx, result in enumerate(organic_results[:10], 1):  # Try first 10
                link = result.get("link", "")
                title = result.get("title", "")
                snippet = result.get("snippet", "")

                # Check if link is a PDF
                if not link.lower().endswith('.pdf'):
                    continue

                # Verify entity name match in title, snippet, or URL
                # Extract key parts of the entity name for matching
                entity_lower = entity_name.lower()
                entity_words = set(entity_lower.split())

                # Remove common words that don't help identify the entity
                stop_words = {'of', 'the', 'a', 'an', 'and', 'for'}
                key_words = entity_words - stop_words

                # Check if key identifying words appear in title, snippet, or URL
                combined_text = f"{title} {snippet} {link}".lower()

                matching_words = [word for word in key_words if word in combined_text]
                match_ratio = len(matching_words) / len(key_words) if key_words else 0

                print(f"  Attempt {idx}: {title[:60]}...")
                print(f"    URL: {link[:80]}...")
                print(f"    Match score: {match_ratio:.0%} ({len(matching_words)}/{len(key_words)} key words)")

                # Enhanced jurisdiction and entity type validation
                is_city_entity = 'city' in entity_lower
                is_county_entity = 'county' in entity_lower

                # Check for entity type specificity (authority, agency, district, etc.)
                entity_type_keywords = ['authority', 'agency', 'district', 'commission', 'board', 'department', 'service']
                has_entity_type = any(keyword in entity_lower for keyword in entity_type_keywords)

                # Extract specific entity descriptors (housing, transit, water, development, etc.)
                specific_descriptors = ['housing', 'transit', 'water', 'development', 'redevelopment',
                                       'transportation', 'port', 'airport', 'utility', 'parking']
                entity_descriptors = [desc for desc in specific_descriptors if desc in entity_lower]

                # Check for generic municipality reports (County of X, City of X) vs specific entities
                # These patterns indicate a general government report, not a specific authority/agency
                generic_county_pattern = r'\bcounty of\b'
                generic_city_pattern = r'\bcity of\b'

                is_generic_county_result = re.search(generic_county_pattern, combined_text) and not any(keyword in combined_text for keyword in entity_type_keywords)
                is_generic_city_result = re.search(generic_city_pattern, combined_text) and not any(keyword in combined_text for keyword in entity_type_keywords)

                # If we're looking for a specific authority/agency, reject generic government reports
                if has_entity_type:
                    if is_generic_county_result:
                        print(f"    Warning: Result appears to be generic county government report")
                        print(f"    Skipping - looking for specific {[k for k in entity_type_keywords if k in entity_lower][0]}, not general county")
                        continue
                    if is_generic_city_result:
                        print(f"    Warning: Result appears to be generic city government report")
                        print(f"    Skipping - looking for specific {[k for k in entity_type_keywords if k in entity_lower][0]}, not general city")
                        continue

                # Check for jurisdiction mismatch (city vs county)
                has_wrong_jurisdiction = False
                if is_city_entity and 'county' in combined_text and 'city' not in combined_text:
                    has_wrong_jurisdiction = True
                    print(f"    Warning: Result mentions 'county' but entity is a city")
                elif is_county_entity and 'city' in combined_text and 'county' not in combined_text:
                    has_wrong_jurisdiction = True
                    print(f"    Warning: Result mentions 'city' but entity is a county")

                # Skip if wrong jurisdiction detected
                if has_wrong_jurisdiction:
                    print(f"    Skipping - jurisdiction mismatch")
                    continue

                # If entity has a specific type (authority, agency, etc.), check that it's present in result
                # This prevents matching general city/county reports when looking for specific agencies
                if has_entity_type:
                    result_has_entity_type = any(keyword in combined_text for keyword in entity_type_keywords)
                    if not result_has_entity_type:
                        print(f"    Warning: Entity has specific type (authority/agency) but result appears to be general municipality report")
                        print(f"    Skipping - entity type mismatch")
                        continue

                # If entity has specific descriptors (housing, transit, etc.), require at least one to match
                if entity_descriptors:
                    result_has_descriptors = any(desc in combined_text for desc in entity_descriptors)
                    if not result_has_descriptors:
                        print(f"    Warning: Entity has specific descriptor ({'/'.join(entity_descriptors)}) but none found in result")
                        print(f"    Skipping - missing entity-specific descriptors")
                        continue

                # Skip if match ratio is too low (less than 50% of key words match)
                # Lowered threshold from 60% to 50% to be more inclusive
                if match_ratio < 0.5 and len(key_words) > 0:
                    print(f"    Skipping - insufficient match to '{entity_name}'")
                    continue

                try:
                    if download_file(link, output_filename):
                        # Verify it's a reasonable size (> 100KB)
                        file_size = Path(output_filename).stat().st_size
                        if file_size > 100000:
                            print(f"  Successfully downloaded: {file_size:,} bytes")
                            print(f"  Entity match verified: {match_ratio:.0%}")
                            return True
                        else:
                            print(f"  File too small ({file_size} bytes), trying next link...")
                except Exception as e:
                    print(f"  Download failed: {e}")
                    continue

            time.sleep(1)  # Brief delay between queries

        print("  Could not find suitable PDF via Google search")

    except Exception as e:
        print(f"  Error with Google search: {e}")
        import traceback
        traceback.print_exc()

    return False


def search_emma(entity_name: str, output_filename: str, state: str = "CA") -> bool:
    """
    Search EMMA (Electronic Municipal Market Access) for financial disclosures using Selenium.
    Website: https://emma.msrb.org
    """
    print(f"\n[3] Searching EMMA (Municipal Securities Rulemaking Board)...")

    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.chrome.options import Options
    except ImportError:
        print("  Error: Selenium not installed.")
        print("  Please install it using: pip install selenium")
        return False

    driver = None
    try:
        print(f"  Launching browser to search EMMA...")

        # Setup Chrome options
        chrome_options = Options()
        # chrome_options.add_argument("--headless")  # Temporarily disable headless for debugging
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--window-size=1920,1080")

        # Create driver
        driver = webdriver.Chrome(options=chrome_options)

        # Navigate to EMMA main search page
        emma_url = "https://emma.msrb.org/"
        print(f"  Navigating to: {emma_url}")
        driver.get(emma_url)

        # Wait for page to load
        wait = WebDriverWait(driver, 20)
        time.sleep(3)

        # Find and click on "Search" or "Issuers" to get to search functionality
        print(f"  Looking for search functionality...")

        # Try to find the main search box
        try:
            # Look for search input - EMMA typically has a search box on the main page
            search_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='text'], input[type='search']")

            search_box = None
            for inp in search_inputs:
                # Find a visible search box
                if inp.is_displayed():
                    search_box = inp
                    break

            if not search_box:
                # Try clicking on search/issuer links
                try:
                    search_link = driver.find_element(By.LINK_TEXT, "Issuers")
                    search_link.click()
                    time.sleep(2)
                    search_box = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='text'], input[type='search']")))
                except:
                    pass

            if search_box:
                print(f"  Searching for: {entity_name}")
                search_box.clear()
                search_box.send_keys(entity_name)
                search_box.send_keys(Keys.RETURN)
                time.sleep(4)  # Wait for results to load

                # Look for the entity in search results
                print("  Analyzing search results...")

                # Find links that contain the entity name
                all_links = driver.find_elements(By.TAG_NAME, "a")
                entity_keywords = set(entity_name.lower().split()) - {'of', 'the', 'a'}

                # Identify critical keywords that must match exactly (city/county names)
                entity_lower = entity_name.lower()
                critical_keywords = []
                for keyword in entity_keywords:
                    # Cities, counties, and unique identifiers must match exactly
                    if keyword not in ['housing', 'authority', 'city', 'county']:
                        critical_keywords.append(keyword)

                for link in all_links:
                    try:
                        link_text = link.text.lower()
                        href = link.get_attribute("href") or ""

                        # Check if ALL critical keywords are present
                        has_all_critical = all(keyword in link_text for keyword in critical_keywords)

                        if not has_all_critical:
                            continue

                        # Check if link matches entity overall
                        matches = sum(1 for keyword in entity_keywords if keyword in link_text)
                        if matches >= len(entity_keywords) * 0.6:  # 60% of keywords match
                            print(f"  Found potential match: {link.text[:80]}")

                            # Click on the entity link
                            link.click()
                            time.sleep(3)

                            # Now look for continuing disclosure documents
                            print("  Looking for financial disclosure documents...")

                            # Try to find links to continuing disclosure or financial reports
                            disclosure_links = driver.find_elements(By.PARTIAL_LINK_TEXT, "Continuing Disclosure")
                            if not disclosure_links:
                                disclosure_links = driver.find_elements(By.PARTIAL_LINK_TEXT, "Financial")
                            if not disclosure_links:
                                disclosure_links = driver.find_elements(By.PARTIAL_LINK_TEXT, "Annual Report")

                            for disc_link in disclosure_links[:3]:
                                try:
                                    disc_link.click()
                                    time.sleep(3)

                                    # Look for PDF links with CAFR/ACFR
                                    pdf_links = driver.find_elements(By.XPATH, "//a[contains(@href, '.pdf')]")

                                    for pdf_link in pdf_links[:10]:
                                        try:
                                            pdf_text = pdf_link.text.lower()
                                            pdf_href = pdf_link.get_attribute("href")

                                            # Check if it's a CAFR/ACFR
                                            if any(term in pdf_text for term in ['cafr', 'acfr', 'comprehensive', 'annual financial']):
                                                print(f"    Found report: {pdf_text[:60]}...")

                                                if pdf_href and download_file(pdf_href, output_filename):
                                                    file_size = Path(output_filename).stat().st_size
                                                    if file_size > 100000:
                                                        driver.quit()
                                                        return True
                                        except:
                                            continue

                                    driver.back()
                                    time.sleep(2)
                                except:
                                    continue

                            # If we didn't find anything, go back and try next result
                            driver.back()
                            time.sleep(2)
                            break  # Only try first good match

                    except:
                        continue

        except Exception as e:
            print(f"  Error navigating EMMA: {e}")

        print("  No suitable financial reports found on EMMA")

    except Exception as e:
        print(f"  Error accessing EMMA: {e}")
        import traceback
        traceback.print_exc()

    finally:
        if driver:
            driver.quit()

    return False


def main():
    parser = argparse.ArgumentParser(
        description='Download financial reports for civic entities (housing authorities, transit agencies, water districts, etc.)'
    )
    parser.add_argument('entity_name', help='Name of the entity (e.g., "Oakland Housing Authority", "Bay Area Rapid Transit")')
    parser.add_argument('-o', '--output', help='Output filename (default: auto-generated)')
    parser.add_argument('-s', '--source',
                       choices=['fac', 'google', 'emma', 'all'],
                       default='all',
                       help='Which source(s) to try (default: all)')

    args = parser.parse_args()

    entity_name = args.entity_name

    # Generate output filename if not specified
    if args.output:
        output_filename = args.output
    else:
        safe_name = sanitize_filename(entity_name)
        output_filename = f"{safe_name}_Financial_Report.pdf"

    print("="*70)
    print("FINANCIAL REPORT DOWNLOADER")
    print("="*70)
    print(f"Entity: {entity_name}")
    print(f"Output: {output_filename}")
    print("="*70)

    success = False

    # Try each source based on user selection
    sources = {
        'fac': search_fac_api,
        'google': search_google,
        'emma': search_emma
    }

    if args.source == 'all':
        sources_to_try = ['fac', 'google', 'emma']
    else:
        sources_to_try = [args.source]

    for source_name in sources_to_try:
        if success:
            break

        source_func = sources[source_name]
        success = source_func(entity_name, output_filename)

        if success:
            print(f"\n{'='*70}")
            print(f"SUCCESS! Downloaded from {source_name.upper()}")
            print(f"File saved as: {output_filename}")
            print(f"{'='*70}")
            break

    if not success:
        print(f"\n{'='*70}")
        print("FAILED: Could not download financial report from any source")
        print("\nTroubleshooting suggestions:")
        print("1. Try searching manually on https://api.fac.gov")
        print("2. Search Google for '{} ACFR PDF'".format(entity_name))
        print("3. Visit https://emma.msrb.org and search manually")
        print(f"{'='*70}")
        sys.exit(1)


if __name__ == "__main__":
    main()
