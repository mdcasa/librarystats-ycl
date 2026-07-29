"""
Loader for the Cisco Meraki WiFi "Summary Report" exports (one workbook per
branch). Reads every .xlsx in a folder and upserts each branch's "Total Unique
Clients" into the Branch Stats "WiFi - Unique Sessions" metric — the automated
replacement for the figure that used to be entered by hand.

Reuses import_meraki_wifi via detect_and_import, so this behaves exactly like
uploading each file through the web Upload page (idempotent upsert; re-running
is a no-op). Branch and month are read from each file name.

    python load_wifi.py                       # defaults to Data files/June/wifi
    python load_wifi.py "Data files/June/wifi"

IMPORTANT: honours DATABASE_URL from .env (Supabase), like every other one-time
load in this project. Omit DATABASE_URL to write to the local SQLite DB instead.
"""

import glob
import os
import sys

from dotenv import load_dotenv
load_dotenv()

import openpyxl
from app import app
from import_excel import detect_and_import


def run(folder):
    paths = sorted(glob.glob(os.path.join(folder, '*.xlsx')))
    if not paths:
        print(f'No .xlsx files found in {folder}')
        return

    total_created = total_updated = 0
    with app.app_context():
        for path in paths:
            fname = os.path.basename(path)
            wb = openpyxl.load_workbook(path, data_only=True)
            results = detect_and_import(wb, filename=fname)
            for r in results:
                c, u = r.get('created', 0), r.get('updated', 0)
                total_created += c
                total_updated += u
                note = r.get('note', '')
                print(f"{fname}\n  {r['sheet']}: {c} created, {u} updated"
                      + (f'  — {note}' if note else ''))
                for w in r.get('warnings', []):
                    print(f'    Warning: {w}')

    print(f'\nDone! {total_created} created, {total_updated} updated across {len(paths)} file(s).')


if __name__ == '__main__':
    folder = sys.argv[1] if len(sys.argv) > 1 else os.path.join('Data files', 'June', 'wifi')
    run(folder)
