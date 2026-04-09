import anthropic
from dotenv import load_dotenv
import os
import urllib.request
import csv
import io
from datetime import date

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

LDP_TRACKER_ID = "1z0-TFgYUmftZglGwGlaDbkgEM3k8VfaIOm4Rl8RmFow"
BATCH_NAME     = "Batch-04-2026"
WORKSHOP_D1    = "28 April 2026 (Tuesday)"
WORKSHOP_D2    = "29 April 2026 (Wednesday)"
TIME           = "9:00 AM — 5:00 PM"
LOCATION       = "Main Training Centre, Dubai"
FLOOR          = "3rd Floor, Training Room B"
PARKING        = "Visitor parking available in basement"
DRESS_CODE     = "Business Casual"
CALENDAR_LINK  = "https://www.google.com/calendar/render?action=TEMPLATE&text=LDP+Batch+04+Workshop&dates=20260428T090000/20260429T170000&location=Main+Training+Centre+Dubai&details=Leadership+Development+Programme+Workshop"
TODAY          = date.today().strftime("%d-%b-%Y")

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

def read_confirmed_participants():
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
    confirmed = [
        r for r in data
        if r.get("Batch","").strip() == BATCH_NAME
        and r.get("Nomination Status","").strip() == "Nominated"
    ]
    return confirmed

def draft_reminder_email(participant_name):
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        messages=[{
            "role": "user",
            "content": f"""Draft a warm friendly day-before reminder email 
for an LDP workshop participant.

Details:
- Participant: {participant_name}
- Workshop Day 1: {WORKSHOP_D1}
- Workshop Day 2: {WORKSHOP_D2}
- Time: {TIME} both days
- Location: {LOCATION}
- Floor/Room: {FLOOR}
- Parking: {PARKING}
- Dress Code: {DRESS_CODE}
- Calendar Link: {CALENDAR_LINK}

The email should:
- Be short and warm — this is a reminder not a novel
- Restate the key logistics clearly
- Include the calendar link
- Mention what to bring: notebook, pen, open mind
- Express excitement about seeing them tomorrow
- Sign off as: LDP Programme Team

Write as complete ready to send email with subject line."""
        }]
    )
    return message.content[0].text

def run_agent2_preworkshop():
    print("\n" + "="*60)
    print("AGENT 2 — PRE-WORKSHOP REMINDER")
    print(f"Batch: {BATCH_NAME}")
    print(f"Workshop: {WORKSHOP_D1} & {WORKSHOP_D2}")
    print(f"Running: {TODAY}")
    print("="*60)

    print("\n[Step 1] Reading confirmed participants...")
    participants = read_confirmed_participants()
    print(f"Found {len(participants)} confirmed participants for {BATCH_NAME}")

    print(f"\n[Step 2] Drafting day-before reminders...")
    print(f"Showing first 3 of {len(participants)}:\n")

    for emp in participants[:3]:
        name = emp.get("Employee Name","").strip()
        print("="*60)
        print(f"TO: {name}")
        print("="*60)
        email = draft_reminder_email(name)
        print(email)
        print()

    print("="*60)
    print(f"AGENT 2 PRE-WORKSHOP COMPLETE")
    print(f"Reminder emails drafted: {len(participants)}")
    print(f"(Showing 3 of {len(participants)} — all drafted in real run)")
    print("="*60)


if __name__ == "__main__":
    run_agent2_preworkshop()
