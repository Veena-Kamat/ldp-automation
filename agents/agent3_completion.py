import anthropic
from dotenv import load_dotenv
import os
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import urllib.request
import csv
import io
from datetime import date, datetime, timedelta

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

LDP_TRACKER_ID      = "1z0-TFgYUmftZglGwGlaDbkgEM3k8VfaIOm4Rl8RmFow"
VL_FOLDER_ID        = "1aLfL_5OkVpMAe4QZnCFr02h01PKqIC12"
FALLBACK_VL_SHEET_ID = "1QZSpDzXmk0MvYWxr5yfK7HyPxPIgkgDgrKxOCyF4GuQ"
CREDENTIALS_FILE = "/Users/veenakamat/ldp-agent/google_credentials.json"
TODAY            = date.today().strftime("%d-%b-%Y")
TODAY_DATE       = date.today()

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
    return gspread.authorize(creds), creds

# ── TOOL 1: Find latest VL report via Drive API ───────────────
def get_latest_vl_report(fallback_sheet_id=FALLBACK_VL_SHEET_ID):
    """Find latest VL report in folder. Falls back to manual ID if Drive API disabled."""
    try:
        gc, creds = connect()
        drive_service = build("drive", "v3", credentials=creds)
        results = drive_service.files().list(
            q=f"'{VL_FOLDER_ID}' in parents and (name contains 'VL_Report' or name contains 'VL_report') and trashed=false",
            orderBy="modifiedTime desc",
            pageSize=1,
            fields="files(id, name, modifiedTime)"
        ).execute()
        files = results.get("files", [])
        if not files:
            print("No VL_Report files found in the VL folder.")
            return None, None
        latest = files[0]
        print(f"Latest VL report: {latest['name']} (modified: {latest['modifiedTime'][:10]})")
        return latest["id"], latest["name"]
    except Exception as e:
        err = str(e)
        if "403" in err or "disabled" in err or "accessNotConfigured" in err:
            print("\n[WARNING] Google Drive API is not enabled for this project.")
            print("To fix: visit https://console.developers.google.com/apis/api/drive.googleapis.com/overview?project=157709324590")
            print("Click 'Enable', wait ~2 minutes, then retry.\n")
        else:
            print(f"[WARNING] Drive API error: {e}\n")

        if fallback_sheet_id:
            print(f"Using provided VL report sheet ID: {fallback_sheet_id}")
            return fallback_sheet_id, "VL_Report (manual)"

        sheet_id = input("Enter the VL Report Google Sheet ID to continue: ").strip()
        return (sheet_id, "VL_Report (manual)") if sheet_id else (None, None)

# ── TOOL 2: Read VL report ────────────────────────────────────
def read_vl_report(sheet_id):
    gc, _ = connect()
    wb = gc.open_by_key(sheet_id)
    all_data = {}
    for ws in wb.worksheets():
        batch_name = ws.title
        if "Batch" not in batch_name:
            continue
        rows = ws.get_all_values()
        if len(rows) < 3:
            all_data[batch_name] = []
            continue
        headers = rows[2]
        data = []
        for row in rows[3:]:
            if any(cell.strip() for cell in row):
                data.append(dict(zip(headers, row)))
        all_data[batch_name] = data
        print(f"  {batch_name}: {len(data)} employees")
    return all_data

# ── TOOL 3: Read LDP Tracker ──────────────────────────────────
def read_ldp_tracker():
    url = f"https://docs.google.com/spreadsheets/d/{LDP_TRACKER_ID}/gviz/tq?tqx=out:csv&sheet=LDP%20Tracker"
    response = urllib.request.urlopen(url)
    content = response.read().decode("utf-8")
    reader = csv.reader(io.StringIO(content))
    all_rows = list(reader)
    headers = [clean_header(h) for h in all_rows[0]]
    data = []
    for row in all_rows[1:]:
        if any(cell.strip() for cell in row):
            data.append(dict(zip(headers, row)))
    return {emp.get("Emp ID", "").strip(): emp for emp in data}

