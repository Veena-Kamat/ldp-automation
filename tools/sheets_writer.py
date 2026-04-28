import gspread
from google.oauth2.service_account import Credentials
import urllib.request
import csv
import io
import time
from datetime import date

SHEET_ID = "1z0-TFgYUmftZglGwGlaDbkgEM3k8VfaIOm4Rl8RmFow"
NOMINATIONS_SHEET_ID = "1Bc-eNUYt15SiDBUccajt0tlgeuCXOKkihb7Zb3UfKiM"
CREDENTIALS_FILE = "/Users/veenakamat/ldp-agent/google_credentials.json"
BATCH_NAME = "Batch-04-2026"
TODAY = date.today().strftime("%d-%b-%Y")

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

def connect_to_sheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_file(
        CREDENTIALS_FILE, scopes=scopes
    )
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID)

def read_nominations():
    url = f"https://docs.google.com/spreadsheets/d/{NOMINATIONS_SHEET_ID}/gviz/tq?tqx=out:csv&gid=1000019961"
    response = urllib.request.urlopen(url)
    content = response.read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))
    return [row for row in reader]

def get_all_nominees(nominations):
    nominees = {}
    for nom in nominations:
        hrbp = ""
        names = []
        comments = ""
        for key, value in nom.items():
            if "name" in key.lower():
                hrbp = value.strip()
            if "nominate" in key.lower() or "eligible" in key.lower():
                names = [n.strip() for n in value.split(",") if n.strip()]
            if "comment" in key.lower() or "special" in key.lower():
                comments = value.strip()
        for name in names:
            nominees[name] = {"hrbp": hrbp, "comments": comments}
    return nominees

def update_tracker():
    print("Connecting to Google Sheet...")
    workbook = connect_to_sheet()
    ws = workbook.worksheet("LDP Tracker")

    print("Reading sheet data...")
    all_values = ws.get_all_values()
    headers = [clean_header(h) for h in all_values[1]]
    col_idx = {h: i for i, h in enumerate(headers)}
    data_rows = all_values[2:]

    print("Reading nominations...")
    nominations = read_nominations()
    nominees = get_all_nominees(nominations)
    print(f"Found {len(nominees)} nominees")

    name_col     = col_idx.get("Employee Name", -1)
    batch_col    = col_idx.get("Batch", -1)
    status_col   = col_idx.get("Nomination Status", -1)
    nom_by_col   = col_idx.get("Nominated By", -1)
    nom_date_col = col_idx.get("Nomination Date", -1)

    updated_names = []
    deferred_names = []
    batch_updates = []

    for row_idx, row in enumerate(data_rows):
        emp_name = row[name_col].strip() if name_col >= 0 and len(row) > name_col else ""
        if emp_name in nominees:
            nom_data = nominees[emp_name]
            sheet_row = row_idx + 3
            comments = nom_data["comments"].lower()
            emp_name_lower = emp_name.lower()
            name_in_comments = emp_name_lower in comments or \
                emp_name.split()[0].lower() in comments or \
                emp_name.split()[-1].lower() in comments
            is_deferred = name_in_comments and any(word in comments for word in
                ["defer","deferred","next batch","maternity",
                "travelling","travel","leave","project deadline"])

            batch_val  = "Deferred-Batch-05-2026" if is_deferred else BATCH_NAME
            status_val = "Deferred" if is_deferred else "Nominated"

            batch_updates.append({
                "range": f"{col_letter(batch_col)}{sheet_row}:{col_letter(nom_date_col)}{sheet_row}",
                "values": [[batch_val, status_val, nom_data["hrbp"], TODAY]]
            })

            if is_deferred:
                deferred_names.append(emp_name)
            else:
                updated_names.append(emp_name)

    # Second pass: set TBD for everyone not in Batch-01/02/03 and not a nominee
    tbd_names = []
    tbd_updates = []
    for row_idx, row in enumerate(data_rows):
        emp_name = row[name_col].strip() if name_col >= 0 and len(row) > name_col else ""
        if not emp_name or emp_name in nominees:
            continue
        current_batch = row[batch_col].strip() if batch_col >= 0 and len(row) > batch_col else ""
        if current_batch.startswith("Batch-01") or \
           current_batch.startswith("Batch-02") or \
           current_batch.startswith("Batch-03"):
            continue
        sheet_row = row_idx + 3
        tbd_updates.append({
            "range": f"{col_letter(batch_col)}{sheet_row}",
            "values": [["TBD"]]
        })
        tbd_names.append(emp_name)

    all_updates = batch_updates + tbd_updates
    print(f"\nApplying {len(all_updates)} updates in bulk ({len(batch_updates)} nominations, {len(tbd_updates)} TBD)...")
    ws.batch_update(all_updates)
    print("Done!")

    print("\n" + "="*60)
    print("TRACKER UPDATE COMPLETE")
    print("="*60)
    print(f"\nNominated for {BATCH_NAME}: {len(updated_names)}")
    for n in updated_names:
        print(f"  ✅ {n}")
    print(f"\nDeferred to Batch-05-2026: {len(deferred_names)}")
    for n in deferred_names:
        print(f"  ⏭  {n}")
    print(f"\nSet to TBD: {len(tbd_names)}")
    for n in tbd_names:
        print(f"  —  {n}")

update_tracker()
