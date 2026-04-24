"""
Import stats from an Excel workbook into the database.

Handles three sheets:
  Branch Stats      – monthly per-branch statistics
  Online Stats      – monthly system-wide online/social metrics
  Qrtly Ref Stats   – quarterly reference transaction samples per branch/desk

Usage (CLI):
    python import_excel.py [path/to/file.xlsx]

Can also be called from the web admin via do_import(workbook).
"""

import os
import sys
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

import openpyxl
from app import app, db
from models import Category, Metric, Branch, Entry, EntryValue, SirsiCheckout

DEFAULT_EXCEL_PATH = os.path.join('Data files', 'statsonly423.xlsx')

# ── Column name mappings ──────────────────────────────────────────────────────

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
    """Accept Q1, Quarter 1, q1, 1, '1', 1.0 etc."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        v = int(val)
        return v if 1 <= v <= 4 else None
    if isinstance(val, str):
        s = val.strip().lower()
        # "quarter 1", "quarter1", "quarter 1 - june", etc.
        if s.startswith('quarter'):
            rest = s[7:].strip()
            # grab just the leading number (handles "1 - June" style labels)
            token = rest.split()[0].rstrip('-').strip() if rest else ''
            try:
                v = int(token)
                return v if 1 <= v <= 4 else None
            except ValueError:
                return None
        # "q1" or "q 1"
        if s.startswith('q'):
            rest = s[1:].strip()
            try:
                v = int(rest)
                return v if 1 <= v <= 4 else None
            except ValueError:
                return None
        # bare number
        try:
            v = int(s)
            return v if 1 <= v <= 4 else None
        except ValueError:
            return None
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
    """Return a dict mapping every reasonable name variant → Branch object."""
    lookup = {}
    for b in Branch.query.all():
        for variant in [b.name.strip(), b.name.strip().lower(), b.name.strip().upper()]:
            lookup[variant] = b

    aliases = {
        # Outreach/Bookmobile variants
        'OUTREACH / BOOKMOBILE':  'Outreach/Bookmobile',
        'Outreach / Bookmobile':  'Outreach/Bookmobile',
        'outreach / bookmobile':  'Outreach/Bookmobile',
        'OUTREACH/BOOKMOBILE':    'Outreach/Bookmobile',
        'outreach/bookmobile':    'Outreach/Bookmobile',
        'BOOKMOBILE/OUTREACH':    'Outreach/Bookmobile',
        'OUTREACH / BKM':         'Outreach/Bookmobile',
        'Outreach / BKM':         'Outreach/Bookmobile',
        # System-wide variants
        'YCL SYSTEM WIDE':        'YCL (System Wide)',
        'YCL (SYSTEM WIDE)':      'YCL (System Wide)',
        # Rock Hill desk short-forms
        'ROCK HILL - CIRC':           'Rock Hill - Circulation',
        'Rock Hill - Circ':           'Rock Hill - Circulation',
        'rock hill - circ':           'Rock Hill - Circulation',
        'ROCK HILL CIRCULATION':      'Rock Hill - Circulation',
        'Rock Hill Circulation':      'Rock Hill - Circulation',
        'RH - CIRC':                  'Rock Hill - Circulation',
        'RH Circ':                    'Rock Hill - Circulation',
        'ROCK HILL - YA':             'Rock Hill - YA',
        'Rock Hill YA':               'Rock Hill - YA',
        'ROCK HILL YA':               'Rock Hill - YA',
        'RH - YA':                    'Rock Hill - YA',
        'RH YA':                      'Rock Hill - YA',
        # Locker locations (ILS codes)
        'YCL-CL-LOC':                 'Clover - Lockers',
        'YCL-FM-LOC':                 'Fort Mill - Lockers',
        'YCL-LW-LOC':                 'Lake Wylie - Lockers',
        'YCL-RH-LOC':                 'Rock Hill - Lockers',
        'YCL-YK-LOC':                 'York - Lockers',
    }
    for alias, canonical in aliases.items():
        target = lookup.get(canonical) or lookup.get(canonical.lower())
        if target:
            lookup[alias] = target
            lookup[alias.lower()] = target

    return lookup


def entry_exists_monthly(cat_id, branch_id, year, month):
    q = Entry.query.filter_by(category_id=cat_id, year=year, month=month)
    if branch_id is None:
        q = q.filter(Entry.branch_id.is_(None))
    else:
        q = q.filter_by(branch_id=branch_id)
    return q.first() is not None


def entry_exists_quarterly(cat_id, branch_id, year, quarter, month=None):
    q = Entry.query.filter_by(category_id=cat_id, year=year, quarter=quarter)
    if month is not None:
        q = q.filter_by(month=month)
    if branch_id is None:
        q = q.filter(Entry.branch_id.is_(None))
    else:
        q = q.filter_by(branch_id=branch_id)
    return q.first() is not None


# ── Sheet importers (return created, skipped, warnings) ───────────────────────

def import_branch_stats(ws, cat, metric_lookup, branch_lookup):
    rows = list(ws.iter_rows(values_only=True))
    headers = rows[0]

    year_idx   = col_index(headers, 'Year')
    month_idx  = col_index(headers, 'Month Num') or col_index(headers, 'Month')
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

        # Skip desk branches — they don't go into Branch Stats
        if getattr(branch, 'is_desk', False):
            continue

        key = (int(year), month, branch.id)
        if key not in buckets:
            buckets[key] = {}
        for i, val in enumerate(row):
            if i in col_metric and val is not None:
                buckets[key][col_metric[i].id] = float(val)

    warnings = [f'Unrecognised branch skipped: {b}' for b in sorted(skipped_branches)]
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
            db.session.add(EntryValue(entry_id=entry.id, metric_id=metric_id, value_number=val))
        created += 1

    db.session.commit()
    return created, skipped, warnings


def import_online_stats(ws, cat, metric_lookup):
    rows = list(ws.iter_rows(values_only=True))
    headers = rows[0]

    year_idx  = col_index(headers, 'Year')
    month_idx = col_index(headers, 'Month Num') or col_index(headers, 'Month')

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
            db.session.add(EntryValue(entry_id=entry.id, metric_id=metric_id, value_number=val))
        created += 1

    db.session.commit()
    return created, skipped, []


def import_quarterly_ref(ws, cat, metric_lookup, branch_lookup):
    rows = list(ws.iter_rows(values_only=True))
    # Skip leading blank rows to find the actual header row
    header_idx = next((i for i, r in enumerate(rows) if any(v is not None for v in r)), 0)
    headers = rows[header_idx]
    rows = rows[header_idx:]  # re-slice so rows[0] is headers, rows[1:] is data

    year_idx    = col_index(headers, 'Year')
    quarter_idx = col_index(headers, 'Quarter')
    month_idx   = col_index(headers, 'Month')
    branch_idx  = col_index(headers, 'Branch or Location') or col_index(headers, 'Branch') or col_index(headers, 'BRANCH')
    value_idx   = col_index(headers, 'Total # of Transactions for the Week')

    metric = metric_lookup.get('Total Transactions for the Week')
    if not metric:
        return 0, 0, ['Metric "Total Transactions for the Week" not found — skipped']

    buckets = {}
    skipped_branches = set()

    for row in rows[1:]:
        if all(v is None for v in row):
            continue

        year        = row[year_idx]    if year_idx    is not None else None
        quarter_raw = row[quarter_idx] if quarter_idx is not None else None
        month_raw   = row[month_idx]   if month_idx   is not None else None
        branch_name = row[branch_idx]  if branch_idx  is not None else None
        val         = row[value_idx]   if value_idx   is not None else None

        if branch_name:
            branch_name = str(branch_name).strip()

        quarter = parse_quarter(quarter_raw)
        month   = parse_month(month_raw)
        if not year or not quarter or not branch_name or val is None:
            continue

        branch = branch_lookup.get(branch_name) or branch_lookup.get(branch_name.upper())
        if branch is None:
            skipped_branches.add(branch_name)
            continue

        key = (int(year), quarter, month, branch.id)
        # Sum multiple rows for the same period (e.g. daily tallies)
        buckets[key] = buckets.get(key, 0) + float(val)

    warnings = [f'Unrecognised branch skipped: {b}' for b in sorted(skipped_branches)]
    created = skipped = 0
    for (year, quarter, month, branch_id), total_val in buckets.items():
        if entry_exists_quarterly(cat.id, branch_id, year, quarter, month):
            skipped += 1
            continue
        entry = Entry(category_id=cat.id, branch_id=branch_id,
                      year=int(year), quarter=quarter, month=month,
                      submitted_by='Excel Import')
        db.session.add(entry)
        db.session.flush()
        db.session.add(EntryValue(entry_id=entry.id, metric_id=metric.id,
                                  value_number=total_val))
        created += 1

    db.session.commit()
    return created, skipped, warnings


# ── SIRSI ILS report importer ─────────────────────────────────────────────────

# ILS station-code → Branch.name
ILS_BRANCH_MAP = {
    'YCL-BK':     'Outreach/Bookmobile',
    'YCL-CL':     'Clover',
    'YCL-CL-LOC': 'Clover - Lockers',
    'YCL-FM':     'Fort Mill',
    'YCL-FM-LOC': 'Fort Mill - Lockers',
    'YCL-LW':     'Lake Wylie',
    'YCL-LW-LOC': 'Lake Wylie - Lockers',
    'YCL-RH':     'Rock Hill',
    'YCL-RH-LOC': 'Rock Hill - Lockers',
    'YCL-YK':     'York',
    'YCL-YK-LOC': 'York - Lockers',
}

# Patron profiles that represent internal/non-patron transactions
INTERNAL_PROFILES = {'DAMAGED', 'DISCARD', 'MISSING', 'REPAIR', 'PRGMNG',
                     'STAFF-PERS', 'YCLCIRC', 'ILL', 'LOSTCARD'}

# New Library Users — patron type classification
_ADULT_PROFILES   = {'ADULT', 'A-NONRES', 'INST-TEACH', 'TEEN', 'COLLEGE', 'HOMEBOUND'}
_JUVENILE_PROFILES = {'JUVENILE', 'J-INTERNET', 'J-RESTRICT', 'JR-NONRES'}

# Door count location name → Branch.name
DOOR_COUNT_BRANCH_MAP = {
    'Clover Library':           'Clover',
    'Fort Mill Library':        'Fort Mill',
    'Lake Wylie Library':       'Lake Wylie',
    'Main - Rock Hill Library': 'Rock Hill',
    'York Library':             'York',
}


# Princh location string → Branch.name (substring match, lowercased)
PRINCH_BRANCH_MAP = {
    'lake wylie': 'Lake Wylie',
    'clover':     'Clover',
    'york':       'York',
    'fort mill':  'Fort Mill',
    'rock hill':  'Rock Hill',
}

# Page-count columns in the Princh export
PRINCH_PAGE_COLS = [
    'Letter color pages', 'Letter monochrome pages',
    'Legal color pages',  'Legal monochrome pages',
    'Ledger color pages', 'Ledger monochrome pages',
]


def import_princh(ws, branch_lookup):
    """
    Parse a Princh print-management export.
    Sums all page-type columns per branch per month → Total Prints per Month.
    """
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return 0, ['Empty sheet']

    headers = list(rows[0])

    def ci(name):
        try: return headers.index(name)
        except ValueError: return None

    loc_idx  = ci('Location')
    from_idx = ci('From')
    page_idxs = [ci(c) for c in PRINCH_PAGE_COLS if ci(c) is not None]

    if loc_idx is None or from_idx is None or not page_idxs:
        return 0, ['Unrecognised Princh format — expected Location, From, and page columns']

    metric_lookup, cat = build_metric_lookup('Branch Stats')
    prints_metric = metric_lookup.get('Total Prints per Month')
    if not cat or not prints_metric:
        return 0, ['Branch Stats or "Total Prints per Month" metric not found']

    from collections import defaultdict
    # (year, month, branch_id) → total pages
    totals = defaultdict(int)
    unrecognised = set()

    for r in rows[1:]:
        if all(v is None for v in r):
            continue
        loc      = r[loc_idx]
        from_val = r[from_idx]
        if not loc or not from_val:
            continue

        # Parse year/month from From date (string '2026-03-01' or datetime)
        if hasattr(from_val, 'year'):
            year, month = from_val.year, from_val.month
        else:
            try:
                parts = str(from_val).split('-')
                year, month = int(parts[0]), int(parts[1])
            except (IndexError, ValueError):
                continue

        # Match location to branch
        loc_lower = str(loc).strip().lower()
        branch_name = next(
            (name for key, name in PRINCH_BRANCH_MAP.items() if key in loc_lower),
            None
        )
        if not branch_name:
            unrecognised.add(str(loc).strip())
            continue
        branch = branch_lookup.get(branch_name)
        if not branch:
            unrecognised.add(branch_name)
            continue

        pages = sum(int(r[i]) for i in page_idxs if isinstance(r[i], (int, float)))
        totals[(year, month, branch.id)] += pages

    warnings = [f'Unrecognised locations skipped: {sorted(unrecognised)}'] if unrecognised else []
    created = updated = 0
    for (year, month, branch_id), total in totals.items():
        r = _upsert_branch_stat(cat.id, branch_id, year, month, prints_metric.id, total)
        if r == 'created': created += 1
        else: updated += 1

    db.session.commit()
    return created, updated, warnings


def _detect_sirsi_report_type(rows):
    """Return ('checkouts_by_location', year, month) or None if not recognised."""
    for r in rows[:15]:
        if r[0] and 'Checkouts by Branch and Shelving Location' in str(r[0]):
            break
    else:
        return None, None, None

    year = month = None
    for r in rows[:15]:
        if str(r[0]).startswith('Trans Stat Year:'):
            try:
                year = int(str(r[0]).split(':')[1].strip())
            except ValueError:
                pass
        if str(r[0]).startswith('Trans Stat Month:'):
            try:
                month = int(str(r[0]).split(':')[1].strip())
            except ValueError:
                pass
    return 'checkouts_by_location', year, month


def import_sirsi_checkouts(ws, year, month, branch_lookup):
    """
    Parse a 'Checkouts by Branch and Shelving Location' SIRSI sheet.

    The sheet contains two page sections separated by a second header block:
      Section 1 — Trans Stat Command Desc: Charge Item Part B  (checkouts)
      Section 2 — Trans Stat Command Desc: Renew Item          (renewals)

    Existing rows for the same year/month are deleted and re-imported.
    Returns (detail_rows_created, circulation_entries_created, warnings).
    """
    rows = list(ws.iter_rows(values_only=True))

    # Delete existing SIRSI detail rows for this period
    SirsiCheckout.query.filter_by(year=year, month=month).delete()

    # Build branch id lookup from ILS codes
    ils_to_branch = {}
    for code, name in ILS_BRANCH_MAP.items():
        b = branch_lookup.get(name) or branch_lookup.get(name.lower())
        if b:
            ils_to_branch[code] = b

    # Parse: track which section we're in (checkouts vs renewals)
    section = None   # 'checkouts' | 'renewals'
    current_ils = None
    warnings = []
    unrecognised = set()

    # accumulate: {(branch_id, patron_type, shelving_location): [checkouts, renewals]}
    detail = {}

    for r in rows:
        cell0 = str(r[0]).strip() if r[0] is not None else ''

        if 'Charge Item Part B' in cell0:
            section = 'checkouts'
            continue
        if 'Renew Item' in cell0:
            section = 'renewals'
            continue
        if section is None:
            continue

        branch_col, profile, location, count = r[0], r[1], r[2], r[3]

        # Update current ILS branch when column is filled
        if branch_col and str(branch_col).startswith('YCL'):
            current_ils = str(branch_col).strip()

        if not isinstance(count, (int, float)):
            continue
        if location in (None, 'Total', 'Number of Checkouts'):
            continue
        if profile == 'Total' or profile == 'Trans Stat User Profile Name':
            continue
        if current_ils is None:
            continue

        branch = ils_to_branch.get(current_ils)
        if branch is None:
            unrecognised.add(current_ils)
            continue

        key = (branch.id, str(profile) if profile else None, str(location))
        if key not in detail:
            detail[key] = [0, 0]
        if section == 'checkouts':
            detail[key][0] += int(count)
        else:
            detail[key][1] += int(count)

    if unrecognised:
        warnings.append(f"Unrecognised ILS codes skipped: {sorted(unrecognised)}")

    # Write detail rows
    for (branch_id, patron_type, shelving_location), (chk, ren) in detail.items():
        db.session.add(SirsiCheckout(
            year=year, month=month,
            branch_id=branch_id,
            patron_type=patron_type,
            shelving_location=shelving_location,
            checkouts=chk,
            renewals=ren,
        ))

    # Write Circulation category totals (per branch + system-wide)
    circ_metrics, circ_cat = build_metric_lookup('Circulation')
    chk_metric      = circ_metrics.get('Checkouts')
    ren_metric      = circ_metrics.get('Renewals')
    hotspot_metric  = circ_metrics.get('Hotspots Checkouts')
    circ_entries = 0

    if circ_cat and chk_metric and ren_metric:
        # Remove existing Circulation entries for this period
        old = Entry.query.filter_by(category_id=circ_cat.id, year=year, month=month).all()
        for e in old:
            EntryValue.query.filter_by(entry_id=e.id).delete()
            db.session.delete(e)

        # Aggregate checkouts/renewals and hotspot checkouts by branch
        branch_totals   = {}  # branch_id → [checkouts, renewals, hotspots]
        for (branch_id, patron_type, shelving_location), (chk, ren) in detail.items():
            if branch_id not in branch_totals:
                branch_totals[branch_id] = [0, 0, 0]
            branch_totals[branch_id][0] += chk
            branch_totals[branch_id][1] += ren
            if shelving_location == 'A-HOTSPOT':
                branch_totals[branch_id][2] += chk

        system_chk = system_ren = system_hot = 0
        for branch_id, (chk, ren, hot) in branch_totals.items():
            entry = Entry(category_id=circ_cat.id, branch_id=branch_id,
                          year=year, month=month, submitted_by='SIRSI Import')
            db.session.add(entry)
            db.session.flush()
            db.session.add(EntryValue(entry_id=entry.id, metric_id=chk_metric.id, value_number=chk))
            db.session.add(EntryValue(entry_id=entry.id, metric_id=ren_metric.id, value_number=ren))
            if hotspot_metric and hot:
                db.session.add(EntryValue(entry_id=entry.id, metric_id=hotspot_metric.id, value_number=hot))
            circ_entries += 1
            system_chk += chk
            system_ren  += ren
            system_hot  += hot

        # System-wide row
        sys_entry = Entry(category_id=circ_cat.id, branch_id=None,
                          year=year, month=month, submitted_by='SIRSI Import')
        db.session.add(sys_entry)
        db.session.flush()
        db.session.add(EntryValue(entry_id=sys_entry.id, metric_id=chk_metric.id, value_number=system_chk))
        db.session.add(EntryValue(entry_id=sys_entry.id, metric_id=ren_metric.id, value_number=system_ren))
        if hotspot_metric and system_hot:
            db.session.add(EntryValue(entry_id=sys_entry.id, metric_id=hotspot_metric.id, value_number=system_hot))
        circ_entries += 1

    db.session.commit()
    return len(detail), circ_entries, warnings


def import_sirsi_user_profile(ws, branch_lookup):
    """
    Parse 'Checkouts by Branch and User Profile' SIRSI report.
    Stores adult/juvenile checkout totals per branch in sirsi_checkouts
    (patron_type set, shelving_location=None).
    Existing rows for the same period with patron_type data are replaced.
    """
    rows = list(ws.iter_rows(values_only=True))

    year = month = None
    for r in rows[:15]:
        if r[0] and 'Trans Stat Year:' in str(r[0]):
            try: year = int(str(r[0]).split(':')[1].strip())
            except: pass
        if r[0] and 'Trans Stat Month:' in str(r[0]):
            try: month = int(str(r[0]).split(':')[1].strip())
            except: pass

    if not year or not month:
        return 0, 0, ['Could not determine year/month from report']

    ils_to_branch = {}
    for code, name in ILS_BRANCH_MAP.items():
        b = branch_lookup.get(name) or branch_lookup.get(name.lower())
        if b:
            ils_to_branch[code] = b

    # Delete existing patron-type rows for this period (shelving_location IS NULL)
    (SirsiCheckout.query
     .filter_by(year=year, month=month)
     .filter(SirsiCheckout.shelving_location == None)  # noqa: E711
     .delete())

    from collections import defaultdict
    # branch_id → {'adult': n, 'juvenile': n}
    counts = defaultdict(lambda: {'adult': 0, 'juvenile': 0})
    unrecognised = set()

    for r in rows:
        ils = r[0]
        profile = r[1]
        count = r[2]
        if not isinstance(count, (int, float)):
            continue
        if profile in (None, 'Total', 'Trans Stat User Profile Name'):
            continue
        if ils in (None, 'Trans Stat Station Library'):
            continue

        ils = str(ils).strip()
        if ils == 'YCL':
            continue  # system-wide summary row, not a branch
        branch = ils_to_branch.get(ils)
        if branch is None:
            unrecognised.add(ils)
            continue

        p = str(profile).strip()
        if p in _ADULT_PROFILES:
            counts[branch.id]['adult'] += int(count)
        elif p in _JUVENILE_PROFILES:
            counts[branch.id]['juvenile'] += int(count)

    detail = []
    for branch_id, c in counts.items():
        for ptype, val in [('adult', c['adult']), ('juvenile', c['juvenile'])]:
            if val:
                row = SirsiCheckout(year=year, month=month, branch_id=branch_id,
                                    patron_type=ptype, shelving_location=None,
                                    checkouts=val, renewals=0)
                db.session.add(row)
                detail.append(row)

    warnings = [f'Unrecognised ILS codes skipped: {sorted(unrecognised)}'] if unrecognised else []
    db.session.commit()
    return len(detail), year, month, warnings


def _upsert_branch_stat(cat_id, branch_id, year, month, metric_id, value):
    """
    Create or update a single EntryValue for a Branch Stats entry.
    Returns 'created' or 'updated'.
    """
    entry = Entry.query.filter_by(category_id=cat_id, branch_id=branch_id,
                                  year=year, month=month).first()
    if not entry:
        entry = Entry(category_id=cat_id, branch_id=branch_id,
                      year=year, month=month, submitted_by='File Import')
        db.session.add(entry)
        db.session.flush()
    ev = EntryValue.query.filter_by(entry_id=entry.id, metric_id=metric_id).first()
    if ev:
        ev.value_number = value
        return 'updated'
    else:
        db.session.add(EntryValue(entry_id=entry.id, metric_id=metric_id,
                                  value_number=value))
        return 'created'


def import_new_library_users(ws, year, month, branch_lookup):
    """
    Parse 'Number of New Library Users by Branch and Patron Type' SIRSI report.
    Updates New Library Card Registrations (Adult / Juvenile) in Branch Stats.
    """
    rows = list(ws.iter_rows(values_only=True))

    metric_lookup, cat = build_metric_lookup('Branch Stats')
    adult_metric    = metric_lookup.get('New Library Card Registrations, Adult')
    juvenile_metric = metric_lookup.get('New Library Card Registrations, Juvenile')
    if not cat or not adult_metric or not juvenile_metric:
        return 0, ['Branch Stats or registration metrics not found']

    # Build ILS code → Branch lookup
    ils_to_branch = {}
    for code, name in ILS_BRANCH_MAP.items():
        b = branch_lookup.get(name) or branch_lookup.get(name.lower())
        if b:
            ils_to_branch[code] = b

    # Aggregate counts: branch_id → {adult, juvenile}
    from collections import defaultdict
    counts = defaultdict(lambda: [0, 0])  # [adult, juvenile]
    unrecognised = set()

    for r in rows:
        user_lib = r[1]
        profile  = r[2]
        count    = r[3]
        if not isinstance(count, (int, float)):
            continue
        if profile in (None, 'Total', 'Trans Stat User Profile Name'):
            continue
        if user_lib in (None, 'Total', 'Trans Stat User Library'):
            continue

        ils = str(user_lib).strip()
        branch = ils_to_branch.get(ils)
        if branch is None:
            unrecognised.add(ils)
            continue

        p = str(profile).strip()
        if p in _ADULT_PROFILES:
            counts[branch.id][0] += int(count)
        elif p in _JUVENILE_PROFILES:
            counts[branch.id][1] += int(count)

    warnings = [f'Unrecognised ILS codes skipped: {sorted(unrecognised)}'] if unrecognised else []
    created = updated = 0
    for branch_id, (adult, juvenile) in counts.items():
        for val, metric in [(adult, adult_metric), (juvenile, juvenile_metric)]:
            if val:
                r = _upsert_branch_stat(cat.id, branch_id, year, month, metric.id, val)
                if r == 'created': created += 1
                else: updated += 1

    db.session.commit()
    return created, updated, warnings


def import_door_count(ws, branch_lookup):
    """
    Parse a daily door count sheet (hourly ins/outs per branch).
    Sums 'Ins' per branch per month and updates Gate Count in Branch Stats.
    """
    rows = list(ws.iter_rows(values_only=True))

    metric_lookup, cat = build_metric_lookup('Branch Stats')
    gate_metric = metric_lookup.get('Gate Count')
    if not cat or not gate_metric:
        return 0, ['Branch Stats or Gate Count metric not found']

    from collections import defaultdict
    monthly_ins = defaultdict(lambda: defaultdict(int))  # (year,month) → branch_id → total

    for r in rows:
        loc_name = r[1]
        date     = r[2]
        ins      = r[3]
        if not isinstance(ins, (int, float)) or ins == 0:
            continue
        if not loc_name or loc_name == 'Location Name':
            continue
        if not hasattr(date, 'year'):
            continue

        branch_name = DOOR_COUNT_BRANCH_MAP.get(str(loc_name).strip())
        if not branch_name:
            continue
        branch = branch_lookup.get(branch_name)
        if not branch:
            continue

        monthly_ins[(date.year, date.month)][branch.id] += int(ins)

    created = updated = 0
    for (year, month), branch_totals in monthly_ins.items():
        for branch_id, total in branch_totals.items():
            r = _upsert_branch_stat(cat.id, branch_id, year, month, gate_metric.id, total)
            if r == 'created': created += 1
            else: updated += 1

    db.session.commit()
    return created, updated, []


def detect_and_import(wb):
    """
    Auto-detect the report type from a workbook and route to the correct importer.
    Returns a list of result dicts for display.
    Must be called within an active Flask app context.
    """
    branch_lookup = build_branch_lookup()
    results = []

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))

        # Find first non-blank cell to identify report type
        title = next((str(r[0]) for r in rows if r[0] is not None), '')

        if 'Checkouts by Branch and User Profile' in title:
            det, year, month, w = import_sirsi_user_profile(ws, branch_lookup)
            results.append({'sheet': 'SIRSI Checkouts (by User Profile)',
                             'created': det, 'updated': 0, 'skipped': 0, 'warnings': w,
                             'note': f'{det} adult/juvenile rows stored for {month}/{year}' if year else ''})

        elif 'Checkouts by Branch and Shelving Location' in title:
            report_type, year, month = _detect_sirsi_report_type(rows)
            if year and month:
                det, circ, w = import_sirsi_checkouts(ws, year, month, branch_lookup)
                results.append({'sheet': 'SIRSI Checkouts (by Shelving Location)',
                                 'created': det, 'skipped': 0, 'warnings': w,
                                 'note': f'{circ} Circulation total entries written'})
            else:
                results.append({'sheet': sheet_name, 'created': 0, 'skipped': 0,
                                 'warnings': ['Could not determine year/month from report']})

        elif 'Number of New Library Users' in title:
            year = month = None
            for r in rows[:15]:
                if r[0] and 'Trans Stat Year:' in str(r[0]):
                    try: year = int(str(r[0]).split(':')[1].strip())
                    except: pass
                if r[0] and 'Trans Stat Month:' in str(r[0]):
                    try: month = int(str(r[0]).split(':')[1].strip())
                    except: pass
            # Fallback: month is in the first data column (value like '1', '2', ...)
            if year and not month:
                for r in rows:
                    val = r[0]
                    if val is not None and str(val).isdigit():
                        m = int(val)
                        if 1 <= m <= 12:
                            month = m
                            break
            if year and month:
                created, updated, w = import_new_library_users(ws, year, month, branch_lookup)
                results.append({'sheet': 'New Library Card Registrations',
                                 'created': created, 'updated': updated, 'skipped': 0, 'warnings': w})
            else:
                results.append({'sheet': sheet_name, 'created': 0, 'updated': 0, 'skipped': 0,
                                 'warnings': ['Could not determine year/month from report']})

        elif any(v is not None and 'Letter color pages' in str(v)
                 for r in rows[:3] for v in r):
            created, updated, w = import_princh(ws, branch_lookup)
            results.append({'sheet': 'Total Prints per Month (Princh)',
                             'created': created, 'updated': updated, 'skipped': 0, 'warnings': w})

        elif any(v is not None and 'Location Name' in str(v)
                 for r in rows[:3] for v in r):
            created, updated, w = import_door_count(ws, branch_lookup)
            results.append({'sheet': 'Gate Count (Door Counter)',
                             'created': created, 'updated': updated, 'skipped': 0, 'warnings': w})

        elif sheet_name in ('Branch Stats', 'Online Stats', 'Qrtly Ref Stats') or \
             any(sheet_name in wb.sheetnames for sheet_name in ('Branch Stats', 'Online Stats')):
            # Standard stats workbook — use do_import
            results.extend(do_import(wb))
            break  # do_import handles all sheets at once

        elif sheet_name == 'Sheet1':
            # Could be QRS
            qrs_metrics, qrs_cat = build_metric_lookup('Quarterly Reference Stats')
            if qrs_cat:
                c, s, w = import_quarterly_ref(ws, qrs_cat, qrs_metrics, branch_lookup)
                results.append({'sheet': 'Quarterly Reference Stats',
                                 'created': c, 'skipped': s, 'warnings': w})
            else:
                results.append({'sheet': sheet_name, 'created': 0, 'skipped': 0,
                                 'warnings': ['Unrecognised file format']})
        else:
            results.append({'sheet': sheet_name, 'created': 0, 'skipped': 0,
                             'warnings': ['Unrecognised file format — sheet not imported']})

    return results


def do_import_sirsi(wb):
    """
    Import a SIRSI ILS report workbook.
    Must be called within an active Flask app context.
    Returns a list of result dicts for display.
    """
    branch_lookup = build_branch_lookup()
    results = []

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        report_type, year, month = _detect_sirsi_report_type(rows)

        if report_type == 'checkouts_by_location':
            if not year or not month:
                results.append({'sheet': sheet_name, 'created': 0, 'skipped': 0,
                                 'warnings': ['Could not determine year/month from report header']})
                continue
            detail_ct, circ_ct, w = import_sirsi_checkouts(ws, year, month, branch_lookup)
            results.append({
                'sheet': sheet_name,
                'created': detail_ct,
                'skipped': 0,
                'warnings': w,
                'note': f'{circ_ct} Circulation total entries written',
            })
        else:
            results.append({'sheet': sheet_name, 'created': 0, 'skipped': 0,
                             'warnings': [f'Unrecognised SIRSI report type in sheet "{sheet_name}"']})

    return results


# ── Main orchestrator ─────────────────────────────────────────────────────────

def do_import(wb):
    """
    Import all recognised sheets from an open openpyxl workbook.
    Must be called within an active Flask app context.
    Returns a list of result dicts for display.
    """
    branch_lookup = build_branch_lookup()
    results = []

    # Branch Stats
    metric_lookup, cat = build_metric_lookup('Branch Stats')
    if cat and 'Branch Stats' in wb.sheetnames:
        c, s, w = import_branch_stats(wb['Branch Stats'], cat, metric_lookup, branch_lookup)
        results.append({'sheet': 'Branch Stats', 'created': c, 'skipped': s, 'warnings': w})
    elif 'Branch Stats' not in wb.sheetnames:
        results.append({'sheet': 'Branch Stats', 'created': 0, 'skipped': 0,
                        'warnings': ['Sheet "Branch Stats" not found in workbook']})

    # Online Stats
    metric_lookup, cat = build_metric_lookup('Online Stats')
    if cat and 'Online Stats' in wb.sheetnames:
        c, s, w = import_online_stats(wb['Online Stats'], cat, metric_lookup)
        results.append({'sheet': 'Online Stats', 'created': c, 'skipped': s, 'warnings': w})
    elif 'Online Stats' not in wb.sheetnames:
        results.append({'sheet': 'Online Stats', 'created': 0, 'skipped': 0,
                        'warnings': ['Sheet "Online Stats" not found in workbook']})

    # Quarterly Reference Stats — accept 'Qrtly Ref Stats' or bare 'Sheet1' fallback
    metric_lookup, cat = build_metric_lookup('Quarterly Reference Stats')
    qrtly_sheet = next(
        (n for n in ('Qrtly Ref Stats', 'Sheet1') if n in wb.sheetnames), None
    )
    if cat and qrtly_sheet:
        c, s, w = import_quarterly_ref(wb[qrtly_sheet], cat, metric_lookup, branch_lookup)
        results.append({'sheet': 'Quarterly Reference Stats', 'created': c, 'skipped': s, 'warnings': w})
    elif not qrtly_sheet:
        results.append({'sheet': 'Quarterly Reference Stats', 'created': 0, 'skipped': 0,
                        'warnings': ['Sheet "Qrtly Ref Stats" not found — add this sheet to import quarterly data']})

    return results


def run(excel_path=None):
    path = excel_path or DEFAULT_EXCEL_PATH
    if not os.path.exists(path):
        print(f'ERROR: Cannot find {path}')
        sys.exit(1)

    print(f'Opening {path} ...')
    wb = openpyxl.load_workbook(path, data_only=True)

    with app.app_context():
        results = do_import(wb)

    for r in results:
        print(f"\n{r['sheet']}: {r['created']} created, {r['skipped']} skipped")
        for w in r.get('warnings', []):
            print(f'  Warning: {w}')
    print('\nDone!')


if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) > 1 else None
    run(path)
