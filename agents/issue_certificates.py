import gspread
from google.oauth2.service_account import Credentials
from datetime import date

SHEET_ID        = "1z0-TFgYUmftZglGwGlaDbkgEM3k8VfaIOm4Rl8RmFow"
CREDENTIALS_FILE = "/Users/veenakamat/ldp-agent/google_credentials.json"
TODAY           = date.today().strftime("%d-%b-%Y")

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

def connect():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
    return gspread.authorize(creds)

def issue_certificates():
    print("Connecting to tracker...")
    gc = connect()
    ws = gc.open_by_key(SHEET_ID).worksheet("LDP Tracker")

    all_values = ws.get_all_values()
    headers    = [clean_header(h) for h in all_values[1]]
    col_idx    = {h: i for i, h in enumerate(headers)}
    data_rows  = all_values[2:]

    name_col      = col_idx.get("Employee Name", -1)
    train_col     = col_idx.get("Training Complete", -1)
    cert_elig_col = col_idx.get("Certificate Eligible", -1)
    cert_date_col = col_idx.get("Certificate Issued Date", -1)

    if cert_date_col < 0:
        print("ERROR: 'Certificate Issued Date' column not found.")
        print("Available columns:", list(col_idx.keys()))
        return

    updates     = []
    issued_names = []

    for row_idx, row in enumerate(data_rows):
        def get(col): return row[col].strip() if col >= 0 and len(row) > col else ""

        if get(train_col) == "Yes" and get(cert_elig_col) == "Yes" and not get(cert_date_col):
            sheet_row = row_idx + 3
            updates.append({
                "range":  f"{col_letter(cert_date_col)}{sheet_row}",
                "values": [[TODAY]]
            })
            issued_names.append(get(name_col))

    if not updates:
        print("No eligible employees without a certificate date — nothing to update.")
        return

    print(f"Issuing certificates for {len(updates)} employees...")
    ws.batch_update(updates)

    print("\n" + "="*60)
    print(f"CERTIFICATES ISSUED — {TODAY}")
    print("="*60)
    for n in issued_names:
        print(f"  ✅ {n}")
    print(f"\nTotal: {len(issued_names)}")

issue_certificates()
