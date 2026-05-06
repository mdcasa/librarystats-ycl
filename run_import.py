import sys
from dotenv import load_dotenv
load_dotenv()

import openpyxl
from app import app, db
from import_excel import import_branch_stats, build_metric_lookup, build_branch_lookup

path = sys.argv[1]
wb = openpyxl.load_workbook(path, data_only=True)

with app.app_context():
    metrics, cat = build_metric_lookup('Branch Stats')
    if not cat:
        print("ERROR: Branch Stats category not found in DB")
        sys.exit(1)
    branch_lookup = build_branch_lookup()

    ws = wb.worksheets[0]
    created, updated, periods, warnings = import_branch_stats(ws, cat, metrics, branch_lookup)

    print(f"\nBranch Stats import complete:")
    print(f"  Created: {created}, Updated: {updated}")
    print(f"  Periods: {sorted(periods)}")
    for w in warnings:
        print(f"  WARNING: {w}")
print("\nDone.")
