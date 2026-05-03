"""
Patch missing data from 'Data files/Ls/2025_missing_stats.xlsx' (Google Form responses).

Covers:
  - Lake Wylie   Jul 2025  → add gate, PC, WiFi, room use, take&makes, 1-on-1,
                              staff training hrs, all ONSITE programming sessions+attendance
  - Clover       Dec 2025  → add gate, PC, WiFi, room use, take&makes, 1-on-1,
                              staff trained+hrs, all ONSITE programming sessions+attendance
  - Bookmobile   Jul 2025  → fix m48 (Outreach Attendance) 246→1511 (data entry error:
                              was set to same value as take&makes instead of actual attendance)

Form column → DB metric mapping:
  Col  4 → m4  Gate Count
  Col  5 → m11 Curbside
  Col  7 → m5  PC Reservations
  Col  8 → m6  WiFi Unique Sessions
  Col  9 → m49 Take & Makes / Passive Participants
  Col 10 → m47 Outreach Activities
  Col 11 → m48 Outreach Attendance
  Col 12 → m7  External Party Room Use
  Col 13 → m52 1-on-1 Sessions
  Col 17 → m50 Staff Trained
  Col 18 → m51 Staff Training Hours
  Col 19 → m17 ONSITE Sess 0-5
  Col 20 → m18 ONSITE Sess 6-11
  Col 21 → m19 ONSITE Sess 12-18
  Col 22 → m20 ONSITE Sess 19+
  Col 23 → m21 ONSITE Sess General Interest
  Col 25 → m28 OFFSITE Sessions (total, stored in 6-11 bucket)
  Col 26 → m41 VIRTUAL Sessions (total, stored as GI)
  Col 27 → m22 ONSITE Att 0-5
  Col 28 → m23 ONSITE Att 6-11
  Col 29 → m24 ONSITE Att 12-18
  Col 30 → m25 ONSITE Att 19+
  Col 31 → m26 ONSITE Att General Interest
  Col 33 → m33 OFFSITE Attendance (total, stored in 6-11 bucket)
  Col 34 → m46 VIRTUAL Attendance (total, stored as GI)
  Col 99 → m8  Total Prints
"""

import os, sys
from dotenv import load_dotenv
load_dotenv()

import openpyxl
from flask import Flask
from models import db, Entry, EntryValue, Branch

app = Flask(__name__)
_db_url = os.environ.get('DATABASE_URL', 'sqlite:///librarystats.db')
if _db_url.startswith('postgres://'): _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

XLSX = 'Data files/Ls/2025_missing_stats.xlsx'
CATEGORY_ID = 1

# Form col → metric_id (skip derived totals: cols 24, 32)
COL_TO_METRIC = {
    4:  4,   # Gate Count
    5:  11,  # Curbside
    7:  5,   # PC Reservations
    8:  6,   # WiFi
    9:  49,  # Take & Makes
    10: 47,  # Outreach Activities
    11: 48,  # Outreach Attendance
    12: 7,   # External Party Room Use
    13: 52,  # 1-on-1
    17: 50,  # Staff Trained
    18: 51,  # Staff Training Hours
    19: 17,  # ONSITE Sess 0-5
    20: 18,  # ONSITE Sess 6-11
    21: 19,  # ONSITE Sess 12-18
    22: 20,  # ONSITE Sess 19+
    23: 21,  # ONSITE Sess GI
    25: 28,  # OFFSITE Sessions total
    26: 41,  # VIRTUAL Sessions total
    27: 22,  # ONSITE Att 0-5
    28: 23,  # ONSITE Att 6-11
    29: 24,  # ONSITE Att 12-18
    30: 25,  # ONSITE Att 19+
    31: 26,  # ONSITE Att GI
    33: 33,  # OFFSITE Attendance total
    34: 46,  # VIRTUAL Attendance total
    99: 8,   # Total Prints
}

# Do NOT overwrite these metrics if they already have a value in the DB
# (registration counts come from SIRSI and are more authoritative)
DO_NOT_OVERWRITE = {1, 2, 88, 9, 10, 11, 12}

