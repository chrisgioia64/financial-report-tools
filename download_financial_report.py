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


def download_file(url: str, filename: str, driver=None) -> bool:
    """Download a file from URL and save it. If driver is provided, uses browser session."""
    try:
        print(f"  Downloading from: {url}")

        if driver:
            # Use Selenium driver to download with browser session/cookies
            # Get cookies from Selenium and use them with requests
            cookies = driver.get_cookies()
            session = requests.Session()
            for cookie in cookies:
                session.cookies.set(cookie['name'], cookie['value'])

            headers = {
                'User-Agent': driver.execute_script("return navigator.userAgent;")
            }
            response = session.get(url, headers=headers, timeout=30, stream=True)
        else:
            # Standard download without browser session
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
        # Remove apostrophes from words to handle variations like "america's" vs "americas"
        key_words = [w.replace("'", "") for w in words if w not in common_words and len(w.replace("'", "")) > 2]

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

            # Initialize reordered_pattern to flexible_pattern by default
            reordered_pattern = flexible_pattern

            # If we have both entity type and location words, try entity type first
            if entity_type_words and other_words:
                # Rearrange: entity type words first, then location words
                reordered_escaped = [w.replace("'", "''") for w in (entity_type_words + other_words)]
                reordered_pattern = '%'.join(reordered_escaped)
                if reordered_pattern != flexible_pattern:
                    search_patterns.append(f"auditee_name=ilike.%{reordered_pattern}%")

            # Strategy 2c: Individual word matching (most flexible - handles any word order)
            # Build a pattern that requires all key words but doesn't care about order
            # This is done by creating multiple wildcards: %word1%word2%word3%
            # But we make it even more flexible by ensuring each word appears independently
            if len(key_words) >= 2:
                # Create a search that checks each word independently with AND logic
                # Use double wildcards to allow any words in between
                individual_escaped = [w.replace("'", "''") for w in key_words]
                # For PostgreSQL, we can use multiple ilike conditions combined with AND
                # But PostgREST uses a different syntax, so we'll use a very loose pattern
                # with lots of wildcards that allows words in any order
                loose_pattern = '%%'.join(individual_escaped)  # Double wildcard allows words between
                if loose_pattern != flexible_pattern and loose_pattern != reordered_pattern:
                    search_patterns.append(f"auditee_name=ilike.%{loose_pattern}%")

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
    Uses the state-specific issuer page for more targeted searching.
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

        # Configure Chrome to automatically download PDFs
        download_dir = str(Path.cwd().absolute())
        prefs = {
            "download.default_directory": download_dir,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "plugins.always_open_pdf_externally": True,  # Download PDFs instead of opening
            "safebrowsing.enabled": True
        }
        chrome_options.add_experimental_option("prefs", prefs)

        # Create driver
        driver = webdriver.Chrome(options=chrome_options)

        # Navigate to EMMA state-specific issuer page
        emma_url = f"https://emma.msrb.org/IssuerHomePage/State?state={state}"
        print(f"  Navigating to: {emma_url}")
        driver.get(emma_url)

        # Wait for page to load
        wait = WebDriverWait(driver, 20)
        time.sleep(3)

        # Check for and handle license agreement if present
        try:
            print(f"  Checking for license agreement...")

            # First, check if there are any iframes on the page
            iframes = driver.find_elements(By.TAG_NAME, "iframe")
            print(f"  DEBUG: Found {len(iframes)} iframe(s)")

            # Try to find and click the specific Accept button
            accept_button = None
            button_found_in_frame = False

            # First try in the main page
            try:
                accept_button = driver.find_element(By.CSS_SELECTOR, "#ctl00_mainContentArea_disclaimerContent_yesButton")
                print(f"  Found Accept button in main page with selector: #ctl00_mainContentArea_disclaimerContent_yesButton")
            except:
                # If not in main page, try each iframe
                for idx, iframe in enumerate(iframes):
                    try:
                        print(f"  Checking iframe {idx + 1}...")
                        driver.switch_to.frame(iframe)
                        try:
                            accept_button = driver.find_element(By.CSS_SELECTOR, "#ctl00_mainContentArea_disclaimerContent_yesButton")
                            print(f"  Found Accept button in iframe {idx + 1}")
                            button_found_in_frame = True
                            break
                        except:
                            driver.switch_to.default_content()
                            continue
                    except:
                        driver.switch_to.default_content()
                        continue

            if accept_button:
                print(f"  Clicking Accept button...")
                try:
                    # Scroll the button into view
                    driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", accept_button)
                    time.sleep(1)  # Give time for scroll to complete

                    # Try clicking with JavaScript if normal click fails
                    try:
                        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#ctl00_mainContentArea_disclaimerContent_yesButton")))
                        accept_button.click()
                    except:
                        # If normal click fails, use JavaScript click
                        print(f"  Normal click failed, using JavaScript click...")
                        driver.execute_script("arguments[0].click();", accept_button)

                    print(f"  Accept button clicked successfully")

                    # Switch back to default content if we were in an iframe
                    if button_found_in_frame:
                        driver.switch_to.default_content()

                    print(f"  Waiting for page to load after accepting...")

                    # Wait for the issuer search page to load by waiting for the search box to appear
                    try:
                        wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "#lvIssuers_filter input")))
                        print(f"  License agreement accepted and search page loaded")
                    except Exception as e:
                        print(f"  Waiting additional time for page to fully load...")
                        time.sleep(5)
                except Exception as e:
                    print(f"  Error clicking Accept button: {e}")
                    if button_found_in_frame:
                        driver.switch_to.default_content()
            else:
                print(f"  WARNING: Could not find Accept button with selector #ctl00_mainContentArea_disclaimerContent_yesButton")
                print(f"  The license agreement may have already been accepted or the page structure has changed")
        except Exception as e:
            print(f"  Error handling license agreement: {e}")
            import traceback
            traceback.print_exc()
            # Make sure we're back to default content
            try:
                driver.switch_to.default_content()
            except:
                pass

        # Find the search input box using the specific selector
        print(f"  Looking for search input box...")
        try:
            # Wait longer for the search box to appear after accepting license
            search_box = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "#lvIssuers_filter input")))
            print(f"  Found search box, searching for: {entity_name}")

            # Clear and enter the search query
            search_box.clear()
            search_box.send_keys(entity_name)

            # Wait for the table to filter
            time.sleep(2)

            # Count the number of results
            # The filtered results should be visible rows in the table
            try:
                # Look for visible table rows (not including the header)
                visible_rows = driver.find_elements(By.CSS_SELECTOR, "#lvIssuers tbody tr")

                # Filter out rows that are hidden (display: none)
                actual_results = [row for row in visible_rows if row.is_displayed() and row.get_attribute("style") != "display: none;"]

                result_count = len(actual_results)
                print(f"  Found {result_count} matching result(s)")

                if result_count == 0:
                    print("  No results found for this entity")
                    return False

                # If there's exactly one result, click on it
                if result_count == 1:
                    print("  Single result found - clicking on the link...")
                    # Find the link in the first (and only) result row
                    try:
                        link = actual_results[0].find_element(By.TAG_NAME, "a")
                        link_text = link.text
                        print(f"  Clicking on: {link_text}")
                        link.click()
                        time.sleep(3)

                        # Look for the "Financial Disclosures" tab
                        print("  Looking for Financial Disclosures tab...")
                        try:
                            # Try to find the Financial Disclosures tab/link
                            financial_tab = None
                            try:
                                financial_tab = driver.find_element(By.PARTIAL_LINK_TEXT, "Financial Disclosures")
                            except:
                                try:
                                    financial_tab = driver.find_element(By.PARTIAL_LINK_TEXT, "Financial Disclosure")
                                except:
                                    try:
                                        financial_tab = driver.find_element(By.LINK_TEXT, "FINANCIAL DISCLOSURES")
                                    except:
                                        pass

                            if financial_tab:
                                print(f"  Found Financial Disclosures tab - clicking...")
                                financial_tab.click()
                                time.sleep(3)

                                # Look for all PDF links on the page
                                print("  Searching for PDF documents...")
                                pdf_links = driver.find_elements(By.XPATH, "//a[contains(@href, '.pdf')]")

                                print(f"  Found {len(pdf_links)} PDF document(s)")

                                if len(pdf_links) > 0:
                                    # Filter PDFs to find actual financial reports
                                    # Keywords that indicate a financial report
                                    financial_keywords = [
                                        'cafr', 'acfr', 'annual financial', 'comprehensive annual',
                                        'financial statement', 'audit report', 'audited financial',
                                        'basic financial', 'financial report'
                                    ]

                                    # Keywords that indicate help/info documents to skip
                                    skip_keywords = [
                                        'fact sheet', 'help', 'guide', 'instruction', 'tutorial',
                                        'customizing', 'homepage', 'user guide', 'how to'
                                    ]

                                    # Score each PDF based on relevance
                                    scored_pdfs = []
                                    for idx, pdf_link in enumerate(pdf_links):
                                        try:
                                            pdf_text = pdf_link.text.lower()
                                            pdf_href = pdf_link.get_attribute("href").lower()
                                            combined_text = f"{pdf_text} {pdf_href}"

                                            # Skip if it's a help document
                                            if any(skip_word in combined_text for skip_word in skip_keywords):
                                                print(f"    Skipping help document: {pdf_link.text[:60]}...")
                                                continue

                                            # Calculate relevance score
                                            score = 0
                                            for keyword in financial_keywords:
                                                if keyword in combined_text:
                                                    score += 10

                                            # Bonus points for being from EMMA domain (not msrb.org help docs)
                                            if 'emma.msrb.org' in pdf_href:
                                                score += 5

                                            # Store the PDF with its score
                                            scored_pdfs.append((score, idx, pdf_link, pdf_text, pdf_href))

                                            print(f"    PDF {idx + 1}: {pdf_link.text[:60]}... (score: {score})")

                                        except Exception as e:
                                            continue

                                    # Sort by score (descending)
                                    scored_pdfs.sort(key=lambda x: -x[0])

                                    if scored_pdfs:
                                        print(f"  Found {len(scored_pdfs)} relevant PDF(s) after filtering")

                                        # Try to download the highest-scored PDF
                                        # Since EMMA blocks direct downloads, we'll click the link and let browser handle it
                                        for score, idx, pdf_link, pdf_text, pdf_href in scored_pdfs:
                                            if score > 0:  # Only try PDFs with positive score
                                                # Get link text early to avoid stale element errors
                                                try:
                                                    link_display_text = pdf_link.text[:80] if pdf_link.text else "..."
                                                except:
                                                    link_display_text = "..."

                                                print(f"  Attempting to access: {link_display_text} (score: {score})")
                                                try:
                                                    # Get the original href
                                                    original_href = pdf_link.get_attribute("href")
                                                    print(f"    URL: {original_href[:100]}...")

                                                    # Click the link to open/download the PDF
                                                    pdf_link.click()
                                                    print(f"    Clicked PDF link, waiting for download...")

                                                    # Extract the PDF filename from URL
                                                    pdf_filename = Path(original_href).name
                                                    download_path = Path.cwd() / pdf_filename

                                                    # Wait for download to complete (up to 15 seconds)
                                                    download_complete = False
                                                    for i in range(30):
                                                        time.sleep(0.5)
                                                        if download_path.exists():
                                                            # Check it's not still downloading (.crdownload)
                                                            temp_file = Path(str(download_path) + '.crdownload')
                                                            if not temp_file.exists():
                                                                download_complete = True
                                                                break

                                                    if download_complete:
                                                        file_size = download_path.stat().st_size
                                                        print(f"    Download complete: {file_size:,} bytes")

                                                        if file_size > 100000:
                                                            # Rename to desired filename
                                                            if Path(output_filename).exists():
                                                                Path(output_filename).unlink()
                                                            download_path.rename(output_filename)
                                                            print(f"    Renamed to: {output_filename}")
                                                            driver.quit()
                                                            return True
                                                        else:
                                                            print(f"    File too small ({file_size} bytes), trying next PDF...")
                                                            download_path.unlink()
                                                    else:
                                                        # Maybe it opened in a new window instead of downloading
                                                        print(f"    Download not detected, checking for new window...")

                                                    time.sleep(2)  # Wait a bit before checking windows
                                                    # Get the current URL - if it's a PDF, the browser will navigate to it
                                                    current_url = driver.current_url
                                                    print(f"    Current URL after click: {current_url[:100]}...")

                                                    # If we navigated to a PDF, try to download it
                                                    if current_url.endswith('.pdf'):
                                                        # Try downloading with session cookies
                                                        if download_file(current_url, output_filename, driver=driver):
                                                            file_size = Path(output_filename).stat().st_size
                                                            if file_size > 100000:
                                                                driver.quit()
                                                                return True
                                                            else:
                                                                print(f"    File too small ({file_size} bytes), going back...")
                                                                driver.back()
                                                                time.sleep(2)
                                                        else:
                                                            print(f"    Download failed, going back...")
                                                            driver.back()
                                                            time.sleep(2)
                                                    else:
                                                        # If it opened in a new tab or frame, try to switch to it
                                                        print(f"    PDF may have opened in new window/tab")
                                                        # Try to find if we have multiple windows
                                                        if len(driver.window_handles) > 1:
                                                            driver.switch_to.window(driver.window_handles[-1])
                                                            pdf_url = driver.current_url
                                                            print(f"    Switched to new window: {pdf_url[:100]}...")

                                                            # PDF is opened in new tab - Chrome should download it automatically
                                                            try:
                                                                print(f"    Waiting for PDF to download...")

                                                                # Wait for the download to complete
                                                                # Chrome downloads PDFs with original filename
                                                                pdf_filename = Path(pdf_url).name  # e.g., "P21877287.pdf"
                                                                download_path = Path.cwd() / pdf_filename

                                                                # Wait up to 15 seconds for download to appear
                                                                download_complete = False
                                                                for i in range(30):  # 30 * 0.5 = 15 seconds
                                                                    time.sleep(0.5)
                                                                    # Check if file exists and is not a .crdownload (temp file)
                                                                    if download_path.exists():
                                                                        # Make sure it's not still downloading
                                                                        temp_file = Path(str(download_path) + '.crdownload')
                                                                        if not temp_file.exists():
                                                                            download_complete = True
                                                                            break

                                                                if download_complete:
                                                                    file_size = download_path.stat().st_size
                                                                    print(f"    Download complete: {file_size:,} bytes")

                                                                    if file_size > 100000:
                                                                        # Rename to our desired filename
                                                                        download_path.rename(output_filename)
                                                                        print(f"    Renamed to: {output_filename}")
                                                                        driver.quit()
                                                                        return True
                                                                    else:
                                                                        print(f"    File too small ({file_size} bytes), trying next PDF...")
                                                                        download_path.unlink()  # Delete the small file
                                                                else:
                                                                    print(f"    Download timed out or failed")

                                                            except Exception as e:
                                                                print(f"    Download error: {e}")

                                                            # Close the PDF window and switch back
                                                            driver.close()
                                                            driver.switch_to.window(driver.window_handles[0])
                                                            time.sleep(1)
                                                        else:
                                                            driver.back()
                                                            time.sleep(2)

                                                except Exception as e:
                                                    print(f"    Error accessing PDF: {e}")
                                                    # Try to go back to the Financial Disclosures page
                                                    try:
                                                        if len(driver.window_handles) > 1:
                                                            driver.close()
                                                            driver.switch_to.window(driver.window_handles[0])
                                                        else:
                                                            driver.back()
                                                        time.sleep(1)
                                                    except:
                                                        pass
                                                    continue

                                        print("  Could not download any relevant financial reports")
                                    else:
                                        print("  No relevant financial reports found after filtering")
                                else:
                                    print("  No PDF documents found on Financial Disclosures page")
                            else:
                                print("  Could not find Financial Disclosures tab")

                        except Exception as e:
                            print(f"  Error accessing Financial Disclosures: {e}")
                            import traceback
                            traceback.print_exc()

                    except Exception as e:
                        print(f"  Error clicking on result: {e}")
                        return False
                else:
                    # Multiple results found
                    print("  Multiple results found. Please refine your search.")
                    for idx, row in enumerate(actual_results[:5], 1):
                        try:
                            link = row.find_element(By.TAG_NAME, "a")
                            print(f"    {idx}. {link.text}")
                        except:
                            pass
                    return False

            except Exception as e:
                print(f"  Error counting results: {e}")
                return False

        except Exception as e:
            print(f"  Error finding search box: {e}")
            import traceback
            traceback.print_exc()
            return False

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
