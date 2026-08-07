"""
Import Branch Stats from Data files/statsonly.csv, skipping entries that already exist.

Usage:
    python import_csv.py [path/to/file.csv]
"""

import csv
import os
import sys

from dotenv import load_dotenv
load_dotenv()

from app import app, db
from models import Category, Metric, Branch, Entry, EntryValue

DEFAULT_CSV_PATH = os.path.join('Data files', 'statsonly.csv')

BRANCH_STATS_MAP = {
    'New Library Card Registrations, Adult (includes YA)': 'New Library Card Registrations, Adult',
    'New Library Card Registrations, Juvenile':            'New Library Card Registrations, Juvenile',
    'Gate Count':                                          'Gate Count',
    'PC Reservations':                                     'PC Reservations',
    'WiFi - Unique Sessions':                              'WiFi - Unique Sessions',
    'External Party Library Room Use':                     'External Party Library Room Use',
    'Total Branch Circulation':                            'Total Branch Circulation',
    'Hotspots Circulation':                                'Hotspots Circulation',
    'Curbside':                                            'Curbside',
    'ILL - Sent (Main ONLY)':                              'ILL - Sent (Main ONLY)',
    'ILL - Received (Main ONLY)':                          'ILL - Received (Main ONLY)',
    'ICLs - Sent (MAIN ONLY)':                             'ICLs - Sent (Main ONLY)',
    'ICLs - Received (MAIN ONLY)':                         'ICLs - Received (Main ONLY)',
    'Total Prints per Month':                              'Total Prints per Month',
    'I2:  ONSITE Sessions 0-5':                            'ONSITE Sessions 0-5',
    'I3:   ONSITE Sessions 6-11':                          'ONSITE Sessions 6-11',
    'I4: ONSITE Sessions 12-18':                           'ONSITE Sessions 12-18',
    'I5:   ONSITE Sessions 19+':                           'ONSITE Sessions 19+',
    'I6:  ONSITE Sessions GENERAL INTEREST':               'ONSITE Sessions General Interest',
    'ONSITE Attendance 0-5':                               'ONSITE Attendance 0-5',
    'ONSITE Attendance 6-11':                              'ONSITE Attendance 6-11',
    'ONSITE Attendance 12-18':                             'ONSITE Attendance 12-18',
    'ONSITE Attendance 19+':                               'ONSITE Attendance 19+',
    'ONSITE Attendance General Interest':                  'ONSITE Attendance General Interest',
    'OFFSITE Sessions 0-5':                                'OFFSITE Sessions 0-5',
    'OFFSITE Sessions 6-11':                               'OFFSITE Sessions 6-11',
    'OFFSITE Sessions 12-18':                              'OFFSITE Sessions 12-18',
    'OFFSITE Sessions 19+':                                'OFFSITE Sessions 19+',
    'OFFSITE Sessions General Interest':                   'OFFSITE Sessions General Interest',
    'OFFSITE Attendance 0-5':                              'OFFSITE Attendance 0-5',
    'OFFSITE Attendance 6-11':                             'OFFSITE Attendance 6-11',
    'OFFSITE Attendance 12-18':                            'OFFSITE Attendance 12-18',
    'OFFSITE Attendance 19+':                              'OFFSITE Attendance 19+',
    'OFFSITE Attendance General Interest':                 'OFFSITE Attendance General Interest',
    'VIRTUAL Sessions 0-5':                                'VIRTUAL Sessions 0-5',
    'VIRTUAL Sessions 6-11':                               'VIRTUAL Sessions 6-11',
    'VIRTUAL Sessions 12-18':                              'VIRTUAL Sessions 12-18',
    'VIRTUAL Sessions 19+':                                'VIRTUAL Sessions 19+',
    'VIRTUAL Sessions General Interest':                   'VIRTUAL Sessions General Interest',
    'VIRTUAL Attendance 0-5':                              'VIRTUAL Attendance 0-5',
    'VIRTUAL Attendance 6-11':                             'VIRTUAL Attendance 6-11',
    'VIRTUAL Attendance 12-18':                            'VIRTUAL Attendance 12-18',
    'VIRTUAL Attendance 19+':                              'VIRTUAL Attendance 19+',
    'VIRTUAL Attendance General Interest':                 'VIRTUAL Attendance General Interest',
    'I21: NUMBER OF OUTREACH ACTIVITIES Conducted':        'Number of Outreach Activities Conducted',
    'Outreach Attendance (YCL Internal)':                  'Outreach Attendance',
    'I22: TOTAL # TAKE & MAKES and OTHER PASSIVE PROGRAM PARTICIPANTS\n':
                                                           'Take & Makes / Other Passive Program Participants',
    'I23: NUMBER OF STAFF TAKING TRAINING':                'Number of Staff Taking Training',
    'I24: NUMBER OF HOURS STAFF ATTENDED TRAINING':        'Number of Hours Staff Attended Training',
    '1-on-1 Total for Month':                              '1-on-1 Total for Month',
    'Locker Circulation':                                  'Locker Circulation',
}

