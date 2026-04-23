"""
Import stats-4-23.xlsx into the database, skipping entries that already exist.

Usage:
    python import_excel.py [path/to/file.xlsx]

Default path: 'Data files/stats-4-23.xlsx'
DATABASE_URL is read from .env or the environment.
"""

import os
import sys
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

import openpyxl
from app import app, db
from models import Category, Metric, Branch, Entry, EntryValue

DEFAULT_EXCEL_PATH = os.path.join('Data files', 'stats-4-23.xlsx')

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
    'yclibrary.org - web sessions':        'yclibrary.org - Web Sessions',
    'ychistory.org - views':               'ychistory.org - Views',
    'patchworktales.org  - views':         'patchworktales.org - Views',
    'Dial A Story - CALLS':                'Dial A Story - Calls',
    'Dial A Story - VIEWS':                'Dial A Story - Views',
    'DSpace - Views':                      'DSpace - Views',
    'Beanstack - Sessions':                'Beanstack - Sessions',
    'LibraryCalendar - Sessions':          'LibraryCalendar - Sessions',
    'LibGuides - Sessions':                'LibGuides - Sessions',
    'DigitalLearn.org - Sessions':         'DigitalLearn.org - Sessions',
    'DigitalLearn.org - Completed Courses':'DigitalLearn.org - Completed Courses',
    'LOTE4Kids - Stories Watched':         'LOTE4Kids - Stories Watched',
    'LOTE4Kids - Actvitities':             'LOTE4Kids - Activities',
    'LOTE4Kids - Logins':                  'LOTE4Kids - Logins',
    'Youtube - Subscribers':               'YouTube - Subscribers',
    'YouTube - Views':                     'YouTube - Views',
    'YouTube - Hours Watched':             'YouTube - Hours Watched',
    'YCL News - Subscriber':               'YCL News - Subscribers',
    'Website Messages':                    'Website Messages',
    'YCL - App - Users':                   'YCL App - Users',
    'YCL - App - Sessions':                'YCL App - Sessions',
    'Facebook Followers':                  'Facebook Followers',
    'Instragram - Subscribers':            'Instagram - Subscribers',
    'YouTube Uploads':                     'YouTube Uploads',
    'Dial A Story Uploads':                'Dial A Story Uploads',
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
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.month
    if isinstance(val, (int, float)):
        v = int(val)
        return v if 1 <= v <= 12 else None
    if isinstance(val, str):
        return _MONTH_NAMES.get(val.strip().lower())
    return None

def parse_quarter(val):
    if isinstance(val, str) and val.lower().startswith('quarter'):
        try:
            return int(val.split()[1])
        except (IndexError, ValueError):
            pass
    return None

def col_index(headers, name):
    try:
        return list(headers).index(name)
    except ValueError:
        return None

def build_metric_lookup(category_name):
    cat = Category.query.filter_by(name=category_name).first()
    if not cat:
        return {}, None
    return {m.name: m for m in cat.metrics}, cat

def build_branch_lookup():
    branches = Branch.query.all()
    lookup = {}
    for b in branches:
        lookup[b.name.strip()]       = b
        lookup[b.name.strip().lower()] = b
        lookup[b.name.strip().upper()] = b

    _aliases = {
        'OUTREACH / BOOKMOBILE':  'Bookmobile/Outreach',
        'Outreach / Bookmobile':  'Bookmobile/Outreach',
        'outreach / bookmobile':  'Bookmobile/Outreach',
        'OUTREACH/BOOKMOBILE':    'Bookmobile/Outreach',
        'outreach/bookmobile':    'Bookmobile/Outreach',
        'BOOKMOBILE/OUTREACH':    'Bookmobile/Outreach',
        'OUTREACH / BKM':         'Bookmobile/Outreach',
        'Outreach / BKM':         'Bookmobile/Outreach',
        'YCL SYSTEM WIDE':        'YCL (System Wide)',
        'YCL (SYSTEM WIDE)':      'YCL (System Wide)',
    }
    for alias, canonical in _aliases.items():
        if canonical in lookup:
            lookup[alias] = lookup[canonical]

    return lookup

def entry_exists_monthly(cat_id, branch_id, year, month):
    q = Entry.query.filter_by(category_id=cat_id, year=year, month=month)
    if branch_id is None:
        q = q.filter(Entry.branch_id.is_(None))
    else:
        q = q.filter_by(branch_id=branch_id)
    return q.first() is not None

def entry_exists_quarterly(cat_id, branch_id, year, quarter):
    q = Entry.query.filter_by(category_id=cat_id, year=year, quarter=quarter)
    if branch_id is None:
        q = q.filter(Entry.branch_id.is_(None))
    else:
        q = q.filter_by(branch_id=branch_id)
    return q.first() is not None

# ── Sheet importers ───────────────────────────────────────────────────────────

