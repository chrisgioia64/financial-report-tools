import requests
import json
import os
from urllib.parse import quote

# List of PHA codes and names from the PHA Contact Report, updated with closer FAC matches where possible
phas = [
    ("CA058", "BERKELEY HOUSING AUTHORITY"),
    ("CA116", "CDC OF NATIONAL CITY"),
    ("CA062", "HOUSING AUTHORITY OF THE CITY OF ALAMEDA"),
    ("CA041", "HOUSING AUTHORITY OF THE CITY OF BENICIA"),
    ("CA060", "CITY OF PITTSBURG HSG AUTH"),
    ("CA128", "CITY OF ROSEVILLE"),
    ("CA088", "CITY OF SANTA ROSA"),
    ("CA125", "CITY OF VACAVILLE"),
    ("CA043", "HOUSING AUTHORITY OF THE COUNTY OF BUTTE"),
    ("CA070", "COUNTY OF PLUMAS HOUSING AUTHORITY"),
    ("CA096", "COUNTY OF SHASTA HSG AUTH"),
    ("CA131", "COUNTY OF SOLANO HSG AUTH"),
    ("CA085", "COUNTY OF SONOMA"),
    ("CA061", "CRESCENT CITY HSG AUTH"),
    ("CA077", "Carlsbad Housing & Homeless Services"),
    ("CA104", "City of Anaheim Housing Authority"),
    ("CA071", "City of Compton Housing Authority"),
    ("CA065", "City of Fairfield"),
    ("CA068", "City of Long Beach Housing Authority"),
    ("CA132", "City of Oceanside Community Development Comm"),
    ("CA079", "City of Pasadena Housing Department"),
    ("CA005", "City of Sacramento Housing Authority"),
    ("CA015", "City of South San Francisco Housing Authority"),
    ("CA151", "County of El Dorado Housing Authority"),
    ("CA023", "HOUSING AUTHORITY OF THE COUNTY OF MERCED"),
    ("CA007", "County of Sacramento Housing Authority"),
    ("CA110", "Culver City Housing Authority"),
    ("CA052", "HOUSING AUTHORITY OF COUNTY OF MARIN"),
    ("CA073", "HOUSING AUTHORITY OF THE CITY OF NAPA"),
    ("CA106", "HOUSING AUTHORITY OF THE CITY OF REDDING"),
    ("CA056", "HOUSING AUTHORITY OF THE CITY OF SAN JOSE"),
    ("CA055", "HOUSING AUTHORITY OF THE CITY OF VALLEJO"),
    ("CA074", "HOUSING AUTHORITY OF THE CITY OF LIVERMORE"),
    ("CA126", "Hawthorne Housing"),
    ("CA024", "HOUSING AUTHORITY OF THE COUNTY OF SAN JOAQUIN"),
    ("CA006", "HOUSING AUTHORITY OF THE CITY OF FRESNO"),
    ("CA028", "HOUSING AUTHORITY OF FRESNO COUNTY"),
    ("CA001", "HOUSING AUTHORITY OF THE CITY AND COUNTY OF SAN FRANCISCO"),
    ("CA120", "Housing Authority of the City of Baldwin Park"),
    ("CA105", "Housing Authority of the City of Burbank"),
    ("CA039", "HOUSING AUTHORITY OF THE CITY OF CALEXICO"),
    ("CA155", "Housing Authority of the City of Encinitas"),
    ("CA025", "HOUSING AUTHORITY OF THE CITY OF EUREKA"),
    ("CA102", "Housing Authority of the City of Garden Grove"),
    ("CA114", "Housing Authority of the City of Glendale"),
    ("CA136", "Housing Authority of the City of Hawaiian Gardens"),
    ("CA082", "Housing Authority of the City of Inglewood"),
    ("CA139", "Housing Authority of the City of Lomita"),
    ("CA004", "HOUSING AUTHORITY OF THE CITY OF LOS ANGELES"),
    ("CA069", "Housing Authority of the City of Madera"),
    ("CA022", "HOUSING AUTHORITY OF THE CITY OF NEEDLES"),
    ("CA118", "Housing Authority of the City of Norwalk"),
    ("CA031", "HOUSING AUTHORITY OF THE CITY OF OXNARD"),
    ("CA050", "Housing Authority of the City of Paso Robles"),
    ("CA081", "Housing Authority of the City of Pleasanton"),
    ("CA123", "Housing Authority of the City of Pomona"),
    ("CA032", "HOUSING AUTHORITY OF THE CITY OF PORT HUENEME"),
    ("CA103", "Housing Authority of the City of Redondo Beach"),
    ("CA010", "Housing Authority of the City of Richmond"),
    ("CA017", "Housing Authority of the City of Riverbank"),
    ("CA035", "HOUSING AUTHORITY OF THE CITY OF SAN BUENAVENTURA"),
    ("CA064", "HOUSING AUTHORITY OF THE CITY OF SAN LUIS OBISPO"),
    ("CA093", "Housing Authority of the City of Santa Ana"),
    ("CA076", "HOUSING AUTHORITY CITY SANTA BARBARA"),
    ("CA111", "Housing Authority of the City of Santa Monica"),
    ("CA075", "Housing Authority of the City of Santa Paula"),
    ("CA119", "Housing Authority of the City of South Gate"),
    ("CA121", "Housing Authority of the City of Torrance"),
    ("CA011", "HOUSING AUTHORITY OF THE COUNTY OF CONTRA COSTA"),
    ("CA067", "HOUSING AUTHORITY OF THE COUNTY OF ALAMEDA"),
    ("CA086", "HOUSING AUTHORITY OF THE COUNTY OF HUMBOLDT"),
    ("CA008", "HOUSING AUTHORITY OF THE COUNTY OF KERN"),
    ("CA033", "Housing Authority of the County of Monterey"),
    ("CA027", "HOUSING AUTHORITY OF THE COUNTY OF RIVERSIDE"),
    ("CA019", "HOUSING AUTHORITY OF THE COUNTY OF SAN BERNARDINO"),
    ("CA108", "Housing Authority of the County of San Diego"),
    ("CA014", "HOUSING AUTHORITY OF THE COUNTY OF SAN MATEO"),
    ("CA021", "HOUSING AUTHORITY OF THE COUNTY OF SANTA BARBARA"),
    ("CA072", "HOUSING AUTHORITY OF THE COUNTY OF SANTA CRUZ"),
    ("CA092", "AREA HOUSING AUTHORITY OF THE COUNTY OF VENTURA"),
    ("CA044", "Housing Authority of the County of Yolo"),
    ("CA143", "IMPERIAL VALLEY HOUSING AUTHORITY"),
    ("CA053", "Housing Authority of the County of Kings"),
    ("CA144", "Lake County Housing Commission"),
    ("CA002", "Los Angeles County Development Authority"),
    ("CA084", "MENDOCINO COUNTY"),
    ("CA003", "HOUSING AUTHORITY OF THE CITY OF OAKLAND, CALIFORNIA"),
    ("CA094", "Orange County Housing Authority"),
    ("CA149", "PLACER COUNTY HOUSING AUTHORITY"),
    ("CA117", "Pico Rivera Housing Assistance Agency"),
    ("CA048", "REGIONAL HOUSING AUTHORITY"),
    ("CA066", "SUISUN CITY HOUSING AUTHORITY"),
    ("CA063", "San Diego Housing Commission"),
    ("CA059", "SANTA CLARA COUNTY HOUSING AUTHORITY"),
    ("CA026", "STANISLAUS REGIONAL HOUSING AUTHORITY"),
    ("CA030", "Tulare County Housing Authority"),
]

