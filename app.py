from flask import Flask, render_template, request, jsonify, make_response
from dotenv import load_dotenv
import anthropic
import urllib.request
import csv
import io
import os
import json
from datetime import date
import gspread
from google.oauth2.service_account import Credentials

load_dotenv()

app = Flask(__name__)
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

LDP_TRACKER_ID   = "1z0-TFgYUmftZglGwGlaDbkgEM3k8VfaIOm4Rl8RmFow"
NOMINATIONS_ID   = "1Bc-eNUYt15SiDBUccajt0tlgeuCXOKkihb7Zb3UfKiM"
EMPLOYEE_BASE_ID = "1pT6HJ2Wx0qrUYssUPYx9DcrRTSEyhqex4PsTdriT3Gk"
VL_SHEET_ID      = "1QZSpDzXmk0MvYWxr5yfK7HyPxPIgkgDgrKxOCyF4GuQ"
CREDENTIALS_FILE = "/Users/veenakamat/ldp-agent/google_credentials.json"
GSPREAD_SCOPES   = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

def connect_gspread():
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        info = json.loads(creds_json)
        creds = Credentials.from_service_account_info(info, scopes=GSPREAD_SCOPES)
    else:
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=GSPREAD_SCOPES)
    return gspread.authorize(creds)

def read_vl_data():
    """Return {emp_id: {status, pct, score}} for all batches in the VL report."""
    gc = connect_gspread()
    wb = gc.open_by_key(VL_SHEET_ID)
    lookup = {}
    for ws in wb.worksheets():
        if "Batch" not in ws.title:
            continue
        rows = ws.get_all_values()
        # Find header row — look for a row whose first cell is "Emp ID"
        header_idx = next(
            (i for i, r in enumerate(rows[:5]) if r and r[0].strip() == "Emp ID"),
            2
        )
        if header_idx >= len(rows):
            continue
        headers = rows[header_idx]
        col = {h.strip(): i for i, h in enumerate(headers)}
        for row in rows[header_idx + 1:]:
            emp_id = row[col["Emp ID"]].strip() if "Emp ID" in col and len(row) > col["Emp ID"] else ""
            if not emp_id:
                continue
            def get(key):
                idx = col.get(key, -1)
                return row[idx].strip() if idx >= 0 and len(row) > idx else ""
            lookup[emp_id] = {
                "status": get("Overall Status"),
                "pct":    get("Completion %"),
                "score":  get("Avg Score"),
            }
    return lookup

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

def read_tracker():
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
    return data

def read_employee_base():
    url = f"https://docs.google.com/spreadsheets/d/{EMPLOYEE_BASE_ID}/gviz/tq?tqx=out:csv"
    response = urllib.request.urlopen(url)
    content = response.read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))
    return [row for row in reader]

def build_email_lookup(base_data):
    # First pass: name → email for the full population (to resolve managers/HRBPs)
    name_to_email = {}
    for row in base_data:
        name  = row.get("Employee Name", "").strip()
        email = row.get("Work Email", "").strip()
        if name and email:
            name_to_email[name] = email

    # Second pass: build full contact record per employee
    lookup = {}
    for row in base_data:
        name = row.get("Employee Name", "").strip()
        if not name:
            continue
        manager_name = row.get("Manager Name", "").strip()
        hrbp_name    = row.get("HRBP Name", "").strip()
        lookup[name] = {
            "email":         row.get("Work Email", "").strip(),
            "manager_name":  manager_name,
            "manager_email": name_to_email.get(manager_name, ""),
            "hrbp_name":     hrbp_name,
            "hrbp_email":    name_to_email.get(hrbp_name, ""),
        }
    return lookup

def read_nominations():
    url = f"https://docs.google.com/spreadsheets/d/{NOMINATIONS_ID}/gviz/tq?tqx=out:csv&gid=1000019961"
    response = urllib.request.urlopen(url)
    content = response.read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))
    return [row for row in reader]

