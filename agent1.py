import anthropic
from dotenv import load_dotenv
import os
from sheets import read_sheet, SECTION_LABELS, clean_header

load_dotenv()

client = anthropic.Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY")
)

BATCH_DATE = "28-29 April 2026"
NOMINATION_DEADLINE = "7 April 2026"

def get_tbd_employees(rows):
    tbd = [r for r in rows if r.get('Batch','').strip() == 'TBD']
    return tbd

def group_by_hrbp(employees):
    grouped = {}
    for emp in employees:
        hrbp = emp.get('HRBP Name', 'Unknown').strip()
        if hrbp not in grouped:
            grouped[hrbp] = []
        grouped[hrbp].append(emp)
    return grouped

def draft_nomination_email(hrbp_name, employees):
    employee_list = ""
    for i, emp in enumerate(employees, 1):
        employee_list += (
            f"{i}. {emp.get('Employee Name','N/A')} — "
            f"{emp.get('Sub-Function','N/A')}, "
            f"{emp.get('Function','N/A')} "
            f"(Promoted to Grade I: {emp.get('Promo Date (to Grade I)','N/A')})\n"
        )

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": f"""You are an HR professional sending a nomination 
request email to an HRBP for the Leadership Development Programme.

Draft a professional, warm and concise email with these details:
- HRBP Name: {hrbp_name}
- Batch Dates: {BATCH_DATE}
- Nomination Deadline: {NOMINATION_DEADLINE}
- Number of eligible employees: {len(employees)}

Eligible employees (promoted from Grade J to I in 2025, 
have direct reports — hence eligible for LDP):
{employee_list}

The email should:
- Open warmly addressing {hrbp_name} by first name
- Briefly explain these employees are eligible because 
  they were promoted to Grade I in 2025 and have reportees
- List the employees clearly
- Ask the HRBP to confirm nominations by the deadline
- Mention batch capacity is 25-30 employees
- Be concise — HRBPs are busy
- Sign off as: LDP Programme Team

Do not add any placeholder text like [Your Name].
Write it as a complete ready-to-send email."""
            }
        ]
    )
    return message.content[0].text

def run_nominations():
    print("=" * 60)
    print("LDP AGENT 1 — NOMINATIONS")
    print(f"Batch: {BATCH_DATE}")
    print("=" * 60)

    print("\nReading LDP Tracker...")
    rows = read_sheet("LDP Tracker")

    tbd = get_tbd_employees(rows)
    print(f"Found {len(tbd)} employees not yet batched")

    grouped = group_by_hrbp(tbd)
    print(f"Across {len(grouped)} HRBPs")
    print("\nDrafting nomination emails...\n")

    for hrbp_name, employees in grouped.items():
        print("=" * 60)
        print(f"TO: {hrbp_name} ({len(employees)} eligible employees)")
        print("=" * 60)
        email = draft_nomination_email(hrbp_name, employees)
        print(email)
        print()

    print("=" * 60)
    print(f"Done. {len(grouped)} emails drafted.")
    print("=" * 60)

run_nominations()
