import anthropic
from dotenv import load_dotenv
import os
import urllib.request
import csv
import io

load_dotenv()

client = anthropic.Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY")
)

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
    encoded = "LDP%20Tracker"
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={encoded}"
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

def build_programme_summary(tracker, nominations):
    
    batches = {}
    vl_details = {}
    attendance_details = {}

    for emp in tracker:
        batch = emp.get('Batch', '').strip()
        if not batch or batch == '':
            batch = 'TBD'
        if batch not in batches:
            batches[batch] = {
                'total': 0,
                'confirmed': 0,
                'attended_both': 0,
                'vl_completed': 0,
                'vl_in_progress': 0,
                'vl_not_started': 0,
                'training_complete': 0,
                'certs_issued': 0,
            }
            vl_details[batch] = {
                'completed': [],
                'in_progress': [],
                'not_started': [],
            }
            attendance_details[batch] = {
                'attended_both': [],
                'absent': [],
                'partial': [],
            }

        b = batches[batch]
        name = emp.get('Employee Name','').strip()
        hrbp = emp.get('HRBP Name','').strip()
        fn   = emp.get('Function','').strip()
        vl_pct = emp.get('VL Completion %','').strip()
        mgr  = emp.get('Manager Name','').strip()

        b['total'] += 1

        if emp.get('Nomination Status','').strip() == 'Confirmed':
            b['confirmed'] += 1

        d1 = emp.get('Day 1 Attendance','').strip()
        d2 = emp.get('Day 2 Attendance','').strip()

        if d1 == 'Attended' and d2 == 'Attended':
            b['attended_both'] += 1
            attendance_details[batch]['attended_both'].append(name)
        elif d1 == 'Absent' and d2 == 'Absent':
            attendance_details[batch]['absent'].append(
                f"{name} (HRBP: {hrbp}, Manager: {mgr})"
            )
        elif d1 == 'Attended' or d2 == 'Attended':
            attendance_details[batch]['partial'].append(
                f"{name} (HRBP: {hrbp}, Manager: {mgr})"
            )

        vl = emp.get('VL Status','').strip()
        if vl == 'Completed':
            b['vl_completed'] += 1
            vl_details[batch]['completed'].append(name)
        elif vl == 'In Progress':
            b['vl_in_progress'] += 1
            vl_details[batch]['in_progress'].append(
                f"{name} ({vl_pct} complete, {fn})"
            )
        elif vl == 'Not Started':
            b['vl_not_started'] += 1
            vl_details[batch]['not_started'].append(
                f"{name} (HRBP: {hrbp}, {fn})"
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
            hrbp_responses[hrbp] = {
                'nominees': nominees,
                'comments': comments
            }
            all_nominees.extend(nominees)
            if comments:
                special_cases.append(f"{hrbp}: {comments}")

    summary = f"""
TODAY'S DATE: 2 April 2026

BATCH STATUS:
"""
    for batch_name in ['Batch-01-2026','Batch-02-2026',
                       'Batch-03-2026','Batch-04-2026','TBD']:
        if batch_name not in batches:
            continue
        b = batches[batch_name]
        vl = vl_details.get(batch_name, {})
        att = attendance_details.get(batch_name, {})

        if batch_name == 'TBD':
            summary += f"\nAwaiting future batches: {b['total']} employees\n"
            continue

        summary += f"""
{batch_name}:
  Confirmed nominations: {b['confirmed']}
  Attended both days: {b['attended_both']}
  Absent both days: {len(att.get('absent',[]))}
  Partial attendance: {len(att.get('partial',[]))}
  VL Completed: {b['vl_completed']}
  VL In Progress: {b['vl_in_progress']}
  VL Not Started: {b['vl_not_started']}
  Training Complete: {b['training_complete']}
  Certificates Issued: {b['certs_issued']}
"""
        if att.get('absent'):
            summary += f"  Absent employees: {', '.join(att['absent'])}\n"
        if att.get('partial'):
            summary += f"  Partial attendance: {', '.join(att['partial'])}\n"
        if vl.get('not_started'):
            summary += f"  VL not started: {', '.join(vl['not_started'])}\n"
        if vl.get('in_progress'):
            summary += f"  VL in progress: {', '.join(vl['in_progress'])}\n"
        if vl.get('completed'):
            summary += f"  VL completed: {', '.join(vl['completed'])}\n"


    summary += f"""
BATCH 04 NOMINATIONS:
  Total HRBPs: 19
  HRBPs responded: {len(hrbp_responses)}
  HRBPs not yet responded: {19 - len(hrbp_responses)}
  Total nominees so far: {len(all_nominees)}
  Nomination deadline: 7 April 2026

HRBP RESPONSES:
"""
    for hrbp, data in hrbp_responses.items():
        summary += f"  {hrbp}: nominated {len(data['nominees'])} — {', '.join(data['nominees'])}\n"
        if data['comments']:
            summary += f"    Special case: {data['comments']}\n"

    summary += f"""
HRBPs NOT YET RESPONDED:
"""
    all_hrbps = [
        "Aisha Walker", "Aparna Johnson", "Ishaan Farouk",
        "Mariam Lee", "Meghna Iqbal", "Nawaf Bhat",
        "Pranav Young", "Ryan Venkataraman", "Saif Sivasubramanian",
        "Salman Varma", "Thomas Subramaniam", "Yusuf Jackson",
        "Daniel Smith", "Maria Verma", "Hamdan Malik",
        "Thomas Varma", "Stanley Al-Dhaheri", "Anita Al-Farsi",
        "Varun Al-Farsi"
    ]
    responded = list(hrbp_responses.keys())
    not_responded = [h for h in all_hrbps if h not in responded]
    for h in not_responded:
        summary += f"  - {h}\n"

    if special_cases:
        summary += f"\nSPECIAL CASES FLAGGED BY HRBPs:\n"
        for case in special_cases:
            summary += f"  • {case}\n"

    return summary

def ask_supervisor(question, programme_summary):
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": f"""You are the LDP Programme Supervisor Agent.
You have full visibility of the Leadership Development
Programme across all batches.

Here is the current programme data:
{programme_summary}

Answer the following question from the HR Manager
clearly and helpfully. Be specific with numbers.
Use a clean structured format.
Highlight anything that needs attention or action.
If something needs to be done urgently flag it clearly.

Question: {question}"""
            }
        ]
    )
    return message.content[0].text

print("="*60)
print("LDP PROGRAMME SUPERVISOR")
print("Type your question. Type 'exit' to quit.")
print("="*60)
print("\nSupervisor ready. Data reloads with every question.\n")

while True:
    print("-"*60)
    question = input("You: ").strip()

    if question.lower() in ('exit', 'quit', 'bye'):
        print("\nSupervisor: Goodbye!")
        break

    if not question:
        continue

    print("\nReloading latest data...")
    tracker = read_ldp_tracker()
    nominations = read_nominations()
    summary = build_programme_summary(tracker, nominations)

    print("Supervisor: thinking...\n")
    response = ask_supervisor(question, summary)
    print(f"Supervisor: {response}\n")