# ── TOOL 4: Update VL + completion status in tracker ─────────
def update_vl_in_tracker(vl_data, tracker_data):
    gc, _ = connect()
    wb = gc.open_by_key(LDP_TRACKER_ID)
    ws = wb.worksheet("LDP Tracker")
    all_values = ws.get_all_values()
    headers = [clean_header(h) for h in all_values[1]]
    col_idx = {h: i for i, h in enumerate(headers)}
    data_rows = all_values[2:]

    emp_id_col    = col_idx.get("Emp ID", -1)
    vl_status_col = col_idx.get("VL Status", -1)
    vl_pct_col    = col_idx.get("VL Completion %", -1)
    vl_score_col  = col_idx.get("VL Score (%)", -1)
    vl_date_col   = col_idx.get("VL Completion Date", -1)
    train_col     = col_idx.get("Training Complete", -1)
    cert_col      = col_idx.get("Certificate Eligible", -1)
    nudge_col     = col_idx.get("VL Nudge Date", col_idx.get("Nudge Date", -1))

    vl_lookup = {}
    for batch_name, employees in vl_data.items():
        for emp in employees:
            emp_id = emp.get("Emp ID", "").strip()
            if emp_id:
                vl_lookup[emp_id] = {
                    "status": emp.get("Overall Status", "").strip(),
                    "pct":    emp.get("Completion %", "").strip(),
                    "score":  emp.get("Avg Score", "").strip(),
                    "date":   emp.get("M8 Date", "").strip() if emp.get("Overall Status", "") == "Completed" else "",
                }

    updates = []
    completed_employees = []
    needs_nudge = []
    needs_second_nudge = []

    for row_idx, row in enumerate(data_rows):
        emp_id = row[emp_id_col].strip() if emp_id_col >= 0 and len(row) > emp_id_col else ""
        if emp_id not in vl_lookup:
            continue

        vl = vl_lookup[emp_id]
        sheet_row = row_idx + 3

        d1 = row[col_idx.get("Day 1 Attendance", -1)].strip() if col_idx.get("Day 1 Attendance", -1) >= 0 else ""
        d2 = row[col_idx.get("Day 2 Attendance", -1)].strip() if col_idx.get("Day 2 Attendance", -1) >= 0 else ""
        attended_both = (d1 == "Attended" and d2 == "Attended")

        train_complete = "Yes" if (attended_both and vl["status"] == "Completed") else "No"
        cert_eligible  = "Yes" if train_complete == "Yes" else "No"

        # Build update range (VL Status → Certificate Eligible)
        range_str = f"{col_letter(vl_status_col)}{sheet_row}:{col_letter(cert_col)}{sheet_row}"
        updates.append({
            "range":  range_str,
            "values": [[vl["status"], vl["pct"], vl["score"], vl["date"], train_complete, cert_eligible]]
        })

        emp_name = row[col_idx.get("Employee Name", -1)].strip() if col_idx.get("Employee Name", -1) >= 0 else emp_id

        if train_complete == "Yes":
            completed_employees.append({
                "emp_id":   emp_id,
                "name":     emp_name,
                "hrbp":     row[col_idx.get("HRBP Name", -1)].strip() if col_idx.get("HRBP Name", -1) >= 0 else "",
                "function": row[col_idx.get("Function", -1)].strip() if col_idx.get("Function", -1) >= 0 else "",
                "manager":  row[col_idx.get("Manager Name", -1)].strip() if col_idx.get("Manager Name", -1) >= 0 else "",
                "batch":    row[col_idx.get("Batch", -1)].strip() if col_idx.get("Batch", -1) >= 0 else "",
            })

        if vl["status"] in ("Not Started", "In Progress") and attended_both:
            # Check if first nudge was already sent (>7 days ago)
            nudge_date_str = ""
            if nudge_col >= 0 and len(row) > nudge_col:
                nudge_date_str = row[nudge_col].strip()

            nudge_data = {
                "emp_id":  emp_id,
                "name":    emp_name,
                "pct":     vl["pct"],
                "status":  vl["status"],
                "hrbp":    row[col_idx.get("HRBP Name", -1)].strip() if col_idx.get("HRBP Name", -1) >= 0 else "",
                "manager": row[col_idx.get("Manager Name", -1)].strip() if col_idx.get("Manager Name", -1) >= 0 else "",
                "nudge_date": nudge_date_str,
            }

            if nudge_date_str:
                try:
                    nudge_date = datetime.strptime(nudge_date_str, "%d-%b-%Y").date()
                    if (TODAY_DATE - nudge_date).days >= 7:
                        needs_second_nudge.append(nudge_data)
                    # If < 7 days, first nudge already sent recently — skip
                except ValueError:
                    needs_nudge.append(nudge_data)
            else:
                needs_nudge.append(nudge_data)

    if updates:
        ws.batch_update(updates)
        print(f"Updated VL data for {len(updates)} employees")

    return completed_employees, needs_nudge, needs_second_nudge