BRANCH_ALIASES = {
    'OUTREACH / BOOKMOBILE': 'Bookmobile/Outreach',  # spaces variant in CSV
    'OUTREACH/BOOKMOBILE':   'Bookmobile/Outreach',  # no-spaces variant in CSV
    'BOOKMOBILE/OUTREACH':   'Bookmobile/Outreach',
    'OUTREACH / BKM':        'Bookmobile/Outreach',
    'YCL (SYSTEM WIDE)':     'YCL (System Wide)',
}


def to_float(val):
    """Convert a CSV string value to float, handling commas and blanks."""
    if not val or not val.strip():
        return None
    try:
        return float(val.replace(',', '').strip())
    except ValueError:
        return None


def build_branch_lookup():
    lookup = {}
    for b in Branch.query.all():
        lookup[b.name.strip()]        = b
        lookup[b.name.strip().lower()] = b
        lookup[b.name.strip().upper()] = b
    for alias, canonical in BRANCH_ALIASES.items():
        # Try exact canonical name, then case variations
        target = (lookup.get(canonical) or
                  lookup.get(canonical.upper()) or
                  lookup.get(canonical.lower()))
        if target:
            lookup[alias]        = target
            lookup[alias.lower()] = target
    return lookup


def entry_exists(cat_id, branch_id, year, month):
    q = db.session.query(Entry).filter_by(
        category_id=cat_id, year=year, month=month
    )
    if branch_id is None:
        q = q.filter(Entry.branch_id.is_(None))
    else:
        q = q.filter_by(branch_id=branch_id)
    return q.first() is not None


def run(csv_path=None):
    path = csv_path or DEFAULT_CSV_PATH
    if not os.path.exists(path):
        print(f"ERROR: Cannot find {path}")
        sys.exit(1)

    print(f"Opening {path} ...")

    with app.app_context():
        cat = Category.query.filter_by(name='Branch Stats').first()
        if not cat:
            print("ERROR: 'Branch Stats' category not found in database.")
            sys.exit(1)

        metric_lookup = {m.name: m for m in cat.metrics}
        branch_lookup = build_branch_lookup()

        with open(path, newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames

            # Map CSV column name → Metric object
            col_metric = {}
            for col in headers:
                db_name = BRANCH_STATS_MAP.get(col)
                if db_name:
                    m = metric_lookup.get(db_name)
                    if m:
                        col_metric[col] = m

            # Accumulate rows into buckets keyed by (year, month, branch_id)
            # so multiple CSV rows for the same period merge into one entry.
            buckets = {}
            skipped_branches = set()

            for row in reader:
                branch_name = row.get('BRANCH', '').strip()
                year_str    = row.get('Year', '').strip()
                month_str   = row.get('Month Num', '').strip()

                if not branch_name or not year_str or not month_str:
                    continue

                try:
                    year  = int(year_str)
                    month = int(month_str)
                except ValueError:
                    continue

                branch = branch_lookup.get(branch_name)
                if branch is None:
                    skipped_branches.add(branch_name)
                    continue

                key = (year, month, branch.id)
                if key not in buckets:
                    buckets[key] = {}

                for col, metric in col_metric.items():
                    val = to_float(row.get(col, ''))
                    if val is not None:
                        buckets[key][metric.id] = val

        if skipped_branches:
            print(f"  Warning: unrecognised branches skipped: {skipped_branches}")

        created = skipped = 0
        for (year, month, branch_id), values in sorted(buckets.items()):
            if not values:
                continue
            if entry_exists(cat.id, branch_id, year, month):
                skipped += 1
                continue
            entry = Entry(category_id=cat.id, branch_id=branch_id,
                          year=year, month=month, submitted_by='CSV Import')
            db.session.add(entry)
            db.session.flush()
            for metric_id, val in values.items():
                db.session.add(EntryValue(entry_id=entry.id,
                                          metric_id=metric_id,
                                          value_number=val))
            created += 1

        db.session.commit()
        print(f"\nBranch Stats: {created} new entries created, {skipped} already existed (skipped)")
        print("Done!")


if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) > 1 else None
    run(path)
