"""
Find all tracker rows where VL Status = 'Completed' and
Certificate Issued Date is blank, then write '28 April 2026'.
Run locally: python tools/issue_certificates.py
"""

import gspread
from google.oauth2.service_account import Credentials

SHEET_ID        = "1z0-TFgYUmftZglGwGlaDbkgEM3k8VfaIOm4Rl8RmFow"
CREDENTIALS_FILE = "/Users/veenakamat/ldp-agent/google_credentials.json"
CERT_DATE       = "28 April 2026"

SECTION_LABELS = [
    "IDENTITY & SCOPE ",
    "BATCH & NOMINATION ",
    "WORKSHOP ATTENDANCE ",
    "VIRTUAL LEARNING ",
    "COMPLETION & CERTIFICATION ",
    "FEEDBACK ",
]

def clean_header(h):
    for label in SECTION_LABELS:
        if h.startswith(label):
            return h.replace(label, "")
    return h

def col_letter(n):
    result = ""
    while n >= 0:
        result = chr(n % 26 + 65) + result
        n = n // 26 - 1
    return result

def main():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
    client = gspread.authorize(creds)
    ws = client.open_by_key(SHEET_ID).worksheet("LDP Tracker")

    print("Reading tracker...")
    all_values = ws.get_all_values()
    raw_headers = all_values[1]  # row 2 is headers
    headers = [clean_header(h) for h in raw_headers]
    data_rows = all_values[2:]   # data starts row 3

    name_col = headers.index("Employee Name") if "Employee Name" in headers else -1
    vl_col   = headers.index("VL Status")     if "VL Status"     in headers else -1
    cert_col = headers.index("Certificate Issued Date") if "Certificate Issued Date" in headers else -1

    if vl_col == -1 or cert_col == -1:
        print("ERROR: Could not find required columns.")
        print("Available headers:", headers)
        return

    updates = []
    matched = []

    for row_idx, row in enumerate(data_rows):
        vl_status  = row[vl_col].strip()  if len(row) > vl_col  else ""
        cert_date  = row[cert_col].strip() if len(row) > cert_col else ""
        emp_name   = row[name_col].strip() if len(row) > name_col else ""

        if vl_status == "Completed" and not cert_date:
            sheet_row = row_idx + 3  # 1-indexed, offset by 2 header rows
            cell = f"{col_letter(cert_col)}{sheet_row}"
            updates.append({"range": cell, "values": [[CERT_DATE]]})
            matched.append(emp_name)

    if not updates:
        print("No rows to update — all completed employees already have a cert date.")
        return

    print(f"\nFound {len(updates)} employee(s) to update:")
    for name in matched:
        print(f"  {name}")

    print(f"\nWriting '{CERT_DATE}' to Certificate Issued Date...")
    ws.batch_update(updates)
    print("Done.")

if __name__ == "__main__":
    main()