def build_programme_data(tracker, nominations, email_lookup=None, vl_lookup=None):
    today = date.today()
    today_str = today.strftime("%d %B %Y")

    batch_config = {
        "Batch-01-2026": {"label": "Batch 01", "date": "Jan 2026", "workshop": "27-28 Jan 2026"},
        "Batch-02-2026": {"label": "Batch 02", "date": "Feb 2026", "workshop": "24-25 Feb 2026"},
        "Batch-03-2026": {"label": "Batch 03", "date": "Mar 2026", "workshop": "31 Mar-1 Apr 2026"},
        "Batch-04-2026": {"label": "Batch 04", "date": "Apr 2026", "workshop": "28-29 Apr 2026"},
    }

    batches = {}
    for bn in batch_config:
        batches[bn] = {
            "total": 0, "nominated": 0,
            "attended_both": 0, "absent": 0,
            "vl_completed": 0, "vl_in_progress": 0,
            "vl_not_started": 0, "training_complete": 0,
            "certs_issued": 0,
            "vl_not_started_names": [],
            "absent_names": [],
        }

    tbd_count = 0
    total_employees = len(tracker)

    for emp in tracker:
        batch = emp.get("Batch", "").strip()
        name = emp.get("Employee Name", "").strip()
        hrbp = emp.get("HRBP Name", "").strip()

        if not batch or batch == "TBD":
            tbd_count += 1
            continue

        if batch not in batches:
            continue

        b = batches[batch]
        b["total"] += 1

        nom_status = emp.get("Nomination Status", "").strip()
        if nom_status in ("Nominated", "Confirmed"):
            b["nominated"] += 1

        d1 = emp.get("Day 1 Attendance", "").strip()
        d2 = emp.get("Day 2 Attendance", "").strip()

        def attended(val):
            return bool(val) and val.lower() not in ("absent", "")

        if attended(d1) and attended(d2):
            b["attended_both"] += 1
        elif not attended(d1) or not attended(d2):
            if b["total"] > 0 and (d1 or d2):
                b["absent"] += 1
                b["absent_names"].append(f"{name} (HRBP: {hrbp})")

        vl = emp.get("VL Status", "").strip()
        if vl == "Completed":
            b["vl_completed"] += 1
        elif vl == "In Progress":
            b["vl_in_progress"] += 1
        elif vl == "Not Started":
            b["vl_not_started"] += 1
            b["vl_not_started_names"].append(f"{name} (HRBP: {hrbp})")

        if emp.get("Training Complete", "").strip() == "Yes":
            b["training_complete"] += 1

        cert_date = emp.get("Certificate Issued Date", "").strip()
        if cert_date and cert_date not in ("", "—"):
            b["certs_issued"] += 1

    all_hrbps = [
        "Aisha Walker", "Aparna Johnson", "Ishaan Farouk",
        "Mariam Lee", "Meghna Iqbal", "Nawaf Bhat",
        "Pranav Young", "Ryan Venkataraman", "Saif Sivasubramanian",
        "Salman Varma", "Thomas Subramaniam", "Yusuf Jackson",
        "Daniel Smith", "Maria Verma", "Hamdan Malik",
        "Thomas Varma", "Stanley Al-Dhaheri", "Anita Al-Farsi",
        "Varun Al-Farsi"
    ]

    responded_hrbps = set()
    total_nominees = 0
    special_cases = []
    nom_by_hrbp = {}

    for nom in nominations:
        hrbp = ""
        nominees = []
        comments = ""
        for key, value in nom.items():
            k = key.lower()
            if "name" in k and not nominees:
                hrbp = value.strip()
            if "nominate" in k or "eligible" in k:
                nominees = [n.strip() for n in value.split(",") if n.strip()]
            if "comment" in k or "special" in k:
                comments = value.strip()
        if hrbp:
            responded_hrbps.add(hrbp)
            total_nominees += len(nominees)
            nom_by_hrbp[hrbp] = nominees
            if comments:
                special_cases.append({"hrbp": hrbp, "comment": comments})

    not_responded = [h for h in all_hrbps if h not in responded_hrbps]

    total_completed = sum(b["training_complete"] for b in batches.values())
    total_in_progress = sum(b["vl_in_progress"] for b in batches.values())
    total_certs = sum(b["certs_issued"] for b in batches.values())
    action_needed = len(not_responded) + sum(b["vl_not_started"] for b in batches.values())

    batch_status = []
    for bn, cfg in batch_config.items():
        b = batches[bn]
        if bn == "Batch-04-2026":
            if b["total"] > 0 and b["attended_both"] > 0:
                desc = f"{b['attended_both']} attended · workshop done"
                color = "amber"
            else:
                days_to = (date(2026, 4, 28) - today).days
                if days_to > 0:
                    desc = f"{b['nominated']} nominated · workshop in {days_to} days"
                else:
                    desc = f"{b['nominated']} nominated · workshop complete"
                color = "grey"
        elif b["training_complete"] > 0 and b["training_complete"] == b["attended_both"]:
            desc = f"{b['training_complete']} certified · complete"
            color = "green"
        elif b["vl_completed"] > 0:
            desc = f"{b['vl_completed']} certified · {b['vl_in_progress']} in progress"
            color = "green"
        elif b["vl_in_progress"] > 0:
            desc = f"{b['vl_in_progress']} VL in progress · {b['vl_not_started']} not started"
            color = "amber"
        elif b["attended_both"] > 0:
            desc = f"{b['attended_both']} attended · VL starting"
            color = "amber"
        else:
            desc = f"{b['total']} employees · pending"
            color = "grey"

        batch_status.append({
            "name": cfg["label"],
            "date": cfg["date"],
            "color": color,
            "desc": desc,
        })

    programme_data = {
        "today": today_str,
        "total_employees": total_employees,
        "tbd_count": tbd_count,
        "total_completed": total_completed,
        "total_certs": total_certs,
        "action_needed": action_needed,
        "batches": batches,
        "batch_status": batch_status,
        "nominations": {
            "responded": len(responded_hrbps),
            "total": len(all_hrbps),
            "not_responded": not_responded,
            "total_nominees": total_nominees,
            "special_cases": special_cases,
        },
    }

    text_summary = f"""
TODAY: {today_str}

PROGRAMME OVERVIEW:
- {total_employees} total employees in scope
- {tbd_count} employees awaiting batch assignment (TBD)
- {total_certs} certificates issued to date
- {total_completed} employees with training complete

BATCH DETAILS:
Batch-01-2026: {batches['Batch-01-2026']['total']} employees, {batches['Batch-01-2026']['attended_both']} attended both days, {batches['Batch-01-2026']['vl_completed']} VL completed, {batches['Batch-01-2026']['vl_in_progress']} in progress, {batches['Batch-01-2026']['vl_not_started']} not started, {batches['Batch-01-2026']['training_complete']} training complete, {batches['Batch-01-2026']['certs_issued']} certs issued
VL not started: {', '.join(batches['Batch-01-2026']['vl_not_started_names']) or 'none'}

Batch-02-2026: {batches['Batch-02-2026']['total']} employees, {batches['Batch-02-2026']['attended_both']} attended both days, {batches['Batch-02-2026']['vl_in_progress']} in progress, {batches['Batch-02-2026']['vl_not_started']} not started
VL not started: {', '.join(batches['Batch-02-2026']['vl_not_started_names']) or 'none'}

Batch-03-2026: {batches['Batch-03-2026']['total']} employees, {batches['Batch-03-2026']['attended_both']} attended both days, {batches['Batch-03-2026']['vl_in_progress']} in progress, {batches['Batch-03-2026']['vl_not_started']} not started

Batch-04-2026: {batches['Batch-04-2026']['total']} employees nominated, workshop 28-29 April 2026 (NOT YET HAPPENED)
DO NOT show attendance data for Batch 04 — workshop has not occurred yet

NOMINATIONS (Batch 04):
- {len(responded_hrbps)} of {len(all_hrbps)} HRBPs responded
- {total_nominees} total nominees
- Deadline: 7 April 2026
- Not responded: {', '.join(not_responded) if not_responded else 'all responded'}

SPECIAL CASES:
{chr(10).join(f"- {sc['hrbp']}: {sc['comment']}" for sc in special_cases) if special_cases else 'None'}
"""

    if vl_lookup:
        lines = ["VL PROGRESS (live from VL report — use for nudges and completion queries):"]
        lines.append("Emp ID | Name | Batch | VL Status | Completion % | Score")
        for emp in tracker:
            emp_id = emp.get("Emp ID", "").strip()
            batch  = emp.get("Batch", "").strip()
            if not emp_id or not batch.startswith("Batch-0") or emp_id not in vl_lookup:
                continue
            vl = vl_lookup[emp_id]
            lines.append(
                f"{emp_id} | {emp.get('Employee Name','').strip()} | {batch} | "
                f"{vl['status']} | {vl['pct']} | {vl['score']}"
            )
        text_summary += "\n" + "\n".join(lines) + "\n"

    if email_lookup:
        lines = ["EMPLOYEE EMAIL DIRECTORY (LDP participants — use exact addresses in email TO: fields):"]
        lines.append("Name | Email | Manager | Manager Email | HRBP | HRBP Email")
        for emp in tracker:
            name = emp.get("Employee Name", "").strip()
            if not name or name not in email_lookup:
                continue
            c = email_lookup[name]
            lines.append(
                f"{name} | {c['email']} | {c['manager_name']} | {c['manager_email']} | {c['hrbp_name']} | {c['hrbp_email']}"
            )
        text_summary += "\n" + "\n".join(lines) + "\n"

    return programme_data, text_summary


