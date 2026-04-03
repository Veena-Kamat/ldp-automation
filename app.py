from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
import anthropic
import urllib.request
import csv
import io
import os

load_dotenv()

app = Flask(__name__)
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

SHEET_ID = "1bqTrb4oR8OCdv_jXrzOXXmSGt0jptX7j"
NOMINATIONS_SHEET_ID = "1Bc-eNUYt15SiDBUccajt0tlgeuCXOKkihb7Zb3UfKiM"

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
    return data

def read_nominations():
    url = f"https://docs.google.com/spreadsheets/d/{NOMINATIONS_SHEET_ID}/gviz/tq?tqx=out:csv&gid=1000019961"
    response = urllib.request.urlopen(url)
    content = response.read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))
    return [row for row in reader]

def build_summary(tracker, nominations):
    batches = {}
    vl_not_started = {}
    absent_employees = {}

    for emp in tracker:
        batch = emp.get('Batch','').strip() or 'TBD'
        if batch not in batches:
            batches[batch] = {
                'total':0,'confirmed':0,'attended_both':0,
                'vl_completed':0,'vl_in_progress':0,
                'vl_not_started':0,'training_complete':0,'certs_issued':0
            }
            vl_not_started[batch] = []
            absent_employees[batch] = []

        b = batches[batch]
        name = emp.get('Employee Name','').strip()
        hrbp = emp.get('HRBP Name','').strip()
        fn   = emp.get('Function','').strip()
        mgr  = emp.get('Manager Name','').strip()
        vl_pct = emp.get('VL Completion %','').strip()

        b['total'] += 1
        if emp.get('Nomination Status','').strip() == 'Confirmed':
            b['confirmed'] += 1

        d1 = emp.get('Day 1 Attendance','').strip()
        d2 = emp.get('Day 2 Attendance','').strip()
        if d1 == 'Attended' and d2 == 'Attended':
            b['attended_both'] += 1
        elif d1 == 'Absent' or d2 == 'Absent':
            absent_employees[batch].append(
                f"{name} (HRBP: {hrbp}, Manager: {mgr})"
            )

        vl = emp.get('VL Status','').strip()
        if vl == 'Completed':
            b['vl_completed'] += 1
        elif vl == 'In Progress':
            b['vl_in_progress'] += 1
        elif vl == 'Not Started':
            b['vl_not_started'] += 1
            vl_not_started[batch].append(
                f"{name} ({fn}, HRBP: {hrbp})"
            )

        if emp.get('Training Complete','').strip() == 'Yes':
            b['training_complete'] += 1
        if emp.get('Certificate Issued Date','').strip() not in ('','—'):
            b['certs_issued'] += 1

    hrbp_responses = {}
    all_nominees = []
    special_cases = []

    for nom in nominations:
        hrbp = ""
        nominees = []
        comments = ""
        for key, value in nom.items():
            if "name" in key.lower():
                hrbp = value.strip()
            if "nominate" in key.lower() or "eligible" in key.lower():
                nominees = [n.strip() for n in value.split(",") if n.strip()]
            if "comment" in key.lower() or "special" in key.lower():
                comments = value.strip()
        if hrbp:
            hrbp_responses[hrbp] = {'nominees': nominees, 'comments': comments}
            all_nominees.extend(nominees)
            if comments:
                special_cases.append(f"{hrbp}: {comments}")

    all_hrbps = [
        "Aisha Walker","Aparna Johnson","Ishaan Farouk",
        "Mariam Lee","Meghna Iqbal","Nawaf Bhat",
        "Pranav Young","Ryan Venkataraman","Saif Sivasubramanian",
        "Salman Varma","Thomas Subramaniam","Yusuf Jackson",
        "Daniel Smith","Maria Verma","Hamdan Malik",
        "Thomas Varma","Stanley Al-Dhaheri","Anita Al-Farsi",
        "Varun Al-Farsi"
    ]
    not_responded = [h for h in all_hrbps if h not in hrbp_responses]

    summary = f"""
TODAY: 2 April 2026

BATCH STATUS:
"""
    for bn in ['Batch-01-2026','Batch-02-2026','Batch-03-2026','Batch-04-2026','TBD']:
        if bn not in batches:
            continue
        b = batches[bn]
        if bn == 'TBD':
            summary += f"\nAwaiting future batches: {b['total']} employees\n"
            continue
        summary += f"""
{bn}:
  Confirmed: {b['confirmed']}
  Attended both days: {b['attended_both']}
  VL Completed: {b['vl_completed']}
  VL In Progress: {b['vl_in_progress']}
  VL Not Started: {b['vl_not_started']}
  Training Complete: {b['training_complete']}
  Certs Issued: {b['certs_issued']}
"""
        if vl_not_started.get(bn):
            summary += f"  VL not started names: {', '.join(vl_not_started[bn])}\n"
        if absent_employees.get(bn):
            summary += f"  Absent employees: {', '.join(absent_employees[bn])}\n"

    summary += f"""
BATCH 04 NOMINATIONS:
  HRBPs responded: {len(hrbp_responses)} of 19
  Not responded: {', '.join(not_responded)}
  Total nominees: {len(all_nominees)}
  Deadline: 7 April 2026
"""
    for hrbp, data in hrbp_responses.items():
        summary += f"  {hrbp}: {', '.join(data['nominees'])}\n"
        if data['comments']:
            summary += f"    Note: {data['comments']}\n"

    if special_cases:
        summary += "\nSPECIAL CASES:\n"
        for case in special_cases:
            summary += f"  {case}\n"

    return summary

def get_gmail_link(to, subject, body):
    import urllib.parse
    params = urllib.parse.urlencode({
        'to': to,
        'su': subject,
        'body': body
    })
    return f"https://mail.google.com/mail/?view=cm&fs=1&{params}"

@app.route('/')
def index():
    return render_template('chat.html')

@app.route('/chat', methods=['POST'])
def chat():
    user_message = request.json.get('message', '')

    tracker = read_ldp_tracker()
    nominations = read_nominations()
    summary = build_summary(tracker, nominations)

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": f"""You are the LDP Programme Supervisor Agent.
You have full visibility of the Leadership Development Programme.

Current programme data:
{summary}

Answer the HR Manager's question clearly and helpfully.
Use structured formatting with headers and bullet points.
Flag urgent items clearly.


If asked to draft emails, format EACH email exactly like this:
---EMAIL---
TO: [name]
SUBJECT: [subject line]
BODY:
[full email body here]
---END---


Question: {user_message}"""
        }]
    )

    reply = response.content[0].text
    return jsonify({'reply': reply})

if __name__ == '__main__':
    app.run(debug=True)
