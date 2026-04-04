import anthropic
from dotenv import load_dotenv
import os
import urllib.request
import csv
import io
import gspread
import time
from google.oauth2.service_account import Credentials
from datetime import date

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

SHEET_ID = "1z0-TFgYUmftZglGwGlaDbkgEM3k8VfaIOm4Rl8RmFow"
NOMINATIONS_SHEET_ID = "1Bc-eNUYt15SiDBUccajt0tlgeuCXOKkihb7Zb3UfKiM"
CREDENTIALS_FILE = "/Users/veenakamat/ldp-agent/google_credentials.json"
BATCH_NAME = "Batch-04-2026"
BATCH_DATE = "28-29 April 2026"
WORKSHOP_LOCATION = "Main Training Centre, Dubai"
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

# ── TOOL 1: Read LDP Tracker ──────────────────────────────
def read_ldp_tracker():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet=LDP%20Tracker"
    response = urllib.request.urlopen(url)
    content = response.read().decode("utf-8")
    reader = csv.reader(io.StringIO(content))
    all_rows = list(reader)
    headers = [clean_header(h) for h in all_rows[0]]
    data = []
    for row in all_rows[1:]:
        if any(cell.strip() for cell in row):
            data.append(dict(zip(headers, row)))
    tbd = [r for r in data if r.get("Batch","").strip() == "TBD"]
    by_hrbp = {}
    for emp in tbd:
        hrbp = emp.get("HRBP Name","").strip()
        if hrbp not in by_hrbp:
            by_hrbp[hrbp] = []
        by_hrbp[hrbp].append({
            "name": emp.get("Employee Name",""),
            "function": emp.get("Function",""),
            "sub_function": emp.get("Sub-Function",""),
            "promo_date": emp.get("Promo Date (to Grade I)",""),
        })
    return {
        "total_tbd": len(tbd),
        "hrbps": len(by_hrbp),
        "by_hrbp": by_hrbp
    }

# ── TOOL 2: Read nominations ──────────────────────────────
def read_form_responses():
    url = f"https://docs.google.com/spreadsheets/d/{NOMINATIONS_SHEET_ID}/gviz/tq?tqx=out:csv&gid=1000019961"
    response = urllib.request.urlopen(url)
    content = response.read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))
    responses = []
    for row in reader:
        hrbp = ""
        nominees = []
        comments = ""
        for key, value in row.items():
            if "name" in key.lower():
                hrbp = value.strip()
            if "nominate" in key.lower() or "eligible" in key.lower():
                nominees = [n.strip() for n in value.split(",") if n.strip()]
            if "comment" in key.lower() or "special" in key.lower():
                comments = value.strip()
        if hrbp:
            responses.append({
                "hrbp": hrbp,
                "nominees": nominees,
                "comments": comments
            })
    return responses

# ── TOOL 3: Update tracker ────────────────────────────────
def update_tracker(nominations_data):
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_file(
        CREDENTIALS_FILE, scopes=scopes
    )
    gc = gspread.authorize(creds)
    workbook = gc.open_by_key(SHEET_ID)
    ws = workbook.worksheet("LDP Tracker")

    all_values = ws.get_all_values()
    headers = [clean_header(h) for h in all_values[1]]
    col_idx = {h: i for i, h in enumerate(headers)}
    data_rows = all_values[2:]

    name_col     = col_idx.get("Employee Name", -1)
    batch_col    = col_idx.get("Batch", -1)
    status_col   = col_idx.get("Nomination Status", -1)
    nom_by_col   = col_idx.get("Nominated By", -1)
    nom_date_col = col_idx.get("Nomination Date", -1)

    nominees_map = {}
    for nom in nominations_data:
        for name in nom["nominees"]:
            nominees_map[name] = {
                "hrbp": nom["hrbp"],
                "comments": nom["comments"]
            }

    batch_updates = []
    updated = []

    for row_idx, row in enumerate(data_rows):
        emp_name = row[name_col].strip() if name_col >= 0 and len(row) > name_col else ""
        if emp_name in nominees_map:
            sheet_row = row_idx + 3
            nom_data = nominees_map[emp_name]
            batch_updates.append({
                "range": f"{col_letter(batch_col)}{sheet_row}:{col_letter(nom_date_col)}{sheet_row}",
                "values": [[BATCH_NAME, "Nominated", nom_data["hrbp"], TODAY]]
            })
            updated.append(emp_name)

    if batch_updates:
        ws.batch_update(batch_updates)

    return {"updated": len(updated), "names": updated}