def ask_claude(user_message, history, text_summary):
    system_prompt = f"""You are the Learning Program Manager Agent for a Leadership Development Programme (LDP).
You have full visibility of the programme data provided below.

PROGRAMME DATA:
{text_summary}

CURRENT PRIORITIES (as of today):
1. URGENT: Send joining emails to all 26 Batch 04 participants — workshop is 28-29 April 2026 at Main Training Centre, Dubai, 9AM-5PM, Business Casual dress code.
2. Follow up on VL completion for Batch 01/02/03 non-completers.
3. NOMINATIONS ARE CLOSED — do not flag missing HRBP nominations as an action item. All 26 nominees are confirmed.

RESPONSE RULES — FOLLOW EXACTLY:
1. Be concise and direct. No padding or filler phrases.
2. Never use markdown tables (no | pipes |)
3. Never use --- dividers
4. Never use ### or #### headers
5. Never use ** bold markers — use plain text
6. Use ## only for section headers
7. Write in clean paragraphs and bullet points
8. For employee lists: "Name (Function, HRBP: X), Name (Function, HRBP: Y)"
9. No blank lines between bullet points
10. Maximum one blank line between sections
11. For Batch 04: NEVER mention attendance — workshop has not happened yet
12. If user has already acknowledged an issue, do not repeat it
13. Be smart — remember context from conversation history

For emails use this exact format:
---EMAIL---
TO: [actual email address from the directory — never use a name here]
SUBJECT: [subject]
BODY:
[email body — plain text only, no markdown]
---END---

When drafting emails, always look up the recipient's email address in the EMPLOYEE EMAIL DIRECTORY above.
For manager CC or HRBP CC, use their email addresses from the directory too."""

    messages = []
    for msg in history[:-1]:
        messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({
        "role": "user",
        "content": user_message
    })

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        system=system_prompt,
        messages=messages
    )

    return response.content[0].text


