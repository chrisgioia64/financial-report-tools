"""
FAC Selenium Downloader

Uses Selenium to search the Federal Audit Clearinghouse website
and download audit PDFs for entities.
"""

import argparse
import time
import os
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service


def sanitize_filename(name: str) -> str:
    """Convert entity name to safe filename."""
    import re
    safe_name = re.sub(r'[^\w\s-]', '', name)
    safe_name = re.sub(r'[-\s]+', '_', safe_name)
    return safe_name.strip('_')


def setup_driver(download_dir: str):
    """Setup Chrome driver with download preferences."""
    chrome_options = Options()

    # Set download preferences
    prefs = {
        "download.default_directory": download_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True,  # Download PDFs instead of viewing
        "safebrowsing.enabled": True
    }
    chrome_options.add_experimental_option("prefs", prefs)

    # Optional: Run in headless mode (comment out to see browser)
    # chrome_options.add_argument("--headless")

    # Create driver
    driver = webdriver.Chrome(options=chrome_options)
    return driver


def search_and_download_fac(entity_name: str, output_dir: str = "."):
    """
    Search FAC website for entity and download PDFs.

    Args:
        entity_name: Name of the entity to search for
        output_dir: Directory to save downloaded PDFs
    """

    # Create output directory if it doesn't exist
    output_path = Path(output_dir).resolve()
    output_path.mkdir(parents=True, exist_ok=True)

    print("="*70)
    print("FAC SELENIUM PDF DOWNLOADER")
    print("="*70)
    print(f"Entity: {entity_name}")
    print(f"Download Directory: {output_path}")
    print("="*70)

    # Setup driver
    print("\nInitializing Chrome driver...")
    driver = setup_driver(str(output_path))

    try:
        # Navigate to FAC dissemination search page
        fac_url = "https://app.fac.gov/dissemination/search/"
        print(f"\nNavigating to: {fac_url}")
        driver.get(fac_url)

        # Wait for page to load
        wait = WebDriverWait(driver, 20)

        # Find the search field "Name (Entity, Auditee, or Auditor)"
        print("\nLooking for search field...")

        # The field might have different identifiers, try multiple approaches
        search_field = None

        # Try by label text
        try:
            search_field = wait.until(
                EC.presence_of_element_located(
                    (By.XPATH, "//input[@type='text' and contains(@placeholder, 'Entity') or contains(@placeholder, 'Auditee') or contains(@placeholder, 'Auditor')]")
                )
            )
            print("  Found search field by placeholder")
        except:
            pass

        # Try by ID or name attribute
        if not search_field:
            try:
                search_field = driver.find_element(By.ID, "entity-name-search")
            except:
                pass

        # Try by name attribute
        if not search_field:
            try:
                search_field = driver.find_element(By.NAME, "entity_name")
            except:
                pass

        # Generic search for text inputs
        if not search_field:
            try:
                inputs = driver.find_elements(By.TAG_NAME, "input")
                for inp in inputs:
                    input_type = inp.get_attribute("type")
                    placeholder = inp.get_attribute("placeholder") or ""
                    aria_label = inp.get_attribute("aria-label") or ""

                    if input_type == "text" and ("entity" in placeholder.lower() or
                                                  "auditee" in placeholder.lower() or
                                                  "auditor" in placeholder.lower() or
                                                  "name" in aria_label.lower()):
                        search_field = inp
                        print(f"  Found search field with placeholder: {placeholder}")
                        break
            except:
                pass

        if not search_field:
            print("  ERROR: Could not find search field on the page")
            print("\nAvailable input fields:")
            inputs = driver.find_elements(By.TAG_NAME, "input")
            for inp in inputs[:10]:  # Show first 10 inputs
                print(f"    - Type: {inp.get_attribute('type')}, "
                      f"Name: {inp.get_attribute('name')}, "
                      f"ID: {inp.get_attribute('id')}, "
                      f"Placeholder: {inp.get_attribute('placeholder')}")
            driver.quit()
            return

        # Enter entity name in search field
        print(f"\nEntering search term: {entity_name}")

        # Wait for element to be interactable
        time.sleep(2)

        try:
            # Scroll to element to ensure it's visible
            driver.execute_script("arguments[0].scrollIntoView(true);", search_field)
            time.sleep(0.5)

            # Click on the field first to focus it
            search_field.click()
            time.sleep(0.5)

            search_field.clear()
            search_field.send_keys(entity_name)
            time.sleep(1)
        except Exception as e:
            print(f"  Error interacting with search field: {e}")
            print("  Trying JavaScript input method...")
            driver.execute_script(f"arguments[0].value = '{entity_name}';", search_field)
            time.sleep(1)

        # Find and click search button
        print("Looking for search button...")
        search_button = None

        try:
            # Try common button selectors
            search_button = driver.find_element(By.XPATH, "//button[contains(text(), 'Search') or contains(text(), 'search')]")
        except:
            try:
                search_button = driver.find_element(By.XPATH, "//input[@type='submit' and contains(@value, 'Search')]")
            except:
                try:
                    search_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
                except:
                    pass

        if search_button:
            print("  Clicking search button...")
            search_button.click()
        else:
            print("  No search button found, pressing Enter...")
            from selenium.webdriver.common.keys import Keys
            search_field.send_keys(Keys.RETURN)

        # Wait for results to load
        print("\nWaiting for search results...")
        time.sleep(3)

        # Look for results
        print("\nSearching for audit reports in results...")

        # Find all links that might lead to report pages
        links = driver.find_elements(By.TAG_NAME, "a")
        report_links = []

        for link in links:
            href = link.get_attribute("href") or ""
            text = link.text.strip()

            # Look for report links (they usually contain report ID or "view" text)
            if "/report/" in href or "view" in text.lower() or "download" in text.lower():
                report_links.append((text, href))

        if not report_links:
            print("  No report links found in search results")
            print("\nTrying to find result rows...")

            # Try to find result table or list
            try:
                results = driver.find_elements(By.XPATH, "//tr[contains(@class, 'result')]")
                if not results:
                    results = driver.find_elements(By.XPATH, "//div[contains(@class, 'result')]")

                print(f"  Found {len(results)} result items")

                if results:
                    # Click on first result
                    print("  Clicking on first result...")
                    results[0].click()
                    time.sleep(2)

                    # Now look for download links
                    pdf_links = driver.find_elements(By.XPATH, "//a[contains(@href, '.pdf') or contains(text(), 'PDF') or contains(text(), 'Download')]")

                    if pdf_links:
                        print(f"\n  Found {len(pdf_links)} PDF link(s)")
                        for idx, pdf_link in enumerate(pdf_links[:3], 1):  # Download first 3
                            print(f"\n  Downloading PDF {idx}...")
                            pdf_link.click()
                            time.sleep(3)  # Wait for download to start
            except Exception as e:
                print(f"  Error processing results: {e}")
        else:
            print(f"\nFound {len(report_links)} report link(s)")

            # Visit each report page and look for PDF downloads
            for idx, (text, href) in enumerate(report_links[:5], 1):  # Process first 5
                print(f"\n[{idx}] {text}")
                print(f"    URL: {href}")

                try:
                    driver.get(href)
                    time.sleep(2)

                    # Look for PDF download links
                    pdf_links = driver.find_elements(By.XPATH, "//a[contains(@href, '.pdf') or contains(text(), 'PDF') or contains(text(), 'Download Report')]")

                    if pdf_links:
                        print(f"    Found {len(pdf_links)} PDF link(s), downloading...")
                        for pdf_link in pdf_links[:1]:  # Download first PDF
                            pdf_link.click()
                            time.sleep(3)
                    else:
                        print("    No PDF download link found on this page")
                except Exception as e:
                    print(f"    Error: {e}")

        # Wait for downloads to complete
        print("\n\nWaiting for downloads to complete...")
        time.sleep(5)

        # Check downloaded files
        downloaded_files = list(output_path.glob("*.pdf"))
        if downloaded_files:
            print(f"\n{'='*70}")
            print(f"SUCCESS! Downloaded {len(downloaded_files)} PDF(s):")
            for pdf_file in downloaded_files:
                file_size = pdf_file.stat().st_size
                print(f"  - {pdf_file.name} ({file_size:,} bytes)")
            print(f"{'='*70}")
        else:
            print(f"\n{'='*70}")
            print("No PDFs were downloaded")
            print("This may be due to:")
            print("  - Search returned no results")
            print("  - PDFs require additional authentication")
            print("  - Website structure has changed")
            print(f"{'='*70}")

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()

    finally:
        print("\nClosing browser in 5 seconds...")
        time.sleep(5)
        driver.quit()


def main():
    parser = argparse.ArgumentParser(
        description='Download audit PDFs from FAC using Selenium'
    )
    parser.add_argument('entity_name',
                       help='Name of the entity (e.g., "Oakland Housing Authority")')
    parser.add_argument('-o', '--output-dir',
                       default='.',
                       help='Output directory for downloaded PDFs (default: current directory)')

    args = parser.parse_args()

    search_and_download_fac(args.entity_name, args.output_dir)


if __name__ == "__main__":
    main()
