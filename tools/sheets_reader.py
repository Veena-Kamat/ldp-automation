import urllib.request
import csv
import io

SHEET_ID = "1bqTrb4oR8OCdv_jXrzOXXmSGt0jptX7j"

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

def read_sheet(sheet_name):
    encoded_name = sheet_name.replace(" ", "%20").replace("—", "%E2%80%94")
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={encoded_name}"
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

print("Reading LDP Tracker...")
rows = read_sheet("LDP Tracker")
print(f"Total employees: {len(rows)}")

print("\nFirst 3 employees:")
for emp in rows[:3]:
    print(f"  {emp.get('Employee Name','N/A')} | "
          f"Batch: {emp.get('Batch','N/A')} | "
          f"HRBP: {emp.get('HRBP Name','N/A')} | "
          f"Status: {emp.get('Nomination Status','N/A')}")

print("\nTBD employees (not yet batched):")
tbd = [r for r in rows if r.get('Batch','').strip() == 'TBD']
print(f"  Found {len(tbd)} employees waiting for a batch")

if tbd:
    print("\nFirst 3 TBD employees:")
    for emp in tbd[:3]:
        print(f"  {emp.get('Employee Name','N/A')} | "
              f"HRBP: {emp.get('HRBP Name','N/A')} | "
              f"Function: {emp.get('Function','N/A')}")

print("\nCleaned column names:")
print(list(rows[0].keys()))
