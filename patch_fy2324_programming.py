"""
Patch FY2023-24 programming data from '23-24 Annual Stats.xls'.

Source: 'Program Comparison p.5' sheet.

Convention (same as FY22-23 and FY24-25 patch scripts):
  Synchronus Age X Sessions   → ONSITE Sessions by age (metrics 17-21)
  S. In-Person Offsite total  → OFFSITE Sessions 6-11 (metric 28)
  S. Virtual total            → VIRTUAL Sessions General Interest (metric 41)
  Age X Attendance            → ONSITE Attendance by age (metrics 22-26)
  S. In-Person Offsite Att.   → OFFSITE Attendance 6-11 (metric 33)
  S. Virtual Attendance       → VIRTUAL Attendance General Interest (metric 46)

Skips any branch/month that already has non-zero programming data (safe to re-run).
Jul-Dec 2023 entries exist in DB with zeros; Jan-Jun 2024 already has data and will
be skipped by the guard.
"""

import os, sys
from dotenv import load_dotenv
load_dotenv()

import xlrd
from flask import Flask
from models import db, Entry, EntryValue, Branch

app = Flask(__name__)
_db_url = os.environ.get('DATABASE_URL', 'sqlite:///librarystats.db')
if _db_url.startswith('postgres://'):
    _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

XLS = 'Data files/Ls/23-24 Annual Stats.xls'
CATEGORY_ID = 1  # Branch Stats

# Column index (0-based) → calendar month/year for FY July 2023 – June 2024
COL_TO_MONTH = {3:7, 4:8, 5:9, 6:10, 7:11, 8:12, 9:1, 10:2, 11:3, 12:4, 13:5, 14:6}
COL_TO_YEAR  = {3:2023, 4:2023, 5:2023, 6:2023, 7:2023, 8:2023,
                9:2024, 10:2024, 11:2024, 12:2024, 13:2024, 14:2024}

BRANCH_ORDER = ['Rock Hill', 'Clover', 'Fort Mill', 'Lake Wylie', 'York', 'Bookmobile']

BRANCH_NAME_MAP = {
    'Rock Hill':  'Rock Hill',
    'Clover':     'Clover',
    'Fort Mill':  'Fort Mill',
    'Lake Wylie': 'Lake Wylie',
    'York':       'York',
    'Bookmobile': 'Bookmobile/Outreach',
}

# (first_data_row 1-indexed pointing at Rock Hill row, metric_id)
# Row positions identical to 22-23 Annual Stats.xls format
SECTIONS = [
    (15, 17),   # Synchronus Age 0-5 Sessions      → ONSITE Sessions 0-5
    (22, 18),   # Synchronus Age 6-11 Sessions      → ONSITE Sessions 6-11
    (29, 19),   # Synchronus Age 12-18 Sessions     → ONSITE Sessions 12-18
    (36, 20),   # Synchronus Age 18+ Sessions       → ONSITE Sessions 19+
    (43, 21),   # Synchronus General Interest S.    → ONSITE Sessions General Interest
    (57, 28),   # S. In-Person Offsite Sessions     → OFFSITE Sessions 6-11 (convention)
    (64, 41),   # S. Virtual Program Sessions       → VIRTUAL Sessions General Interest
    (75, 22),   # Age 0-5 Attendance                → ONSITE Attendance 0-5
    (82, 23),   # Age 6-11 Attendance               → ONSITE Attendance 6-11
    (89, 24),   # Age 12-18 Attendance              → ONSITE Attendance 12-18
    (96, 25),   # Age 18+ Attendance                → ONSITE Attendance 19+
    (103, 26),  # General Interest Attendance       → ONSITE Attendance General Interest
    (117, 33),  # S. In-Person Offsite Attendance   → OFFSITE Attendance 6-11 (convention)
    (124, 46),  # S. Virtual Program Attendance     → VIRTUAL Attendance General Interest
]

PROG_METRIC_IDS = set(range(17, 47))