@app.route("/")
def index():
    response = make_response(render_template("chat.html"))
    response.headers["X-Frame-Options"] = "ALLOWALL"
    response.headers["Content-Security-Policy"] = "frame-ancestors *"
    return response


@app.route("/batch4_emails")
def batch4_emails():
    try:
        tracker      = read_tracker()
        email_lookup = build_email_lookup(read_employee_base())

        emails = []
        for emp in tracker:
            if emp.get("Batch", "").strip() != "Batch-04-2026":
                continue
            name     = emp.get("Employee Name", "").strip()
            to_email = email_lookup.get(name, {}).get("email", "")

            subject = "You've Been Selected for the Leadership Development Programme 2026"
            body = (
                f"Congratulations {name}!\n\n"
                "You have been selected for the Leadership Development Programme 2026. "
                "This is a fantastic opportunity and a recognition of your potential and leadership capability.\n\n"
                "Here are your programme details:\n\n"
                "Workshop Dates: 28-29 April 2026\n"
                "Location: Main Training Centre, Dubai\n"
                "Time: 9:00 AM - 5:00 PM (both days)\n"
                "Dress Code: Business Casual\n\n"
                "Following the workshop, you will also complete a series of virtual learning modules "
                "to reinforce and apply your learning.\n\n"
                "Add the dates to your calendar: https://www.google.com/calendar/render"
                "?action=TEMPLATE&text=LDP+Batch+04+Workshop"
                "&dates=20260428T090000/20260429T170000"
                "&location=Main+Training+Centre+Dubai"
                "&details=Leadership+Development+Programme+Workshop\n\n"
                "Please confirm your attendance by replying to this email.\n\n"
                "We look forward to seeing you there!\n\n"
                "Warm regards,\nLDP Programme Team"
            )
            emails.append({"name": name, "to": to_email, "subject": subject, "body": body})

        return jsonify({"emails": emails})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/programme_data")