# ── TOOL 5: Remove completers, flag non-completers ────────────
def finalise_batch_in_tracker(completed_employees, non_completers, batch_name):
    """
    For a batch being closed:
    - Mark completed employees: Training Complete = Yes, Certificate Eligible = Yes
    - Flag non-completers with a note for follow-up
    Returns a summary dict.
    """
    gc, _ = connect()
    wb = gc.open_by_key(LDP_TRACKER_ID)
    ws = wb.worksheet("LDP Tracker")
    all_values = ws.get_all_values()
    headers = [clean_header(h) for h in all_values[1]]
    col_idx = {h: i for i, h in enumerate(headers)}
    data_rows = all_values[2:]

    emp_id_col   = col_idx.get("Emp ID", -1)
    followup_col = col_idx.get("Follow Up Required", col_idx.get("Notes", -1))

    completed_ids  = {e["emp_id"] for e in completed_employees}
    non_comp_ids   = {e["emp_id"] for e in non_completers}

    updates = []
    for row_idx, row in enumerate(data_rows):
        emp_id = row[emp_id_col].strip() if emp_id_col >= 0 and len(row) > emp_id_col else ""
        sheet_row = row_idx + 3

        if emp_id in non_comp_ids and followup_col >= 0:
            updates.append({
                "range":  f"{col_letter(followup_col)}{sheet_row}",
                "values": [["VL Not Completed — Follow Up Required"]]
            })

    if updates:
        ws.batch_update(updates)
        print(f"Flagged {len(updates)} non-completers for follow-up")

    return {
        "batch":       batch_name,
        "completed":   len(completed_employees),
        "not_completed": len(non_completers),
    }

# ── Email drafters ─────────────────────────────────────────────
def draft_certificate_email(emp_name, function, batch):
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        messages=[{"role": "user", "content": f"""Draft a warm congratulations email
to an employee who has completed the Leadership Development Programme.

Details:
- Employee: {emp_name}
- Function: {function}
- Batch: {batch}
- Today: {TODAY}

The email should:
- Congratulate them warmly on completing LDP
- Mention they completed both workshop days AND all virtual learning modules
- Tell them their certificate of completion will be attached
- Encourage them to apply their learnings
- Be warm and celebratory but professional
- Sign off as: LDP Programme Team

Write in plain text only. Do not use ** for bold or any markdown formatting.
Write as a complete ready-to-send email with subject line."""}]
    )
    return message.content[0].text

def draft_nudge_email(emp_name, vl_pct, vl_status, manager_name, is_second=False):
    nudge_type = "second reminder" if is_second else "friendly nudge"
    urgency = "We wanted to follow up again as your VL modules are still pending." if is_second else ""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        messages=[{"role": "user", "content": f"""Draft a {nudge_type} email
to an employee who hasn't completed their virtual learning.

Details:
- Employee: {emp_name}
- VL Status: {vl_status}
- Completion: {vl_pct}
- Manager CC: {manager_name}
- Context: {urgency}

The email should:
- Be friendly and encouraging {'with a sense of urgency' if is_second else ''}
- Remind them VL is part of their LDP completion
- Mention their current progress ({vl_pct} complete)
- Ask them to complete remaining modules
- {'Mention their manager is being kept informed' if is_second else 'Keep it short — 3-4 sentences max'}
- Sign off as: LDP Programme Team

Write in plain text only. Do not use ** for bold or any markdown formatting.
Write as a complete ready-to-send email with subject line."""}]
    )
    return message.content[0].text

def draft_feedback_survey_participant(emp_name, batch):
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        messages=[{"role": "user", "content": f"""Draft a feedback request email
to an LDP graduate asking for their programme feedback.

Details:
- Employee: {emp_name}
- Batch: {batch}
- Today: {TODAY}

The email should:
- Thank them for completing LDP
- Ask them to share feedback on the programme experience
- Mention it takes only 5 minutes
- Say their feedback helps improve future batches
- Include a placeholder [FEEDBACK LINK HERE] for the form URL
- Be warm and brief (3-4 sentences)
- Sign off as: LDP Programme Team

Write in plain text only. Do not use ** for bold or any markdown formatting.
Write as a complete ready-to-send email with subject line."""}]
    )
    return message.content[0].text

