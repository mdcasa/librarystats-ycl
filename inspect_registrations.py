"""Show every patron type and count from a New Library Users SIRSI report."""
import sys
from dotenv import load_dotenv
load_dotenv()

import openpyxl
from collections import defaultdict

path = sys.argv[1]
wb = openpyxl.load_workbook(path, data_only=True)
ws = wb.worksheets[0]
rows = list(ws.iter_rows(values_only=True))

_ADULT    = {'ADULT', 'A-NONRES', 'INST-TEACH', 'TEEN', 'COLLEGE', 'HOMEBOUND'}
_JUVENILE = {'JUVENILE', 'J-INTERNET', 'J-RESTRICT', 'JR-NONRES'}

profile_totals = defaultdict(int)
unclassified   = defaultdict(int)

for r in rows:
    user_lib = r[1]
    profile  = r[2]
    count    = r[3]
    if not isinstance(count, (int, float)):
        continue
    if profile in (None, 'Total', 'Trans Stat User Profile Name'):
        continue
    if user_lib in (None, 'Total', 'Trans Stat User Library'):
        continue
    if not str(user_lib).strip().startswith('YCL-'):
        continue

    p = str(profile).strip()
    profile_totals[p] += int(count)
    if p not in _ADULT and p not in _JUVENILE:
        unclassified[p] += int(count)

print("All patron types and system-wide totals:")
print(f"{'Profile':<20} {'Count':>6}  {'Bucket'}")
print("-" * 45)
adult_total = juvenile_total = unclass_total = 0
for p, n in sorted(profile_totals.items(), key=lambda x: -x[1]):
    if p in _ADULT:
        bucket = 'ADULT'
        adult_total += n
    elif p in _JUVENILE:
        bucket = 'JUVENILE'
        juvenile_total += n
    else:
        bucket = '*** UNCLASSIFIED ***'
        unclass_total += n
    print(f"{p:<20} {n:>6}  {bucket}")

print("-" * 45)
print(f"{'ADULT total':<20} {adult_total:>6}")
print(f"{'JUVENILE total':<20} {juvenile_total:>6}")
if unclass_total:
    print(f"{'UNCLASSIFIED total':<20} {unclass_total:>6}  ← these are silently skipped")
print(f"{'Grand total':<20} {adult_total + juvenile_total + unclass_total:>6}")
