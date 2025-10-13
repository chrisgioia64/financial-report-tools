import requests
import json

BASE_URL = "https://api.fac.gov"
API_KEY = "aNGNO2WsZlfQEmkcXIZlLfAkDCL8jb1yGQ2qJcjj"

def fetch_audit_by_id(report_id):
    url = f"{BASE_URL}/general?report_id=eq.{report_id}"
    headers = {"X-Api-Key": API_KEY}
    
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        audit = response.json()
        
        if audit:
            print(f"\n Audit Report Found for Report ID: {report_id}\n")
            print(json.dumps(audit, indent=4))  # Pretty-print JSON
        else:
            print(f"\n No audit report found for Report ID: {report_id}")
    else:
        print(f"\n Error {response.status_code}: {response.text}")

report_id = input("Enter the Report ID: ").strip()
fetch_audit_by_id(report_id)