def programme_data():
    try:
        tracker      = read_tracker()
        nominations  = read_nominations()
        email_lookup = build_email_lookup(read_employee_base())
        vl_lookup    = read_vl_data()
        data, _ = build_programme_data(tracker, nominations, email_lookup, vl_lookup)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/chat", methods=["POST"])
def chat():
    try:
        body = request.json
        user_message = body.get("message", "")
        history      = body.get("history", [])

        tracker      = read_tracker()
        nominations  = read_nominations()
        email_lookup = build_email_lookup(read_employee_base())
        vl_lookup    = read_vl_data()
        programme_data, text_summary = build_programme_data(tracker, nominations, email_lookup, vl_lookup)

        reply = ask_claude(user_message, history, text_summary)

        return jsonify({
            "reply": reply,
            "programme_data": programme_data
        })
    except Exception as e:
        return jsonify({"reply": f"Error: {str(e)}"}), 500


@app.route("/todays_actions")
def todays_actions():
    try:
        tracker      = read_tracker()
        nominations  = read_nominations()
        email_lookup = build_email_lookup(read_employee_base())
        vl_lookup    = read_vl_data()
        programme_data, text_summary = build_programme_data(tracker, nominations, email_lookup, vl_lookup)

        reply = ask_claude(
            "What are today's most urgent priority actions? Lead with sending joining emails to Batch 04 participants. Do not mention nominations. Be specific with names and numbers. Keep it brief.",
            [],
            text_summary
        )

        return jsonify({
            "actions": reply,
            "programme_data": programme_data
        })
    except Exception as e:
        return jsonify({"actions": f"Error: {str(e)}"}), 500


@app.after_request
def add_headers(response):
    response.headers.pop("X-Frame-Options", None)
    response.headers["Content-Security-Policy"] = "frame-ancestors *"
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


if __name__ == "__main__":
    app.run(debug=True)
