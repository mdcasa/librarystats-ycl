"""
One-time import of stats.xlsx into the database.

Usage:
    python import_excel.py

DATABASE_URL is read from the .env file or environment variable.
"""

import os
import sys
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

import openpyxl
from app import app, db
from models import Category, Metric, Branch, Entry, EntryValue

EXCEL_PATH = os.path.join('Data files', 'stats.xlsx')

# ── Column name mappings (Excel header → database metric name) ────────────────

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

ONLINE_STATS_MAP = {
    'yclibrary.org - web sessions':      'yclibrary.org - Web Sessions',
    'ychistory.org - views':             'ychistory.org - Views',
    'patchworktales.org  - views':       'patchworktales.org - Views',
    'Dial A Story - CALLS':              'Dial A Story - Calls',
    'Dial A Story - VIEWS':              'Dial A Story - Views',
    'DSpace - Views':                    'DSpace - Views',
    'Beanstack - Sessions':              'Beanstack - Sessions',
    'LibraryCalendar - Sessions':        'LibraryCalendar - Sessions',
    'LibGuides - Sessions':              'LibGuides - Sessions',
    'DigitalLearn.org - Sessions':       'DigitalLearn.org - Sessions',
    'DigitalLearn.org - Completed Courses': 'DigitalLearn.org - Completed Courses',
    'LOTE4Kids - Stories Watched':       'LOTE4Kids - Stories Watched',
    'LOTE4Kids - Actvitities':           'LOTE4Kids - Activities',
    'LOTE4Kids - Logins':                'LOTE4Kids - Logins',
    'Youtube - Subscribers':             'YouTube - Subscribers',
    'YouTube - Views':                   'YouTube - Views',
    'YouTube - Hours Watched':           'YouTube - Hours Watched',
    'YCL News - Subscriber':             'YCL News - Subscribers',
    'Website Messages':                  'Website Messages',
    'YCL - App - Users':                 'YCL App - Users',
    'YCL - App - Sessions':              'YCL App - Sessions',
    'Facebook Followers':                'Facebook Followers',
    'Instragram - Subscribers':          'Instagram - Subscribers',
    'YouTube Uploads':                   'YouTube Uploads',
    'Dial A Story Uploads':              'Dial A Story Uploads',
}

ERESOURCES_MAP = {
    'E-Book Circ':    'E-Book Circulation',
    'E-Audio Circ':   'E-Audio Circulation',
    'E-Video Circ':   'E-Video Circulation',
    'E-Serials Circ': 'E-Serials Circulation',
}

QRTLY_MAP = {
    'Total # of Transactions for the Week': 'Total Transactions for the Week',
}

# ── Helpers ───────────────────────────────────────────────────────────────────

_MONTH_NAMES = {
    'january':1,'february':2,'march':3,'april':4,'may':5,'june':6,
    'july':7,'august':8,'september':9,'october':10,'november':11,'december':12,
}

