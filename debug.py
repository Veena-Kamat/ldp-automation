import urllib.request
import csv
import io

SHEET_ID = "1bqTrb4oR8OCdv_jXrzOXXmSGt0jptX7j"

encoded_name = "LDP%20Tracker"
url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={encoded_name}"
response = urllib.request.urlopen(url)
content = response.read().decode("utf-8")
reader = csv.reader(io.StringIO(content))
all_rows = list(reader)

print("Row 0:", all_rows[0][:5])
print("Row 1:", all_rows[1][:5])
print("Row 2:", all_rows[2][:5])
print("Row 3:", all_rows[3][:5])
