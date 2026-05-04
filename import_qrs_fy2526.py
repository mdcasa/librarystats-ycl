"""
Import qrsfinal2025.xlsx into Quarterly Reference Stats.

Quarter → correct year/month (derived from label, overriding file year for Q3):
  Q1 - June      → year=2025, month=6
  Q2 - October   → year=2025, month=10
  Q3 - January   → year=2026, month=1   (file says year=2025, corrected here)
  Q4 - April     → year=2026, month=4

Multiple rows for the same branch/quarter are summed.
Existing entries are skipped (safe to re-run).
"""

import os, sys
from dotenv import load_dotenv
load_dotenv()

import openpyxl
from flask import Flask
from models import db, Entry, EntryValue, Branch, Category, Metric

app = Flask(__name__)
_db_url = os.environ.get('DATABASE_URL', 'sqlite:///librarystats.db')
if _db_url.startswith('postgres://'):
    _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

XLSX = 'Data files/QRS/qrsfinal2025.xlsx'

# Quarter label (lowercased prefix) → (quarter number, year, month)
QUARTER_MAP = {
    'quarter 1': (1, 2025,  6),
    'quarter 2': (2, 2025, 10),
    'quarter 3': (3, 2026,  1),
    'quarter 4': (4, 2026,  4),
}

# Branch name aliases (file name → DB canonical name)
BRANCH_ALIASES = {
    'outreach / bkm':        'Outreach / BKM',
    'rock hill - childrens': "Rock Hill - Children's",
}


def resolve_branch(name, branch_map):
    """Return Branch object for a file branch name, or None if unrecognised."""
    if not name:
        return None
    stripped = name.strip()
    # check aliases first (handles duplicates like Childrens vs Children's)
    canonical = BRANCH_ALIASES.get(stripped.lower())
    if canonical and canonical in branch_map:
        return branch_map[canonical]
    # direct match
    if stripped in branch_map:
        return branch_map[stripped]
    return None


def main(dry_run=True):
    print(f"{'DRY RUN — ' if dry_run else ''}Importing {XLSX}\n")

    wb = openpyxl.load_workbook(XLSX, read_only=True)
    ws = wb['Sheet1']
    rows = list(ws.iter_rows(values_only=True))
    headers = rows[0]

    quarter_idx = headers.index('Quarter')
    branch_idx  = headers.index('Branch or Location')
    value_idx   = headers.index('Total # of Transactions for the Week')

    with app.app_context():
        cat = Category.query.filter_by(name='Quarterly Reference Stats').first()
        metric = next((m for m in cat.metrics if m.name == 'Total Transactions for the Week'), None)
        branch_map = {b.name: b for b in Branch.query.all()}

        # Aggregate: {(quarter, year, month, branch_id): total}
        buckets = {}
        skipped_branches = set()

        for row in rows[1:]:
            if all(v is None for v in row):
                continue

            quarter_label = str(row[quarter_idx]).strip().lower() if row[quarter_idx] else ''
            branch_name   = str(row[branch_idx]).strip() if row[branch_idx] else ''
            val           = row[value_idx]

            if val is None:
                continue

            # Match quarter label prefix
            qinfo = next((v for k, v in QUARTER_MAP.items() if quarter_label.startswith(k)), None)
            if qinfo is None:
                print(f"  WARN  Unrecognised quarter label: '{row[quarter_idx]}' — skipped")
                continue

            quarter, year, month = qinfo

            branch = resolve_branch(branch_name, branch_map)
            if branch is None:
                skipped_branches.add(branch_name)
                continue

            key = (quarter, year, month, branch.id)
            buckets[key] = buckets.get(key, 0) + float(val)

        if skipped_branches:
            for b in sorted(skipped_branches):
                print(f"  WARN  Unrecognised branch skipped: '{b}'")

        created = skipped = 0
        for (quarter, year, month, branch_id), total in sorted(buckets.items()):
            bname = next(b.name for b in branch_map.values() if b.id == branch_id)
            # Check if entry already exists
            existing = Entry.query.filter_by(
                category_id=cat.id, branch_id=branch_id,
                year=year, quarter=quarter, month=month
            ).first()

            if existing:
                print(f"  SKIP  Q{quarter} {year}-{month:02d} {bname}: already exists")
                skipped += 1
                continue

            print(f"  {'DRY ' if dry_run else ''}CREATE  Q{quarter} {year}-{month:02d} {bname}: {int(total)} transactions")

            if not dry_run:
                entry = Entry(
                    category_id=cat.id,
                    branch_id=branch_id,
                    year=year,
                    quarter=quarter,
                    month=month,
                    submitted_by='Import: qrsfinal2025.xlsx',
                )
                db.session.add(entry)
                db.session.flush()
                db.session.add(EntryValue(
                    entry_id=entry.id,
                    metric_id=metric.id,
                    value_number=total,
                ))
                created += 1

        if not dry_run:
            db.session.commit()
            print(f"\nDone. {created} entries created, {skipped} skipped.")
        else:
            print(f"\nDry run complete ({len(buckets)} entries would be created). Run with --apply to write to DB.")


if __name__ == '__main__':
    main(dry_run='--apply' not in sys.argv)