def draft_feedback_survey_manager(manager_name, emp_name, batch):
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        messages=[{"role": "user", "content": f"""Draft a feedback request email
to a manager of an LDP graduate, asking for their observation of the programme's impact.

Details:
- Manager: {manager_name}
- Employee: {emp_name}
- Batch: {batch}
- Today: {TODAY}

The email should:
- Inform the manager that {emp_name} has completed LDP
- Ask them to share observations on any behavioural changes or growth they've noticed
- Mention it takes only 5 minutes
- Include a placeholder [MANAGER FEEDBACK LINK HERE] for the form URL
- Be professional and brief
- Sign off as: LDP Programme Team

Write in plain text only. Do not use ** for bold or any markdown formatting.
Write as a complete ready-to-send email with subject line."""}]
    )
    return message.content[0].text

def generate_feedback_insights(feedback_data):
    """Generate an insights report from feedback responses using Claude."""
    if not feedback_data:
        return "No feedback data available to generate insights."

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        messages=[{"role": "user", "content": f"""You are an L&D analyst. Analyse the following
LDP programme feedback responses and generate a concise insights report.

Feedback data:
{feedback_data}

Your report should include:
1. Overall sentiment (positive/neutral/negative breakdown)
2. Top 3 strengths of the programme
3. Top 3 areas for improvement
4. Key themes that appear across multiple responses
5. Recommended actions for the next batch
6. Any standout quotes worth highlighting

Format the report clearly with headers. Be specific and data-driven."""}]
    )
    return message.content[0].text

def generate_batch_closed_report(batch_name, completed, needs_nudge, needs_second_nudge, tbd_employees):
    """Generate a batch closure summary report for the supervisor."""
    total_batch = len(completed) + len(needs_nudge) + len(needs_second_nudge)
    non_completers = needs_nudge + needs_second_nudge

    report = f"""
{'='*60}
BATCH CLOSURE REPORT — {batch_name}
Generated: {TODAY}
{'='*60}

COMPLETION SUMMARY:
  Total in batch:          {total_batch}
  Training complete:       {len(completed)} ({int(len(completed)/max(total_batch,1)*100)}%)
  VL not yet complete:     {len(non_completers)}
    - First nudge needed:  {len(needs_nudge)}
    - Second nudge needed: {len(needs_second_nudge)}

COMPLETERS (certificate eligible):
"""
    for emp in completed:
        report += f"  ✓ {emp['name']} ({emp.get('function','')}) — {emp.get('batch','')}\n"

    if non_completers:
        report += "\nNON-COMPLETERS (follow-up required):\n"
        for emp in non_completers:
            report += f"  ✗ {emp['name']} — {emp['pct']} complete | HRBP: {emp['hrbp']}\n"

    if tbd_employees:
        report += f"\nTBD EMPLOYEES (not yet assigned to a batch): {len(tbd_employees)}\n"
        for emp in tbd_employees[:5]:
            report += f"  - {emp.get('Employee Name','')} | HRBP: {emp.get('HRBP Name','')}\n"
        if len(tbd_employees) > 5:
            report += f"  ... and {len(tbd_employees) - 5} more\n"

    report += f"""
STATUS: {'BATCH CLOSED' if len(non_completers) == 0 else 'BATCH PARTIALLY CLOSED — follow-ups pending'}
{'='*60}
"""
    return report

def get_tbd_employees():
    """Return list of employees still not assigned to any batch."""
    url = f"https://docs.google.com/spreadsheets/d/{LDP_TRACKER_ID}/gviz/tq?tqx=out:csv&sheet=LDP%20Tracker"
    response = urllib.request.urlopen(url)
    content = response.read().decode("utf-8")
    reader = csv.reader(io.StringIO(content))
    all_rows = list(reader)
    headers = [clean_header(h) for h in all_rows[0]]
    data = []
    for row in all_rows[1:]:
        if any(cell.strip() for cell in row):
            data.append(dict(zip(headers, row)))
    return [emp for emp in data if emp.get("Batch", "").strip() == "TBD"]