def parse_month(val):
    """Return 1-12 from a datetime (day==month in this dataset) or month name string."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.month
    if isinstance(val, str):
        return _MONTH_NAMES.get(val.strip().lower())
    return None

def parse_quarter(val):
    """Return 1-4 from strings like 'Quarter 2 - 10-October'."""
    if isinstance(val, str) and val.lower().startswith('quarter'):
        try:
            return int(val.split()[1])
        except (IndexError, ValueError):
            pass
    return None

def col_index(headers, name):
    """Return column index for an exact header name, or None."""
    try:
        return list(headers).index(name)
    except ValueError:
        return None

def build_metric_lookup(category_name):
    """Return {metric_name: Metric} for a category."""
    cat = Category.query.filter_by(name=category_name).first()
    if not cat:
        return {}, None
    return {m.name: m for m in cat.metrics}, cat

def build_branch_lookup():
    """Return a dict that matches branch names case-insensitively plus known aliases."""
    branches = Branch.query.all()
    lookup = {}
    for b in branches:
        lookup[b.name] = b
        lookup[b.name.lower()] = b
        lookup[b.name.upper()] = b

    # Aliases for variations found in the Excel file
    _aliases = {
        'OUTREACH / BOOKMOBILE': 'Bookmobile/Outreach',
        'Outreach / Bookmobile': 'Bookmobile/Outreach',
        'outreach / bookmobile': 'Bookmobile/Outreach',
        'BOOKMOBILE/OUTREACH':   'Bookmobile/Outreach',
        'YCL SYSTEM WIDE':       'YCL (System Wide)',
    }
    for alias, canonical in _aliases.items():
        if canonical in lookup:
            lookup[alias] = lookup[canonical]

    return lookup

# ── Sheet importers ───────────────────────────────────────────────────────────

def import_branch_stats(ws, cat, metric_lookup, branch_lookup):
    rows = list(ws.iter_rows(values_only=True))
    headers = rows[0]

    year_idx    = col_index(headers, 'Year')
    month_idx   = col_index(headers, 'Month')
    branch_idx  = col_index(headers, 'BRANCH')

    # Map column index → Metric object
    col_metric = {}
    for i, h in enumerate(headers):
        if h and h in BRANCH_STATS_MAP:
            m = metric_lookup.get(BRANCH_STATS_MAP[h])
            if m:
                col_metric[i] = m

    # Accumulate: (year, month, branch_id) → {metric_id: value}
    # Multiple Excel rows for the same period/branch are merged.
    buckets = {}
    skipped_branches = set()

    for row in rows[1:]:
        if all(v is None for v in row):
            continue

        year        = row[year_idx]   if year_idx   is not None else None
        month_raw   = row[month_idx]  if month_idx  is not None else None
        branch_name = row[branch_idx] if branch_idx is not None else None

        month = parse_month(month_raw)
        if not year or not month or not branch_name:
            continue

        branch = branch_lookup.get(branch_name)
        if branch is None:
            skipped_branches.add(branch_name)
            continue

        key = (int(year), month, branch.id)
        if key not in buckets:
            buckets[key] = {}

        for i, val in enumerate(row):
            if i in col_metric and val is not None:
                buckets[key][col_metric[i].id] = float(val)

    if skipped_branches:
        print(f"  Warning: unrecognised branches skipped: {skipped_branches}")

    created = 0
    for (year, month, branch_id), values in buckets.items():
        if not values:
            continue
        entry = Entry(category_id=cat.id, branch_id=branch_id,
                      year=year, month=month, submitted_by='Excel Import')
        db.session.add(entry)
        db.session.flush()
        for metric_id, val in values.items():
            db.session.add(EntryValue(entry_id=entry.id, metric_id=metric_id,
                                      value_number=val))
        created += 1

    db.session.commit()
    print(f"  Branch Stats: {created} entries imported")


def import_sheet_no_branch(ws, cat, metric_lookup, col_map, sheet_label):
    rows = list(ws.iter_rows(values_only=True))
    headers = rows[0]

    year_idx  = col_index(headers, 'Year')
    month_idx = col_index(headers, 'Month')

    col_metric = {}
    for i, h in enumerate(headers):
        if h and h in col_map:
            m = metric_lookup.get(col_map[h])
            if m:
                col_metric[i] = m

    buckets = {}
    for row in rows[1:]:
        if all(v is None for v in row):
            continue

        year      = row[year_idx]  if year_idx  is not None else None
        month_raw = row[month_idx] if month_idx is not None else None
        month     = parse_month(month_raw)

        if not year or not month:
            continue

        key = (int(year), month)
        if key not in buckets:
            buckets[key] = {}

        for i, val in enumerate(row):
            if i in col_metric and val is not None:
                buckets[key][col_metric[i].id] = float(val)

    created = 0
    for (year, month), values in buckets.items():
        if not values:
            continue
        entry = Entry(category_id=cat.id, year=year, month=month,
                      submitted_by='Excel Import')
        db.session.add(entry)
        db.session.flush()
        for metric_id, val in values.items():
            db.session.add(EntryValue(entry_id=entry.id, metric_id=metric_id,
                                      value_number=val))
        created += 1

    db.session.commit()
    print(f"  {sheet_label}: {created} entries imported")


def import_quarterly_ref(ws, cat, metric_lookup, branch_lookup):
    rows = list(ws.iter_rows(values_only=True))
    headers = rows[0]

    year_idx    = col_index(headers, 'Year')
    quarter_idx = col_index(headers, 'Quarter')
    branch_idx  = col_index(headers, 'Branch or Location')
    value_idx   = col_index(headers, 'Total # of Transactions for the Week')

    metric = metric_lookup.get('Total Transactions for the Week')
    if not metric:
        print("  Quarterly Ref Stats: metric not found, skipping")
        return

    created = 0
    skipped_branches = set()

    for row in rows[1:]:
        if all(v is None for v in row):
            continue

        year        = row[year_idx]    if year_idx    is not None else None
        quarter_raw = row[quarter_idx] if quarter_idx is not None else None
        branch_name = row[branch_idx]  if branch_idx  is not None else None
        val         = row[value_idx]   if value_idx   is not None else None

        quarter = parse_quarter(quarter_raw)
        if not year or not quarter or not branch_name or val is None:
            continue

        branch = branch_lookup.get(branch_name)
        if branch is None:
            skipped_branches.add(branch_name)
            continue

        entry = Entry(category_id=cat.id, branch_id=branch.id,
                      year=int(year), quarter=quarter, submitted_by='Excel Import')
        db.session.add(entry)
        db.session.flush()
        db.session.add(EntryValue(entry_id=entry.id, metric_id=metric.id,
                                  value_number=float(val)))
        created += 1

    db.session.commit()
    if skipped_branches:
        print(f"  Warning: unrecognised branches skipped: {skipped_branches}")
    print(f"  Quarterly Ref Stats: {created} entries imported")


# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    if not os.path.exists(EXCEL_PATH):
        print(f"ERROR: Cannot find {EXCEL_PATH}")
        sys.exit(1)

    print(f"Opening {EXCEL_PATH} ...")
    wb = openpyxl.load_workbook(EXCEL_PATH, data_only=True)

    with app.app_context():
        branch_lookup = build_branch_lookup()

        # Branch Stats
        print("\nImporting Branch Stats ...")
        metric_lookup, cat = build_metric_lookup('Branch Stats')
        if cat:
            import_branch_stats(wb['Branch Stats'], cat, metric_lookup, branch_lookup)
        else:
            print("  Category 'Branch Stats' not found in database — skipping")

        # eResources
        print("\nImporting eResources ...")
        metric_lookup, cat = build_metric_lookup('eResources')
        if cat:
            import_sheet_no_branch(wb['eResources'], cat, metric_lookup,
                                   ERESOURCES_MAP, 'eResources')
        else:
            print("  Category 'eResources' not found — skipping")

        # Online Stats
        print("\nImporting Online Stats ...")
        metric_lookup, cat = build_metric_lookup('Online Stats')
        if cat:
            import_sheet_no_branch(wb['Online Stats'], cat, metric_lookup,
                                   ONLINE_STATS_MAP, 'Online Stats')
        else:
            print("  Category 'Online Stats' not found — skipping")

        # Quarterly Reference Stats
        print("\nImporting Quarterly Reference Stats ...")
        metric_lookup, cat = build_metric_lookup('Quarterly Reference Stats')
        if cat:
            import_quarterly_ref(wb['Qrtly Ref Stats'], cat, metric_lookup, branch_lookup)
        else:
            print("  Category 'Quarterly Reference Stats' not found — skipping")

        print("\nDone!")


if __name__ == '__main__':
    run()
