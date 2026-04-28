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

NOMINATIONS_SHEET_ID = "1Bc-eNUYt15SiDBUccajt0tlgeuCXOKkihb7Zb3UfKiM"
BATCH_DATE = "28-29 May 2026"
WORKSHOP_LOCATION = "Main Training Centre, Dubai"
WORKSHOP_TIME = "9:00 AM - 5:00 PM"
DRESS_CODE = "Business Casual"

def read_nominations():
    url = f"https://docs.google.com/spreadsheets/d/{NOMINATIONS_SHEET_ID}/gviz/tq?tqx=out:csv"
    response = urllib.request.urlopen(url)
    content = response.read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))
    return [row for row in reader]

def get_nominees(nominations):
    if not nominations:
        return []
    latest = nominations[-1]
    for key, value in latest.items():
        if "nominate" in key.lower() or "eligible" in key.lower():
            return [n.strip() for n in value.split(",")]
    return []

def draft_joining_email(participant_name):
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": f"""You are an HR professional sending a 
joining email to an employee who has been selected 
for the Leadership Development Programme.

Draft a warm, exciting and professional email 
informing them of their selection.

Details:
- Participant Name: {participant_name}
- Programme: Leadership Development Programme (LDP)
- Batch Dates: {BATCH_DATE}
- Location: {WORKSHOP_LOCATION}
- Time: {WORKSHOP_TIME} both days
- Dress Code: {DRESS_CODE}

The email must open with exactly these sentences:
"Congratulations {participant_name}! You have been selected for the Leadership Development Programme 2026. This is a fantastic opportunity and a recognition of your potential and leadership capability."

Then continue with:
- Programme details: {BATCH_DATE}, {WORKSHOP_LOCATION}, {WORKSHOP_TIME} both days
- Dress Code: {DRESS_CODE}
- Mention they will also complete virtual learning modules after the workshop
- Include this calendar link: https://www.google.com/calendar/render?action=TEMPLATE&text=LDP+Batch+04+Workshop&dates=20260528T090000/20260529T170000&location=Main+Training+Centre+Dubai&details=Leadership+Development+Programme+Workshop
- Ask them to confirm attendance by replying
- Sign off as: LDP Programme Team

Write in plain text only. Do not use ** for bold or any markdown formatting.
Write as a complete ready-to-send email with subject line."""
            }
        ]
    )
    return message.content[0].text

# Run it
print("="*60)
print("LDP AGENT 1 — JOINING EMAILS TO PARTICIPANTS")
print("="*60)

print("\nReading nominations...")
nominations = read_nominations()
nominees = get_nominees(nominations)

print(f"Drafting joining emails for {len(nominees)} participants\n")

for participant in nominees:
    print("="*60)
    print(f"EMAIL TO: {participant}")
    print("="*60)
    email = draft_joining_email(participant)
    print(email)
    print()
