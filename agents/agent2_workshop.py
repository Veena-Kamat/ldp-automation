import anthropic
from dotenv import load_dotenv
import os
import gspread
import urllib.request
import csv
import io
from google.oauth2.service_account import Credentials
from datetime import date

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

LDP_TRACKER_ID   = "1z0-TFgYUmftZglGwGlaDbkgEM3k8VfaIOm4Rl8RmFow"
ATTENDANCE_ID    = "1nsvTzUEMAKFlR8LlKGnJmQZ5TMtruxbUwhCMUZ0WQW4"
CREDENTIALS_FILE = "/Users/veenakamat/ldp-agent/google_credentials.json"
BATCH_NAME       = "Batch-03-2026"
TODAY            = date.today().strftime("%d-%b-%Y")

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
    creds = Credentials.from_service_account_file(
        CREDENTIALS_FILE, scopes=scopes
    )
    return gspread.authorize(creds)

def read_attendance():
    gc = connect()
    wb = gc.open_by_key(ATTENDANCE_ID)
    ws = wb.get_worksheet(0)
    all_rows = ws.get_all_values()
    headers = all_rows[1]
    data = []
    for row in all_rows[2:]:
        if any(cell.strip() for cell in row):
            data.append(dict(zip(headers, row)))
    return data

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
    return {emp.get("Emp ID","").strip(): emp for emp in data}

def update_attendance_in_tracker(attendance_data, tracker_data):
    gc = connect()
    wb = gc.open_by_key(LDP_TRACKER_ID)
    ws = wb.worksheet("LDP Tracker")

    all_values = ws.get_all_values()
    headers = [clean_header(h) for h in all_values[1]]
    col_idx = {h: i for i, h in enumerate(headers)}
    data_rows = all_values[2:]

    emp_id_col = col_idx.get("Emp ID", -1)
    d1_col     = col_idx.get("Day 1 Attendance", -1)
    d2_col     = col_idx.get("Day 2 Attendance", -1)

    att_map = {}
    for row in attendance_data:
        emp_id = row.get("Emp ID","").strip()
        d1 = row.get("Day 1 (31-Mar)","").strip()
        d2 = row.get("Day 2 (01-Apr)","").strip()
        if emp_id:
            att_map[emp_id] = {"d1": d1, "d2": d2}

    updates = []
    for row_idx, row in enumerate(data_rows):
        emp_id = row[emp_id_col].strip() if emp_id_col >= 0 and len(row) > emp_id_col else ""
        if emp_id in att_map:
            sheet_row = row_idx + 3
            updates.append({
                "range": f"{col_letter(d1_col)}{sheet_row}:{col_letter(d2_col)}{sheet_row}",
                "values": [[att_map[emp_id]["d1"], att_map[emp_id]["d2"]]]
            })

    if updates:
        ws.batch_update(updates)
        print(f"Updated attendance for {len(updates)} employees")
    return att_map

def draft_nonattendee_email(emp_name, emp_function, batch,
                             d1, d2, reason,
                             manager_name, hrbp_name):
    missed = []
    if d1 != "Attended":
        missed.append("Day 1 (31 March)")
    if d2 != "Attended":
        missed.append("Day 2 (1 April)")
    missed_str = " and ".join(missed)

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        messages=[{
            "role": "user",
            "content": f"""Draft a professional and empathetic follow up email 
to an employee who missed their LDP workshop session.

Details:
- Employee: {emp_name}
- Function: {emp_function}
- Batch: {batch}
- Missed: {missed_str}
- Reason on record: {reason if reason else 'Not provided'}
- Manager (in CC): {manager_name}
- HRBP (in CC): {hrbp_name}

The email should:
- Be addressed to the employee
- Acknowledge they missed the session
- Express that we hope they are well (especially if medical)
- Mention they will be considered for the next available batch
- Ask them to confirm their availability for rescheduling
- Keep it warm and supportive — not punitive
- Mention manager and HRBP are copied

Sign off as: LDP Programme Team"""
        }]
    )
    return message.content[0].text

def run_agent2():
    print("\n" + "="*60)
    print("AGENT 2 — POST WORKSHOP")
    print(f"Batch: {BATCH_NAME}")
    print(f"Running: {TODAY}")
    print("="*60)

    # Step 1: Read attendance sheet
    print("\n[Step 1] Reading attendance sheet...")
    attendance = read_attendance()
    print(f"Found {len(attendance)} attendance records")

    # Step 2: Read LDP Tracker for context
    print("\n[Step 2] Reading LDP Tracker...")
    tracker = read_ldp_tracker()
    print(f"Loaded {len(tracker)} employees from tracker")

    # Step 3: Update tracker with attendance
    print("\n[Step 3] Updating attendance in LDP Tracker...")
    att_map = update_attendance_in_tracker(attendance, tracker)

    # Step 4: Identify non-attendees
    print("\n[Step 4] Identifying non-attendees...")
    non_attendees = []
    for row in attendance:
        emp_id = row.get("Emp ID","").strip()
        d1 = row.get("Day 1 (31-Mar)","").strip()
        d2 = row.get("Day 2 (01-Apr)","").strip()
        if d1 != "Attended" or d2 != "Attended":
            tracker_emp = tracker.get(emp_id, {})
            non_attendees.append({
                "emp_id":   emp_id,
                "name":     row.get("Employee Name","").strip(),
                "function": tracker_emp.get("Function",""),
                "d1":       d1,
                "d2":       d2,
                "manager":  tracker_emp.get("Manager Name",""),
                "hrbp":     tracker_emp.get("HRBP Name",""),
            })

    print(f"Found {len(non_attendees)} non/partial attendees")
    for na in non_attendees:
        status = "Absent both days" if na["d1"]=="Absent" and na["d2"]=="Absent" else "Partial"
        print(f"  {na['name']} — {status} | Mgr: {na['manager']} | HRBP: {na['hrbp']}")

    # Step 5: Draft follow-up emails
    print("\n[Step 5] Drafting follow-up emails...")
    for na in non_attendees:
        print(f"\n{'='*60}")
        print(f"TO:  {na['name']}")
        print(f"CC:  {na['manager']} (Manager), {na['hrbp']} (HRBP)")
        print(f"{'='*60}")
        email = draft_nonattendee_email(
            emp_name    = na["name"],
            emp_function= na["function"],
            batch       = BATCH_NAME,
            d1          = na["d1"],
            d2          = na["d2"],
            reason      = "",
            manager_name= na["manager"],
            hrbp_name   = na["hrbp"]
        )
        print(email)

    print("\n" + "="*60)
    print("AGENT 2 COMPLETE")
    print(f"Attendance updated: {len(att_map)} employees")
    print(f"Follow-up emails drafted: {len(non_attendees)}")
    print("="*60)

run_agent2()
