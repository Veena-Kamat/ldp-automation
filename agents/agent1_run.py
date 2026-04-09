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

SHEET_ID         = "1z0-TFgYUmftZglGwGlaDbkgEM3k8VfaIOm4Rl8RmFow"
NOMINATIONS_SHEET_ID = "1Bc-eNUYt15SiDBUccajt0tlgeuCXOKkihb7Zb3UfKiM"
CREDENTIALS_FILE = "/Users/veenakamat/ldp-agent/google_credentials.json"
BATCH_NAME       = "Batch-04-2026"
NEXT_BATCH_NAME  = "Batch-05-2026"
BATCH_DATE       = "28-29 April 2026"
NOMINATION_DEADLINE = "7 April 2026"
WORKSHOP_LOCATION   = "Main Training Centre, Dubai"
TODAY = date.today().strftime("%d-%b-%Y")

SECTION_LABELS = [
    "IDENTITY & SCOPE ",
    "BATCH & NOMINATION ",
    "WORKSHOP ATTENDANCE ",
    "VIRTUAL LEARNING ",
    "COMPLETION & CERTIFICATION ",
    "FEEDBACK ",
]

ALL_HRBPS = [
    "Aisha Walker", "Aparna Johnson", "Ishaan Farouk",
    "Mariam Lee", "Meghna Iqbal", "Nawaf Bhat",
    "Pranav Young", "Ryan Venkataraman", "Saif Sivasubramanian",
    "Salman Varma", "Thomas Subramaniam", "Yusuf Jackson",
    "Daniel Smith", "Maria Verma", "Hamdan Malik",
    "Thomas Varma", "Stanley Al-Dhaheri", "Anita Al-Farsi",
    "Varun Al-Farsi"
]

DEFER_KEYWORDS = [
    "defer", "deferred", "next batch", "maternity",
    "travelling", "travel", "leave", "project deadline",
    "long leave", "medical", "secondment"
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

# ── TOOL 1: Read LDP Tracker (TBD employees) ─────────────────
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

    tbd = [r for r in data if r.get("Batch", "").strip() == "TBD"]
    by_hrbp = {}
    for emp in tbd:
        hrbp = emp.get("HRBP Name", "").strip()
        if hrbp not in by_hrbp:
            by_hrbp[hrbp] = []
        by_hrbp[hrbp].append({
            "name":         emp.get("Employee Name", ""),
            "function":     emp.get("Function", ""),
            "sub_function": emp.get("Sub-Function", ""),
            "promo_date":   emp.get("Promo Date (to Grade I)", ""),
        })
    return {
        "total_tbd": len(tbd),
        "hrbps":     len(by_hrbp),
        "by_hrbp":   by_hrbp,
        "all":       data,
    }

# ── TOOL 2: Find previous batch non-attendees ─────────────────
def find_previous_non_attendees(all_employees):
    """Return employees from prior batches who were absent both workshop days."""
    prior_batches = ["Batch-01-2026", "Batch-02-2026", "Batch-03-2026"]
    non_attendees = []
    for emp in all_employees:
        batch = emp.get("Batch", "").strip()
        if batch not in prior_batches:
            continue
        d1 = emp.get("Day 1 Attendance", "").strip()
        d2 = emp.get("Day 2 Attendance", "").strip()
        # Absent both days OR no attendance recorded yet
        if d1 == "Absent" and d2 == "Absent":
            non_attendees.append({
                "name":     emp.get("Employee Name", "").strip(),
                "hrbp":     emp.get("HRBP Name", "").strip(),
                "function": emp.get("Function", "").strip(),
                "batch":    batch,
                "emp_id":   emp.get("Emp ID", "").strip(),
            })
    return non_attendees

# ── TOOL 3: Read nomination form responses ────────────────────
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
                "hrbp":      hrbp,
                "nominees":  nominees,
                "comments":  comments,
            })
    return responses

# ── TOOL 4: Check Day 7 — who hasn't responded? ───────────────
def check_day7_nonresponders(form_responses):
    """Compare form responses against full HRBP list."""
    responded = {r["hrbp"] for r in form_responses}
    not_responded = [h for h in ALL_HRBPS if h not in responded]
    return not_responded

