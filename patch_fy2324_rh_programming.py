"""
Patch Rock Hill Jan 2024 and Feb 2024 programming data from '23-24 Annual Stats.xls'.

Source: Program Comparison p.5 sheet.
Virtual sessions/attendance stored as General Interest (metric 41/46) since Ls file
gives a single total with no age breakdown.
Offsite totals stored as metric 28/33 (6-11 bucket), matching existing convention.
"""

import os, sys
from dotenv import load_dotenv
load_dotenv()

import xlrd
from flask import Flask
from models import db, Entry, EntryValue, Branch

app = Flask(__name__)
_db_url = os.environ.get('DATABASE_URL', 'sqlite:///librarystats.db')
if _db_url.startswith('postgres://'): _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

XLS = 'Data files/Ls/23-24 Annual Stats.xls'
CATEGORY_ID = 1

# (first_data_row 1-indexed, metric_id, is_attendance)
# Offsite total → metric 28 (sessions) / 33 (attendance); Virtual total → 41 (sessions) / 46 (attendance)
SECTIONS = [
    (15, 17),   # ONSITE Sessions 0-5
    (22, 18),   # ONSITE Sessions 6-11
    (29, 19),   # ONSITE Sessions 12-18
    (36, 20),   # ONSITE Sessions 19+
    (43, 21),   # ONSITE Sessions General Interest
    (57, 28),   # Offsite Sessions total → OFFSITE Sessions 6-11 (convention)
    (64, 41),   # Virtual Sessions total → VIRTUAL Sessions General Interest
    (75, 22),   # ONSITE Attendance 0-5
    (82, 23),   # ONSITE Attendance 6-11
    (89, 24),   # ONSITE Attendance 12-18
    (96, 25),   # ONSITE Attendance 19+
    (103, 26),  # ONSITE Attendance General Interest
    (117, 33),  # Offsite Attendance total → OFFSITE Attendance 6-11
    (124, 46),  # Virtual Attendance total → VIRTUAL Attendance General Interest
]

# Col index in xls: 9=Jan, 10=Feb (FY starts Jul, so col3=Jul ... col9=Jan, col10=Feb)
MONTH_COLS = {1: 9, 2: 10}

def parse_rh_data():
    """Returns {month: {metric_id: value}} for Rock Hill Jan+Feb 2024."""
    wb = xlrd.open_workbook(XLS)
    ws = wb.sheet_by_name('Program Comparison p.5')
    result = {1: {}, 2: {}}
    for first_row, metric_id in SECTIONS:
        rh_row = ws.row_values(first_row - 1)  # Rock Hill is first branch, 0-indexed
        for month, col in MONTH_COLS.items():
            raw = rh_row[col]
            val = int(raw) if isinstance(raw, (int, float)) and raw != '' else 0
            result[month][metric_id] = val
    return result

def upsert_value(entry_id, metric_id, value):
    ev = EntryValue.query.filter_by(entry_id=entry_id, metric_id=metric_id).first()
    if ev:
        ev.value_number = float(value)
    else:
        db.session.add(EntryValue(entry_id=entry_id, metric_id=metric_id, value_number=float(value)))

PROG_METRIC_IDS = set(range(17, 47))

def has_programming(entry_id):
    return EntryValue.query.filter(
        EntryValue.entry_id == entry_id,
        EntryValue.metric_id.in_(PROG_METRIC_IDS),
        EntryValue.value_number != None,
        EntryValue.value_number != 0
    ).first() is not None

def main(dry_run=True):
    print(f"{'DRY RUN — ' if dry_run else ''}Patching Rock Hill Jan/Feb 2024 programming\n")
    data = parse_rh_data()

    with app.app_context():
        rh = Branch.query.filter_by(name='Rock Hill').first()
        if not rh:
            print("ERROR: Rock Hill branch not found"); return

        for month in [1, 2]:
            entry = Entry.query.filter_by(
                category_id=CATEGORY_ID, branch_id=rh.id, year=2024, month=month
            ).first()
            if not entry:
                print(f"  SKIP Rock Hill 2024-{month:02d}: no entry in DB"); continue
            if has_programming(entry.id):
                print(f"  SKIP Rock Hill 2024-{month:02d}: already has programming (entry {entry.id})"); continue

            metrics = data[month]
            sess = sum(metrics.get(m, 0) for m in [17,18,19,20,21,28,29,30,31,37,38,39,40,41])
            att  = sum(metrics.get(m, 0) for m in [22,23,24,25,26,33,34,35,36,42,43,44,45,46])
            non_zero = {k: v for k, v in metrics.items() if v}

            print(f"  PATCH Rock Hill 2024-{month:02d} (entry {entry.id}): {sess} sessions, {att} attendance")
            for mid, val in sorted(non_zero.items()):
                print(f"    metric {mid}: {val}")

            if not dry_run:
                for mid, val in non_zero.items():
                    upsert_value(entry.id, mid, val)
                db.session.commit()
                print(f"    → committed {len(non_zero)} values")

    if dry_run:
        print("\nDry run complete. Run with --apply to write.")
    else:
        print("\nDone.")

if __name__ == '__main__':
    main(dry_run='--apply' not in sys.argv)
