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

# Hardcoded for demo
HRBP_NAME = "Meghna Iqbal"
BATCH_DATE = "28-29 April 2026"
WORKSHOP_LOCATION = "Main Training Centre, Dubai"

def read_nominations():
    url = f"https://docs.google.com/spreadsheets/d/{NOMINATIONS_SHEET_ID}/gviz/tq?tqx=out:csv"
    response = urllib.request.urlopen(url)
    content = response.read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))
    rows = [row for row in reader]
    return rows

def get_nominees(nominations):
    if not nominations:
        return []
    latest = nominations[-1]
    for key, value in latest.items():
        if "nominate" in key.lower() or "eligible" in key.lower():
            nominees = [n.strip() for n in value.split(",")]
            return nominees
    return []

def draft_confirmation_email(hrbp_name, nominees):
    nominee_list = ""
    for i, name in enumerate(nominees, 1):
        nominee_list += f"{i}. {name}\n"

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": f"""You are an HR professional sending a 
nomination confirmation email to an HRBP.

Draft a warm, professional and concise email confirming 
we are going ahead with their nominations for the 
Leadership Development Programme.

Details:
- HRBP Name: {hrbp_name}
- Batch Dates: {BATCH_DATE}
- Location: {WORKSHOP_LOCATION}
- Confirmed nominees:
{nominee_list}

The email should:
- Thank the HRBP by first name for their nominations
- Confirm we are going ahead with these specific employees
- Mention the batch dates and location
- Tell them the participants will receive a 
  joining email shortly with programme details
- Ask them to let us know if anything changes
- Be warm but brief
- Sign off as: LDP Programme Team

Write it as a complete ready to send email
with subject line."""
            }
        ]
    )
    return message.content[0].text

# Run it
print("="*60)
print("LDP AGENT 1 — NOMINATION CONFIRMATION")
print("="*60)

print("\nReading nomination responses...")
nominations = read_nominations()
print(f"Found {len(nominations)} response(s)")

nominees = get_nominees(nominations)
print(f"\nNominees from {HRBP_NAME}:")
for n in nominees:
    print(f"  • {n}")

print(f"\nDrafting confirmation email to {HRBP_NAME}...")
email = draft_confirmation_email(HRBP_NAME, nominees)

print("\n" + "="*60)
print(f"CONFIRMATION EMAIL TO: {HRBP_NAME}")
print("="*60)
print(email)
print("="*60)