# ── TOOL 4: Draft email with Claude ──────────────────────
def draft_email(email_type, context):
    if email_type == "nomination":
        prompt = f"""Draft a professional nomination request email to HRBP.
HRBP: {context['hrbp_name']}
Batch: {BATCH_DATE}
Deadline: 7 April 2026
Employees: {context['employees']}
Sign off as LDP Programme Team. Ready to send."""

    elif email_type == "confirmation":
        prompt = f"""Draft a confirmation email to HRBP that we are going
ahead with their nominations.
HRBP: {context['hrbp_name']}
Nominees: {context['nominees']}
Batch: {BATCH_DATE}
Sign off as LDP Programme Team. Ready to send."""

    elif email_type == "joining":
        prompt = f"""Draft a warm joining email to a participant selected for LDP.
Name: {context['participant']}
Batch: {BATCH_DATE}
Location: {WORKSHOP_LOCATION}
Time: 9AM-5PM both days
Ask them to reply to confirm attendance by 14 April 2026.
Sign off as LDP Programme Team. Ready to send."""

    elif email_type == "special_case":
        prompt = f"""Draft a brief note to HR about a special case flagged
by an HRBP.
HRBP: {context['hrbp']}
Comment: {context['comment']}
Suggest appropriate action.
Sign off as LDP Programme Team."""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text
# ── MAIN AGENT 1 RUNNER ───────────────────────────────────
def run_agent1():
    print("\n" + "="*60)
    print("AGENT 1 — NOMINATIONS WORKFLOW")
    print(f"Batch: {BATCH_NAME} | {BATCH_DATE}")
    print(f"Running: {TODAY}")
    print("="*60)

    # Step 1: Scope
    print("\n[Step 1] Reading tracker...")
    tracker_data = read_ldp_tracker()
    print(f"Found {tracker_data['total_tbd']} TBD employees across {tracker_data['hrbps']} HRBPs")

    # Step 2: Draft nomination emails
    print("\n[Step 2] Drafting nomination emails...")
    for hrbp_name, employees in list(tracker_data["by_hrbp"].items())[:3]:
        emp_list = ", ".join([e["name"] for e in employees])
        print(f"\n--- EMAIL TO: {hrbp_name} ({len(employees)} employees) ---")
        email = draft_email("nomination", {
            "hrbp_name": hrbp_name,
            "employees": emp_list
        })
        print(email[:300] + "...")
    print(f"\n[All {tracker_data['hrbps']} nomination emails drafted]")

    # Step 3: Read form responses
    print("\n[Step 3] Reading nomination responses...")
    responses = read_form_responses()
    print(f"Found {len(responses)} HRBP responses")
    total_nominees = sum(len(r["nominees"]) for r in responses)
    print(f"Total nominees: {total_nominees}")

    # Step 4: Update tracker
    print("\n[Step 4] Updating LDP Tracker...")
    result = update_tracker(responses)
    print(f"Updated {result['updated']} employees in tracker")

    # Step 5: Special cases
    print("\n[Step 5] Checking special cases...")
    special_cases = [r for r in responses if r["comments"].strip()]
    if special_cases:
        print(f"Found {len(special_cases)} HRBPs with comments:")
        for case in special_cases:
            print(f"  {case['hrbp']}: {case['comments'][:80]}...")
    else:
        print("No special cases flagged")

    # Step 6: Draft confirmation emails
    print("\n[Step 6] Drafting confirmation emails...")
    for resp in responses[:2]:
        nominees_str = ", ".join(resp["nominees"])
        print(f"\n--- CONFIRMATION TO: {resp['hrbp']} ---")
        email = draft_email("confirmation", {
            "hrbp_name": resp["hrbp"],
            "nominees": nominees_str
        })
        print(email[:300] + "...")

    # Step 7: Draft joining emails
    print("\n[Step 7] Drafting joining emails...")
    all_nominees = []
    for resp in responses:
        all_nominees.extend(resp["nominees"])

    for participant in all_nominees[:2]:
        print(f"\n--- JOINING EMAIL TO: {participant} ---")
        email = draft_email("joining", {"participant": participant})
        print(email[:300] + "...")

    print("\n" + "="*60)
    print("AGENT 1 COMPLETE")
    print(f"Nominated: {result['updated']} employees")
    print(f"Special cases: {len(special_cases)}")
    print(f"Confirmation emails: {len(responses)} drafted")
    print(f"Joining emails: {len(all_nominees)} drafted")
    print("="*60)

run_agent1()