def import_branch_stats(ws, cat, metric_lookup, branch_lookup):
    rows = list(ws.iter_rows(values_only=True))
    headers = rows[0]

    year_idx   = col_index(headers, 'Year')
    month_idx  = col_index(headers, 'Month Num')   # use numeric month column
    if month_idx is None:
        month_idx = col_index(headers, 'Month')    # fallback to name
    branch_idx = col_index(headers, 'BRANCH')

    col_metric = {}
    for i, h in enumerate(headers):
        if h and h in BRANCH_STATS_MAP:
            m = metric_lookup.get(BRANCH_STATS_MAP[h])
            if m:
                col_metric[i] = m

    buckets = {}
    skipped_branches = set()

    for row in rows[1:]:
        if all(v is None for v in row):
            continue

        year        = row[year_idx]   if year_idx   is not None else None
        month_raw   = row[month_idx]  if month_idx  is not None else None
        branch_name = row[branch_idx] if branch_idx is not None else None

        if branch_name:
            branch_name = str(branch_name).strip()

        month = parse_month(month_raw)
        if not year or not month or not branch_name:
            continue

        branch = branch_lookup.get(branch_name) or branch_lookup.get(branch_name.upper())
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

    created = skipped = 0
    for (year, month, branch_id), values in buckets.items():
        if not values:
            continue
        if entry_exists_monthly(cat.id, branch_id, year, month):
            skipped += 1
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
    print(f"  Branch Stats: {created} new entries, {skipped} already existed (skipped)")


def import_online_stats(ws, cat, metric_lookup):
    rows = list(ws.iter_rows(values_only=True))
    headers = rows[0]

    year_idx  = col_index(headers, 'Year')
    month_idx = col_index(headers, 'Month Num')
    if month_idx is None:
        month_idx = col_index(headers, 'Month')

    col_metric = {}
    for i, h in enumerate(headers):
        if h and h in ONLINE_STATS_MAP:
            m = metric_lookup.get(ONLINE_STATS_MAP[h])
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

    created = skipped = 0
    for (year, month), values in buckets.items():
        if not values:
            continue
        if entry_exists_monthly(cat.id, None, year, month):
            skipped += 1
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
    print(f"  Online Stats: {created} new entries, {skipped} already existed (skipped)")


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

    # Merge multiple rows for same (year, quarter, branch)
    buckets = {}
    skipped_branches = set()

    for row in rows[1:]:
        if all(v is None for v in row):
            continue

        year        = row[year_idx]    if year_idx    is not None else None
        quarter_raw = row[quarter_idx] if quarter_idx is not None else None
        branch_name = row[branch_idx]  if branch_idx  is not None else None
        val         = row[value_idx]   if value_idx   is not None else None

        if branch_name:
            branch_name = str(branch_name).strip()

        quarter = parse_quarter(quarter_raw)
        if not year or not quarter or not branch_name or val is None:
            continue

        branch = branch_lookup.get(branch_name) or branch_lookup.get(branch_name.upper())
        if branch is None:
            skipped_branches.add(branch_name)
            continue

        key = (int(year), quarter, branch.id)
        buckets[key] = buckets.get(key, 0) + float(val)

    if skipped_branches:
        print(f"  Warning: unrecognised branches skipped: {skipped_branches}")

    created = skipped = 0
    for (year, quarter, branch_id), total_val in buckets.items():
        if entry_exists_quarterly(cat.id, branch_id, year, quarter):
            skipped += 1
            continue
        entry = Entry(category_id=cat.id, branch_id=branch_id,
                      year=int(year), quarter=quarter, submitted_by='Excel Import')
        db.session.add(entry)
        db.session.flush()
        db.session.add(EntryValue(entry_id=entry.id, metric_id=metric.id,
                                  value_number=total_val))
        created += 1

    db.session.commit()
    if skipped_branches:
        print(f"  Warning: unrecognised branches skipped: {skipped_branches}")
    print(f"  Quarterly Ref Stats: {created} new entries, {skipped} already existed (skipped)")


# ── Main ──────────────────────────────────────────────────────────────────────

def run(excel_path=None):
    path = excel_path or DEFAULT_EXCEL_PATH
    if not os.path.exists(path):
        print(f"ERROR: Cannot find {path}")
        sys.exit(1)

    print(f"Opening {path} ...")
    wb = openpyxl.load_workbook(path, data_only=True)

    with app.app_context():
        branch_lookup = build_branch_lookup()

        print("\nImporting Branch Stats ...")
        metric_lookup, cat = build_metric_lookup('Branch Stats')
        if cat and 'Branch Stats' in wb.sheetnames:
            import_branch_stats(wb['Branch Stats'], cat, metric_lookup, branch_lookup)
        else:
            print("  Skipped (category or sheet not found)")

        print("\nImporting Online Stats ...")
        metric_lookup, cat = build_metric_lookup('Online Stats')
        if cat and 'Online Stats' in wb.sheetnames:
            import_online_stats(wb['Online Stats'], cat, metric_lookup)
        else:
            print("  Skipped (category or sheet not found)")

        print("\nImporting Quarterly Reference Stats ...")
        metric_lookup, cat = build_metric_lookup('Quarterly Reference Stats')
        if cat and 'Qrtly Ref Stats' in wb.sheetnames:
            import_quarterly_ref(wb['Qrtly Ref Stats'], cat, metric_lookup, branch_lookup)
        else:
            print("  Skipped (category or sheet not found)")

        print("\nNOTE: eResources sheet skipped — its column structure (ABCmouse,")
        print("  Biblioboard, hoopla, etc.) does not match the current eResources")
        print("  metrics in the database. Update via Admin > Categories if needed.")

        print("\nDone!")


if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) > 1 else None
    run(path)