# Hardcoded API key (Note: Hardcoding API keys is not recommended for security reasons; consider using environment variables in production)
API_KEY = "F6pOX4Hz6T4b7qMbMSHA5onhsVmfKRTE4IG4wRzh"
if not API_KEY:
    print("API key is required.")
    exit(1)

BASE_URL = "https://api.fac.gov"
headers = {"X-Api-Key": API_KEY}

# Create a directory for downloads
os.makedirs("ca_pha_audits", exist_ok=True)

# Fiscal year to search for (changed to 2024 for available audits)
AUDIT_YEAR = "2024"

for code, name in phas:
    print(f"Searching for {name} ({code})...")
    
    # Escape name for query (use ilike for partial match)
    escaped_name = name.replace("'", "''")  # Escape single quotes for SQL
    query_param = f"ilike.*{escaped_name}*"
    
    url = f"{BASE_URL}/general?auditee_state=eq.CA&auditee_name={query_param}&audit_year=eq.{AUDIT_YEAR}&limit=1&select=report_id,auditee_name,audit_year"
    
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        data = response.json()
        if data:
            report = data[0]
            report_id = report['report_id']
            print(f"Found report ID: {report_id} for {report['auditee_name']}")
            
            # Construct the PDF URL using the report_id
            pdf_url = f"https://app.fac.gov/dissemination/report/pdf/{report_id}"
            pdf_response = requests.get(pdf_url)
            if pdf_response.status_code == 200:
                filename = f"{code}_{name.replace(' ', '_').replace('/', '_').replace('&', 'and').replace(',', '')}_single_audit.pdf"
                filepath = os.path.join("ca_pha_audits", filename)
                with open(filepath, 'wb') as f:
                    f.write(pdf_response.content)
                print(f"Downloaded: {filepath}")
            else:
                print(f"Failed to download PDF for {report_id} (status: {pdf_response.status_code})")
                # Optional: Print response for debugging
                print(pdf_response.text[:500])
        else:
            print(f"No audit found for {name} in {AUDIT_YEAR}.")
    else:
        print(f"API error for {name}: {response.status_code} - {response.text}")

print("Download complete. Check the 'ca_pha_audits' directory.")