# ── MAIN AGENT 3 RUNNER ───────────────────────────────────────
def run_agent3(vl_sheet_id=None):
    print("\n" + "="*60)
    print("AGENT 3 — VL TRACKING & COMPLETION")
    print(f"Running: {TODAY}")
    print("="*60)

    # Step 1: Find latest VL report
    print("\n[Step 1] Finding latest VL report...")
    vl_sheet_id, vl_filename = get_latest_vl_report(fallback_sheet_id=vl_sheet_id)
    if not vl_sheet_id:
        print("No VL report found. Exiting.")
        return

    # Step 2: Read VL data
    print("\n[Step 2] Reading VL report...")
    vl_data = read_vl_report(vl_sheet_id)

    # Step 3: Read LDP Tracker
    print("\n[Step 3] Reading LDP Tracker...")
    tracker = read_ldp_tracker()
    print(f"Loaded {len(tracker)} employees")

    # Step 4: Update tracker with VL data
    print("\n[Step 4] Updating VL data in tracker...")
    completed, needs_nudge, needs_second_nudge = update_vl_in_tracker(vl_data, tracker)

    # Step 5: Certificate emails
    print(f"\n[Step 5] {len(completed)} employees completed training!")
    for emp in completed[:2]:
        print("="*60)
        print(f"CERTIFICATE EMAIL TO: {emp['name']}")
        print("="*60)
        email = draft_certificate_email(emp["name"], emp["function"], emp.get("batch", "LDP 2026"))
        print(email)
        print()

    # Step 6: First nudge emails
    print(f"\n[Step 6] {len(needs_nudge)} employees need FIRST VL nudge")
    for emp in needs_nudge[:2]:
        print("="*60)
        print(f"NUDGE EMAIL TO: {emp['name']} ({emp['pct']} complete)")
        print("="*60)
        email = draft_nudge_email(emp["name"], emp["pct"], emp["status"], emp["manager"], is_second=False)
        print(email)
        print()

    # Step 7: Second nudge emails (week 2 check)
    print(f"\n[Step 7] {len(needs_second_nudge)} employees need SECOND VL nudge (>7 days since first)")
    for emp in needs_second_nudge[:2]:
        print("="*60)
        print(f"SECOND NUDGE TO: {emp['name']} ({emp['pct']} complete, nudged {emp['nudge_date']})")
        print("="*60)
        email = draft_nudge_email(emp["name"], emp["pct"], emp["status"], emp["manager"], is_second=True)
        print(email)
        print()

    # Step 8: Feedback survey emails (participant + manager)
    print(f"\n[Step 8] Drafting feedback survey emails for {len(completed)} completers...")
    for emp in completed[:2]:
        print("="*60)
        print(f"PARTICIPANT FEEDBACK — TO: {emp['name']}")
        print("="*60)
        email = draft_feedback_survey_participant(emp["name"], emp.get("batch", "LDP 2026"))
        print(email)
        print()
        print("="*60)
        print(f"MANAGER FEEDBACK — TO: {emp.get('manager','Manager')} (re: {emp['name']})")
        print("="*60)
        email = draft_feedback_survey_manager(emp.get("manager", "Manager"), emp["name"], emp.get("batch", "LDP 2026"))
        print(email)
        print()

    # Step 9: Flag non-completers in tracker
    non_completers = needs_nudge + needs_second_nudge
    if non_completers:
        print(f"\n[Step 9] Flagging {len(non_completers)} non-completers in tracker...")
        finalise_batch_in_tracker(completed, non_completers, "LDP 2026")

    # Step 10: Identify remaining TBD employees
    print("\n[Step 10] Checking remaining TBD employees...")
    tbd = get_tbd_employees()
    print(f"Found {len(tbd)} employees not yet assigned to a batch")

    # Step 11: Batch closed report
    print("\n[Step 11] Generating batch closed report...")
    # Determine batch name from first completer
    batch_name = completed[0].get("batch", "LDP 2026") if completed else "LDP 2026"
    report = generate_batch_closed_report(batch_name, completed, needs_nudge, needs_second_nudge, tbd)
    print(report)

    print("="*60)
    print("AGENT 3 COMPLETE")
    print(f"VL updated:            {len(completed) + len(needs_nudge) + len(needs_second_nudge)} employees")
    print(f"Certificates eligible: {len(completed)}")
    print(f"First nudge emails:    {len(needs_nudge)}")
    print(f"Second nudge emails:   {len(needs_second_nudge)}")
    print(f"Feedback emails:       {len(completed) * 2} (participant + manager)")
    print(f"TBD employees:         {len(tbd)}")
    print("="*60)


if __name__ == "__main__":
    import sys
    # Pass VL report sheet ID as first argument to bypass Drive API
    # e.g. python3 agent3_completion.py 1-cKaveDPqRyj8PR7b2jMegHyNbipyOIT7B7mLi68HRI
    sheet_arg = sys.argv[1] if len(sys.argv) > 1 else None
    run_agent3(vl_sheet_id=sheet_arg)