BRANCH_NORM = {
    'Lake Wylie':           'Lake Wylie',
    'Bookmobile and Outreach': 'Bookmobile/Outreach',
    'Clover':               'Clover',
}

# (form_branch, form_month, db_year, db_month)
TARGETS = [
    ('Lake Wylie',              'July',     2025, 7),
    ('Clover',                  'December', 2025, 12),
    ('Bookmobile and Outreach', 'July',     2025, 7),
]

def load_form_data():
    wb = openpyxl.load_workbook(XLSX)
    ws = wb['Form Responses 1']
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    lookup = {}
    for row in rows:
        key = (row[3], row[2])  # (branch, month)
        if key not in lookup:
            lookup[key] = row
    return lookup

def upsert(entry_id, metric_id, value):
    ev = EntryValue.query.filter_by(entry_id=entry_id, metric_id=metric_id).first()
    if ev:
        ev.value_number = float(value)
    else:
        db.session.add(EntryValue(entry_id=entry_id, metric_id=metric_id, value_number=float(value)))

def main(dry_run=True):
    print(f"{'DRY RUN — ' if dry_run else ''}Patching from 2025_missing_stats.xlsx\n")
    form = load_form_data()

    with app.app_context():
        branches = {b.name: b.id for b in Branch.query.all()}

        for (form_branch, form_month, yr, mo) in TARGETS:
            db_branch = BRANCH_NORM[form_branch]
            bid = branches[db_branch]
            entry = Entry.query.filter_by(category_id=CATEGORY_ID, branch_id=bid, year=yr, month=mo).first()
            if not entry:
                print(f"  SKIP {db_branch} {yr}-{mo:02d}: no DB entry"); continue

            existing = {ev.metric_id: ev.value_number
                        for ev in EntryValue.query.filter_by(entry_id=entry.id).all()}

            row = form.get((form_branch, form_month))
            if not row:
                print(f"  SKIP {db_branch} {yr}-{mo:02d}: not in form file"); continue

            # Special case: Bookmobile Jul 2025 — only fix the outreach attendance error
            if form_branch == 'Bookmobile and Outreach':
                old_val = existing.get(48)
                new_val = row[11]  # col 11 = Outreach Attendance
                print(f"  FIX {db_branch} {yr}-{mo:02d} (entry {entry.id}): "
                      f"m48 Outreach Attendance {old_val:.0f} → {new_val:.0f}")
                if not dry_run:
                    upsert(entry.id, 48, new_val)
                    db.session.commit()
                    print(f"    → committed")
                continue

            # For other branches: upsert all form values that are non-null and non-zero,
            # skipping metrics that already have values and are in DO_NOT_OVERWRITE
            to_write = {}
            skipped = {}
            for col, mid in COL_TO_METRIC.items():
                val = row[col] if col < len(row) else None
                if val is None or val == 0:
                    continue
                if mid in DO_NOT_OVERWRITE and mid in existing and existing[mid]:
                    skipped[mid] = (existing[mid], val)
                    continue
                to_write[mid] = val

            sess = sum(to_write.get(m, 0) for m in [17,18,19,20,21,28,41])
            att  = sum(to_write.get(m, 0) for m in [22,23,24,25,26,33,46])
            print(f"  PATCH {db_branch} {yr}-{mo:02d} (entry {entry.id}): "
                  f"{len(to_write)} values, {sess:.0f} prog sessions, {att:.0f} attendance")
            for mid, val in sorted(to_write.items()):
                print(f"    m{mid}: {val:.0f}")
            if skipped:
                print(f"    Skipped (already set): " +
                      ", ".join(f"m{m}=db:{dv:.0f}/form:{fv:.0f}" for m,(dv,fv) in sorted(skipped.items())))

            if not dry_run:
                for mid, val in to_write.items():
                    upsert(entry.id, mid, val)
                db.session.commit()
                print(f"    → committed")

    suffix = "\nDry run complete. Run with --apply to write." if dry_run else "\nDone."
    print(suffix)

if __name__ == '__main__':
    main(dry_run='--apply' not in sys.argv)