# ── TOOL 5: Update tracker (nominate + defer flagged) ─────────
def update_tracker(nominations_data):
    gc = connect()
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
        comments_lower = nom["comments"].lower()
        is_defer_comment = any(kw in comments_lower for kw in DEFER_KEYWORDS)
        for name in nom["nominees"]:
            # Check if this specific person is mentioned in deferral comment
            name_mentioned = (
                name.lower() in comments_lower or
                name.split()[0].lower() in comments_lower or
                name.split()[-1].lower() in comments_lower
            )
            is_deferred = is_defer_comment and name_mentioned
            nominees_map[name] = {
                "hrbp":       nom["hrbp"],
                "comments":   nom["comments"],
                "is_deferred": is_deferred,
            }

    batch_updates = []
    updated = []
    deferred = []

    for row_idx, row in enumerate(data_rows):
        emp_name = row[name_col].strip() if name_col >= 0 and len(row) > name_col else ""
        if emp_name not in nominees_map:
            continue

        nom_data  = nominees_map[emp_name]
        sheet_row = row_idx + 3

        if nom_data["is_deferred"]:
            batch_val  = NEXT_BATCH_NAME
            status_val = "Deferred"
            deferred.append(emp_name)
        else:
            batch_val  = BATCH_NAME
            status_val = "Nominated"
            updated.append(emp_name)

        batch_updates.append({
            "range": f"{col_letter(batch_col)}{sheet_row}:{col_letter(nom_date_col)}{sheet_row}",
            "values": [[batch_val, status_val, nom_data["hrbp"], TODAY]]
        })

    if batch_updates:
        ws.batch_update(batch_updates)

    return {"updated": len(updated), "names": updated, "deferred": deferred}

# ── TOOL 6: Draft emails via Claude ──────────────────────────
def draft_email(email_type, context):
    if email_type == "nomination":
        prompt = f"""Draft a professional nomination request email to an HRBP for LDP.
HRBP: {context['hrbp_name']}
Batch dates: {BATCH_DATE}
Nomination deadline: {NOMINATION_DEADLINE}
Eligible employees: {context['employees']}
Sign off as LDP Programme Team. Write as a complete ready-to-send email with subject line."""

    elif email_type == "nomination_with_nonattendees":
        prompt = f"""Draft a nomination request email to an HRBP for LDP.
HRBP: {context['hrbp_name']}
Batch dates: {BATCH_DATE}
Nomination deadline: {NOMINATION_DEADLINE}
Eligible TBD employees: {context['employees']}

Also mention that the following employees from a previous batch were absent and should be considered for re-scheduling:
Previous non-attendees under this HRBP: {context.get('non_attendees', 'None')}

Sign off as LDP Programme Team. Write as a complete ready-to-send email with subject line."""

    elif email_type == "confirmation":
        prompt = f"""Draft a nomination confirmation email to an HRBP.
HRBP: {context['hrbp_name']}
Nominees confirmed: {context['nominees']}
Batch dates: {BATCH_DATE}
Sign off as LDP Programme Team. Write as a complete ready-to-send email with subject line."""

    elif email_type == "joining":
        prompt = f"""Draft a warm joining email to an LDP participant.
Name: {context['participant']}
Batch dates: {BATCH_DATE}
Location: {WORKSHOP_LOCATION}
Time: 9AM-5PM both days
Ask them to reply to confirm attendance by 14 April 2026.
Sign off as LDP Programme Team. Write as a complete ready-to-send email with subject line."""

    elif email_type == "day7_reminder":
        prompt = f"""Draft a polite but firm reminder email to an HRBP who has not responded to the LDP nomination request.
HRBP: {context['hrbp_name']}
Nomination deadline: {NOMINATION_DEADLINE}
Batch dates: {BATCH_DATE}
They were asked to nominate eligible employees from their team for LDP.
Keep it brief — 3-4 sentences. Remind them the deadline is approaching.
Sign off as LDP Programme Team. Write as a complete ready-to-send email with subject line."""

    elif email_type == "special_case":
        prompt = f"""Draft a brief internal note to HR about a special case flagged by an HRBP.
HRBP: {context['hrbp']}
Comment: {context['comment']}
Suggest appropriate action (defer to next batch, check with manager, etc).
Sign off as LDP Programme Team."""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text