SESS_METRIC_IDS = [17, 18, 19, 20, 21, 28, 41]
ATT_METRIC_IDS  = [22, 23, 24, 25, 26, 33, 46]


def parse_sheet():
    """Returns {(ls_branch, year, month): {metric_id: value}}"""
    wb = xlrd.open_workbook(XLS)
    ws = wb.sheet_by_name('Program Comparison p.5')
    data = {}
    for first_row, metric_id in SECTIONS:
        for b_offset, branch_name in enumerate(BRANCH_ORDER):
            row = ws.row_values(first_row - 1 + b_offset)
            for col_idx, month in COL_TO_MONTH.items():
                year = COL_TO_YEAR[col_idx]
                raw  = row[col_idx]
                val  = int(raw) if isinstance(raw, (int, float)) and raw != '' else 0
                key  = (branch_name, year, month)
                if key not in data:
                    data[key] = {}
                data[key][metric_id] = val
    return data


def has_programming(entry_id):
    return EntryValue.query.filter(
        EntryValue.entry_id == entry_id,
        EntryValue.metric_id.in_(PROG_METRIC_IDS),
        EntryValue.value_number != None,
        EntryValue.value_number != 0,
    ).first() is not None


def upsert_value(entry_id, metric_id, value):
    ev = EntryValue.query.filter_by(entry_id=entry_id, metric_id=metric_id).first()
    if ev:
        ev.value_number = float(value)
    else:
        db.session.add(EntryValue(entry_id=entry_id, metric_id=metric_id, value_number=float(value)))


def main(dry_run=True):
    print(f"{'DRY RUN — ' if dry_run else ''}Loading FY2023-24 programming data\n")

    sheet_data = parse_sheet()

    with app.app_context():
        branches = {b.name: b.id for b in Branch.query.all()}

        entries_created = 0
        entries_patched = 0
        entries_skipped = 0

        for ls_branch in BRANCH_ORDER:
            db_name   = BRANCH_NAME_MAP[ls_branch]
            branch_id = branches.get(db_name)
            if not branch_id:
                print(f"  ERROR: branch '{db_name}' not found in DB")
                continue

            for col_idx in sorted(COL_TO_MONTH):
                month    = COL_TO_MONTH[col_idx]
                year     = COL_TO_YEAR[col_idx]
                key      = (ls_branch, year, month)
                metrics  = sheet_data.get(key, {})
                non_zero = {k: v for k, v in metrics.items() if v}

                if not non_zero:
                    continue  # no programming data for this branch/month

                entry = Entry.query.filter_by(
                    category_id=CATEGORY_ID,
                    branch_id=branch_id,
                    year=year,
                    month=month,
                ).first()

                if entry and has_programming(entry.id):
                    print(f"  SKIP  {ls_branch} {year}-{month:02d} (entry {entry.id}): already has programming data")
                    entries_skipped += 1
                    continue

                sess = sum(non_zero.get(m, 0) for m in SESS_METRIC_IDS)
                att  = sum(non_zero.get(m, 0) for m in ATT_METRIC_IDS)
                action = "CREATE" if not entry else "PATCH "
                print(f"  {action} {ls_branch} {year}-{month:02d}: {sess} sessions, {att} attendance ({len(non_zero)} values)")

                if not dry_run:
                    if not entry:
                        entry = Entry(
                            category_id=CATEGORY_ID,
                            branch_id=branch_id,
                            year=year,
                            month=month,
                            submitted_by='Patch: FY2324 programming',
                        )
                        db.session.add(entry)
                        db.session.flush()
                        entries_created += 1

                    for mid, val in non_zero.items():
                        upsert_value(entry.id, mid, val)
                    db.session.commit()
                    entries_patched += 1

        if dry_run:
            print("\nDry run complete. Run with --apply to write to DB.")
        else:
            print(f"\nDone. {entries_created} entries created, {entries_patched} entries patched, {entries_skipped} skipped.")


if __name__ == '__main__':
    main(dry_run='--apply' not in sys.argv)
