import urllib.request
import csv
import io

NOMINATIONS_SHEET_ID = "1Bc-eNUYt15SiDBUccajt0tlgeuCXOKkihb7Zb3UfKiM"

def read_nominations():
    url = f"https://docs.google.com/spreadsheets/d/{NOMINATIONS_SHEET_ID}/gviz/tq?tqx=out:csv"
    response = urllib.request.urlopen(url)
    content = response.read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))
    rows = [row for row in reader]
    return rows

print("Reading nomination responses...")
nominations = read_nominations()
print(f"Found {len(nominations)} response(s)\n")

for nom in nominations:
    print("=" * 60)
    for key, value in nom.items():
        if value.strip():
            print(f"{key}: {value}")
    print("=" * 60)
