"""
One-time load of public fax history (Apr 2025 – Sep 2026) from the FaxScan24
tracking workbook into the Faxing category: one entry per branch per month
with prepaid/credit-debit card transactions, credit card sales and commission.

Reuses import_fax_activity via detect_and_import, so this behaves exactly like
uploading the workbook through the web Upload page (idempotent upsert;
re-running is a no-op). Only the "Monthly Data" sheet is read — the other
sheets are formulas built from it.

    python load_fax.py               # load "Data files/Faxing/Faxing Statistics Apr 2025 - Sep 2026.xlsx"
    python load_fax.py path/to/workbook.xlsx

IMPORTANT: honours DATABASE_URL from .env (Supabase), like every other one-time
load in this project. Omit DATABASE_URL to write to the local SQLite DB instead.
"""

import os
import sys

import openpyxl
from app import app, db
from models import Category, Entry, FAX_CATEGORY
from import_excel import detect_and_import

DEFAULT_PATH = os.path.join('Data files', 'Faxing', 'Faxing Statistics Apr 2025 - Sep 2026.xlsx')


def run(path):
    with app.app_context():
        print(f'Database: {db.engine.url.render_as_string(hide_password=True)}')
        cat = Category.query.filter_by(name=FAX_CATEGORY).first()
        before = Entry.query.filter_by(category_id=cat.id).count() if cat else 0
        print(f'{FAX_CATEGORY} entries before: {before}')

        wb = openpyxl.load_workbook(path, data_only=True)
        results = detect_and_import(wb, filename=os.path.basename(path))
        for r in results:
            note = r.get('note', '')
            print(f"{r['sheet']}: {r.get('created', 0)} values created, "
                  f"{r.get('updated', 0)} updated" + (f'  — {note}' if note else ''))
            for w in r.get('warnings', []):
                print(f'  Warning: {w}')

        after = Entry.query.filter_by(category_id=cat.id).count() if cat else 0
        print(f'{FAX_CATEGORY} entries after: {after}')


if __name__ == '__main__':
    run(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PATH)