# ── MAIN AGENT 1 RUNNER ───────────────────────────────────────
def run_agent1():
    print("\n" + "="*60)
    print("AGENT 1 — NOMINATIONS WORKFLOW")
    print(f"Batch: {BATCH_NAME} | {BATCH_DATE}")
    print(f"Running: {TODAY}")
    print("="*60)

    # Step 1: Read tracker — TBD employees
    print("\n[Step 1] Reading LDP Tracker...")
    tracker_data = read_ldp_tracker()
    print(f"Found {tracker_data['total_tbd']} TBD employees across {tracker_data['hrbps']} HRBPs")

    # Step 2: Find previous non-attendees
    print("\n[Step 2] Finding previous batch non-attendees...")
    prev_non_attendees = find_previous_non_attendees(tracker_data["all"])
    print(f"Found {len(prev_non_attendees)} employees who were absent from a prior workshop")
    # Group by HRBP for inclusion in nomination emails
    non_att_by_hrbp = {}
    for emp in prev_non_attendees:
        hrbp = emp["hrbp"]
        if hrbp not in non_att_by_hrbp:
            non_att_by_hrbp[hrbp] = []
        non_att_by_hrbp[hrbp].append(emp["name"])
        print(f"  {emp['name']} (was {emp['batch']}, HRBP: {hrbp})")

    # Step 3: Draft nomination emails (with non-attendees included)
    print("\n[Step 3] Drafting nomination emails...")
    for hrbp_name, employees in list(tracker_data["by_hrbp"].items())[:3]:
        emp_list = ", ".join([e["name"] for e in employees])
        non_att_list = ", ".join(non_att_by_hrbp.get(hrbp_name, []))
        email_type = "nomination_with_nonattendees" if non_att_list else "nomination"
        print(f"\n--- EMAIL TO: {hrbp_name} ({len(employees)} TBD + {len(non_att_by_hrbp.get(hrbp_name,[]))} re-schedule) ---")
        email = draft_email(email_type, {
            "hrbp_name":     hrbp_name,
            "employees":     emp_list,
            "non_attendees": non_att_list,
        })
        print(email[:400] + "...")
    print(f"\n[All {tracker_data['hrbps']} nomination emails drafted]")

    # Step 4: Read form responses
    print("\n[Step 4] Reading nomination form responses...")
    responses = read_form_responses()
    print(f"Found {len(responses)} HRBP responses")
    total_nominees = sum(len(r["nominees"]) for r in responses)
    print(f"Total nominees: {total_nominees}")

    # Step 5: Day 7 check — non-responders
    print("\n[Step 5] Day 7 check — identifying non-responders...")
    non_responders = check_day7_nonresponders(responses)
    print(f"  {len(responses)}/{len(ALL_HRBPS)} HRBPs responded")
    if non_responders:
        print(f"  {len(non_responders)} HRBPs have NOT responded:")
        for h in non_responders:
            print(f"    - {h}")
        print("\n  Drafting reminder emails to non-responders...")
        for hrbp_name in non_responders[:3]:
            print(f"\n--- REMINDER TO: {hrbp_name} ---")
            email = draft_email("day7_reminder", {"hrbp_name": hrbp_name})
            print(email[:300] + "...")
        print(f"[{len(non_responders)} reminder emails drafted]")
    else:
        print("  All HRBPs have responded!")

    # Step 6: Update tracker (nominate confirmed + defer flagged)
    print("\n[Step 6] Updating LDP Tracker...")
    result = update_tracker(responses)
    print(f"  Nominated for {BATCH_NAME}: {result['updated']} employees")
    if result["deferred"]:
        print(f"  Deferred to {NEXT_BATCH_NAME}: {len(result['deferred'])} employees")
        for name in result["deferred"]:
            print(f"    - {name}")

    # Step 7: Special cases
    print("\n[Step 7] Checking special cases...")
    special_cases = [r for r in responses if r["comments"].strip()]
    if special_cases:
        print(f"Found {len(special_cases)} HRBPs with comments:")
        for case in special_cases:
            print(f"  {case['hrbp']}: {case['comments'][:100]}")
    else:
        print("No special cases flagged")

    # Step 8: Draft confirmation emails
    print("\n[Step 8] Drafting confirmation emails...")
    for resp in responses[:2]:
        nominees_str = ", ".join(resp["nominees"])
        print(f"\n--- CONFIRMATION TO: {resp['hrbp']} ---")
        email = draft_email("confirmation", {
            "hrbp_name": resp["hrbp"],
            "nominees":  nominees_str,
        })
        print(email[:300] + "...")

    # Step 9: Draft joining emails
    print("\n[Step 9] Drafting joining emails...")
    all_nominees = []
    for resp in responses:
        all_nominees.extend(resp["nominees"])
    for participant in all_nominees[:2]:
        print(f"\n--- JOINING EMAIL TO: {participant} ---")
        email = draft_email("joining", {"participant": participant})
        print(email[:300] + "...")

    print("\n" + "="*60)
    print("AGENT 1 COMPLETE")
    print(f"TBD employees in scope:    {tracker_data['total_tbd']}")
    print(f"Previous non-attendees:    {len(prev_non_attendees)}")
    print(f"HRBPs responded:           {len(responses)}/{len(ALL_HRBPS)}")
    print(f"Reminder emails drafted:   {len(non_responders)}")
    print(f"Nominated ({BATCH_NAME}):  {result['updated']}")
    print(f"Deferred ({NEXT_BATCH_NAME}): {len(result['deferred'])}")
    print(f"Special cases:             {len(special_cases)}")
    print(f"Confirmation emails:       {len(responses)} drafted")
    print(f"Joining emails:            {len(all_nominees)} drafted")
    print("="*60)


if __name__ == "__main__":
    run_agent1()
