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
import re
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

def _norm(s):
    """Collapse runs of whitespace and strip edges — used to match Excel headers robustly."""
    return re.sub(r'\s+', ' ', s.strip()) if s else ''

# Normalised lookup built once at import time so import_branch_stats can do
# fuzzy-whitespace matching without mutating the canonical map.
_BRANCH_STATS_MAP_NORM = {_norm(k): v for k, v in BRANCH_STATS_MAP.items()}

# Headers containing these tokens are programming columns we want to warn about
# if they appear in the Excel but aren't matched by the map.
_PROG_TOKENS = {'ONSITE', 'OFFSITE', 'VIRTUAL', 'Sessions', 'Attendance'}

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

# Metrics that must only be recorded under Rock Hill (Main branch).
# Importers skip these for any other branch.
_MAIN_ONLY_METRIC_NAMES = {
    'ILL - Sent (Main ONLY)',
    'ILL - Received (Main ONLY)',
    'ICLs - Sent (Main ONLY)',
    'ICLs - Received (Main ONLY)',
}

# Google Forms response export ("Form Responses 1" sheet).
# OFFSITE/VIRTUAL totals stored in the 6-11 and General Interest buckets by convention
# (matching existing patch scripts — the form has no per-age breakdown for those).
GOOGLE_FORMS_STATS_MAP = {
    # ONSITE programming
    'Number of Synchronous Program Sessions Targeted at Children Ages 0-5':       'ONSITE Sessions 0-5',
    'Number of Synchronous Program Sessions Targeted at Children Ages 6-11':      'ONSITE Sessions 6-11',
    'Number of Synchronous Program Sessions Targeted at Young Adults Ages 12-18': 'ONSITE Sessions 12-18',
    'Number of Synchronous Program Sessions Targeted at Adults Ages 19+':         'ONSITE Sessions 19+',
    'Number of Synchronous General Interest Program Sessions':                     'ONSITE Sessions General Interest',
    'Attendance at Synchronous Programs Targeted at Children Ages 0-5':           'ONSITE Attendance 0-5',
    'Attendance at Synchronous Programs Targeted at Children Ages 6-11':          'ONSITE Attendance 6-11',
    'Attendance at Synchronous Programs Targeted at Young Adults Ages 12-18':     'ONSITE Attendance 12-18',
    'Attendance at Synchronous Programs Targeted at Adults Ages 19+':             'ONSITE Attendance 19+',
    'Attendance at Synchronous General Interest Programs':                         'ONSITE Attendance General Interest',
    # OFFSITE / VIRTUAL totals (no age breakdown in form)
    'Number of Synchronous In-Person Offsite Program Sessions':                    'OFFSITE Sessions 6-11',
    'Number of Synchronous Virtual Program Sessions':                              'VIRTUAL Sessions General Interest',
    'Synchronous In-Person Offsite Program Attendance':                            'OFFSITE Attendance 6-11',
    'Synchronous Virtual Program Attendance':                                      'VIRTUAL Attendance General Interest',
    # Other branch stats
    'Outreach Activities':                                                         'Number of Outreach Activities Conducted',
    'Outreach Attendance':                                                         'Outreach Attendance',
    'Take & Make Kits':                                                            'Take & Makes / Other Passive Program Participants',
    'Door Count':                                                                  'Gate Count',
    'PC Reservation Sessions':                                                     'PC Reservations',
    'WiFi - Unique Clients':                                                       'WiFi - Unique Sessions',
    'InterLibrary Loans  - Received':                                              'ILL - Received (Main ONLY)',
    'InterLibrary Loans - Sent':                                                   'ILL - Sent (Main ONLY)',
    'Number of times library facilities were used by external parties or groups for non library functions (Scheduled use only)':
                                                                                   'External Party Library Room Use',
    # Two spellings found in the wild (advice vs advise typo)
    'Number of scheduled one-on-one sessions between staff and library patrons (Do not include reference transactions and directional advice)':
                                                                                   '1-on-1 Total for Month',
    'Number of scheduled one-on-one sessions between staff and library patrons (Do not include reference transactions and directional advise)':
                                                                                   '1-on-1 Total for Month',
    'Number of Staff Trained at Each Session':                                     'Number of Staff Taking Training',
    'Monthly Total Hours of Staff Training':                                       'Number of Hours Staff Attended Training',
    'Curbside':                                                                    'Curbside',
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
        'OUTREACH / BOOKMOBILE':      'Bookmobile/Outreach',
        'Outreach / Bookmobile':      'Bookmobile/Outreach',
        'outreach / bookmobile':      'Bookmobile/Outreach',
        'OUTREACH/BOOKMOBILE':        'Bookmobile/Outreach',
        'Outreach/Bookmobile':        'Bookmobile/Outreach',
        'outreach/bookmobile':        'Bookmobile/Outreach',
        'BOOKMOBILE/OUTREACH':        'Bookmobile/Outreach',
        'OUTREACH / BKM':             'Bookmobile/Outreach',
        'Outreach / BKM':             'Bookmobile/Outreach',
        'Bookmobile and Outreach':    'Bookmobile/Outreach',
        'BOOKMOBILE AND OUTREACH':    'Bookmobile/Outreach',
        'bookmobile and outreach':    'Bookmobile/Outreach',
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
        'Rock Hill - Childrens':      "Rock Hill - Children's",
        'ROCK HILL - CHILDRENS':      "Rock Hill - Children's",
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

def import_branch_stats(ws, cat, metric_lookup, branch_lookup, year_override=None):
    rows = list(ws.iter_rows(values_only=True))
    headers = rows[0]

    year_idx   = col_index(headers, 'Year')
    month_idx  = col_index(headers, 'Month Num') or col_index(headers, 'Month')
    branch_idx = col_index(headers, 'BRANCH')

    # Never overwrite metrics that come from SIRSI reports — those importers are authoritative.
    _SIRSI_METRIC_NAMES = {
        'New Library Card Registrations, Adult',
        'New Library Card Registrations, Juvenile',
        'New Library Card Registrations, Total',
        'Total Branch Circulation',
        'Hotspots Circulation',
        'Locker Circulation',
    }
    sirsi_metric_ids = {m.id for name, m in metric_lookup.items() if name in _SIRSI_METRIC_NAMES}

    col_metric = {}
    unmatched_prog_cols = []
    for i, h in enumerate(headers):
        if not h:
            continue
        h_str = str(h)
        metric_name = _BRANCH_STATS_MAP_NORM.get(_norm(h_str))
        if metric_name:
            m = metric_lookup.get(metric_name)
            if m and m.id not in sirsi_metric_ids:
                col_metric[i] = m
        else:
            tokens = set(h_str.split())
            if tokens & _PROG_TOKENS:
                unmatched_prog_cols.append(h_str)

    buckets = {}
    skipped_branches = set()

    for row in rows[1:]:
        if all(v is None for v in row):
            continue
        year        = row[year_idx]   if year_idx   is not None else year_override
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

        is_rock_hill = 'rock hill' in branch.name.lower()
        key = (int(year), month, branch.id)
        if key not in buckets:
            buckets[key] = {}
        for i, val in enumerate(row):
            if i in col_metric and val is not None:
                m = col_metric[i]
                if m.name in _MAIN_ONLY_METRIC_NAMES and not is_rock_hill:
                    continue
                buckets[key][m.id] = float(val)

    warnings = [f'Unrecognised branch skipped: {b}' for b in sorted(skipped_branches)]
    if unmatched_prog_cols:
        warnings.append(
            'Programming columns in file not matched to any metric (data NOT imported): '
            + '; '.join(unmatched_prog_cols)
        )
    created = updated = 0
    for (year, month, branch_id), values in buckets.items():
        if not values:
            continue
        entry = Entry.query.filter_by(
            category_id=cat.id, branch_id=branch_id, year=year, month=month
        ).first()
        if entry is None:
            entry = Entry(category_id=cat.id, branch_id=branch_id,
                          year=year, month=month, submitted_by='Excel Import')
            db.session.add(entry)
            db.session.flush()
            created += 1
        else:
            updated += 1
        ev_map = {ev.metric_id: ev for ev in entry.values}
        for metric_id, val in values.items():
            ev = ev_map.get(metric_id)
            if ev:
                ev.value_number = val
            else:
                db.session.add(EntryValue(entry_id=entry.id, metric_id=metric_id, value_number=val))

    db.session.commit()
    period_set = {(y, m) for y, m, _ in buckets.keys()}
    return created, updated, period_set, warnings


def import_google_forms_stats(ws, cat, metric_lookup, branch_lookup):
    """Import monthly branch stats from a Google Forms response export.

    Expects sheet 'Form Responses 1' with columns: Timestamp, Email Address,
    Select Month, Select Branch, then metric columns.  Year is inferred from
    the submission timestamp (if the reported month is later than the
    submission month, the year rolls back by one).

    OFFSITE/VIRTUAL session and attendance totals are stored in the 6-11 and
    General Interest buckets by convention (the form has no per-age breakdown).
    Registration metrics (SIRSI-sourced) are never overwritten.
    """
    # Metrics sourced from SIRSI — never overwrite with form data
    SIRSI_METRIC_NAMES = {
        'New Library Card Registrations, Adult',
        'New Library Card Registrations, Juvenile',
        'Total Branch Circulation',
        'Hotspots Circulation',
        'Locker Circulation',
    }
    sirsi_metric_ids = {m.id for name, m in metric_lookup.items() if name in SIRSI_METRIC_NAMES}

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return 0, 0, set(), ['Empty sheet']

    headers = rows[0]

    timestamp_idx = col_index(headers, 'Timestamp')
    month_idx     = col_index(headers, 'Select Month')
    branch_idx    = col_index(headers, 'Select Branch')
    if None in (timestamp_idx, month_idx, branch_idx):
        return 0, 0, set(), ['Missing required columns (Timestamp / Select Month / Select Branch)']

    col_metric = {}
    for i, h in enumerate(headers):
        if h is None:
            continue
        h_str = str(h).strip()
        metric_name = GOOGLE_FORMS_STATS_MAP.get(h_str)
        if metric_name:
            m = metric_lookup.get(metric_name)
            if m and m.id not in sirsi_metric_ids:
                col_metric[i] = m

    # Rows are in ascending timestamp order; later rows overwrite earlier ones
    # for the same branch+month (picks up the most recent correction).
    buckets = {}
    skipped_branches = set()
    bad_rows = 0

    for row in rows[1:]:
        if all(v is None for v in row):
            continue

        timestamp   = row[timestamp_idx]
        month_name  = row[month_idx]
        branch_name = row[branch_idx]

        if not isinstance(timestamp, datetime):
            bad_rows += 1
            continue

        month = parse_month(month_name)
        if not month or not branch_name:
            bad_rows += 1
            continue

        branch_name = str(branch_name).strip()
        if 'system wide' in branch_name.lower():
            continue

        branch = branch_lookup.get(branch_name) or branch_lookup.get(branch_name.lower())
        if branch is None:
            skipped_branches.add(branch_name)
            continue

        sub_year = timestamp.year
        year = sub_year - 1 if month > timestamp.month else sub_year

        is_rock_hill = 'rock hill' in branch.name.lower()
        key = (year, month, branch.id)
        if key not in buckets:
            buckets[key] = {}
        for i, val in enumerate(row):
            if i in col_metric and val is not None:
                m = col_metric[i]
                if m.name in _MAIN_ONLY_METRIC_NAMES and not is_rock_hill:
                    continue
                try:
                    buckets[key][m.id] = float(val)
                except (ValueError, TypeError):
                    pass

    warnings = [f'Unrecognised branch skipped: {b}' for b in sorted(skipped_branches)]
    if bad_rows:
        warnings.append(f'{bad_rows} rows skipped (unparseable timestamp or missing month/branch)')

    created = updated = 0
    for (year, month, branch_id), values in buckets.items():
        if not values:
            continue
        entry = Entry.query.filter_by(
            category_id=cat.id, branch_id=branch_id, year=year, month=month
        ).first()
        if entry is None:
            entry = Entry(category_id=cat.id, branch_id=branch_id,
                          year=year, month=month, submitted_by='Excel Import')
            db.session.add(entry)
            db.session.flush()
            created += 1
        else:
            updated += 1
        ev_map = {ev.metric_id: ev for ev in entry.values}
        for metric_id, val in values.items():
            ev = ev_map.get(metric_id)
            if ev:
                ev.value_number = val
            else:
                db.session.add(EntryValue(entry_id=entry.id, metric_id=metric_id, value_number=val))

    db.session.commit()
    period_set = {(y, m) for y, m, _ in buckets.keys()}
    return created, updated, period_set, warnings


def import_online_stats(ws, cat, metric_lookup, year_override=None):
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
        year      = row[year_idx]  if year_idx  is not None else year_override
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

    created = updated = 0
    for (year, month), values in buckets.items():
        if not values:
            continue
        entry = Entry.query.filter_by(
            category_id=cat.id, branch_id=None, year=year, month=month
        ).first()
        if entry is None:
            entry = Entry(category_id=cat.id, year=year, month=month,
                          submitted_by='Excel Import')
            db.session.add(entry)
            db.session.flush()
            created += 1
        else:
            updated += 1
        ev_map = {ev.metric_id: ev for ev in entry.values}
        for metric_id, val in values.items():
            ev = ev_map.get(metric_id)
            if ev:
                ev.value_number = val
            else:
                db.session.add(EntryValue(entry_id=entry.id, metric_id=metric_id, value_number=val))

    db.session.commit()
    return created, updated, []


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
    'YCL-BK':     'Bookmobile/Outreach',
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
_ADULT_PROFILES   = {'ADULT', 'A-NONRES', 'INST-TEACH', 'TEEN', 'COLLEGE', 'HOMEBOUND',
                     'J-ADULT'}       # juvenile patron aged up to adult status
_JUVENILE_PROFILES = {'JUVENILE', 'J-INTERNET', 'J-RESTRICT', 'JR-NONRES',
                      'TEMP-INET',    # temporary internet-only juvenile card
                      'JR-RECIP'}     # junior reciprocal borrower

# Door count location name → Branch.name
DOOR_COUNT_BRANCH_MAP = {
    'Clover Library':           'Clover',
    'Fort Mill Library':        'Fort Mill',
    'Lake Wylie Library':       'Lake Wylie',
    'Main - Rock Hill Library': 'Rock Hill',
    'York Library':             'York',
}


# Printing location string → Branch.name (substring match, lowercased)
PRINTING_BRANCH_MAP = {
    'lake wylie': 'Lake Wylie',
    'clover':     'Clover',
    'fort mill':  'Fort Mill',
    'rock hill':  'Rock Hill',
    'york':       'York',
}

# Page-count columns in the printing export
PRINTING_PAGE_COLS = [
    'Letter color pages', 'Letter monochrome pages',
    'Legal color pages',  'Legal monochrome pages',
    'Ledger color pages', 'Ledger monochrome pages',
]


def import_printing(ws, branch_lookup):
    """
    Parse a printing export.
    Sums all page-type columns per branch per month → Total Prints per Month.
    """
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return 0, ['Empty sheet']

    headers = list(rows[0])

    def ci(name):
        try: return headers.index(name)
        except ValueError: return None

    loc_idx   = ci('Location')
    from_idx  = ci('From')
    docs_idx  = ci('Documents')
    page_idxs = [ci(c) for c in PRINTING_PAGE_COLS if ci(c) is not None]

    if loc_idx is None or from_idx is None or (not page_idxs and docs_idx is None):
        return 0, 0, ['Unrecognised printing format — expected Location, From, and page or Documents columns']

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
            (name for key, name in PRINTING_BRANCH_MAP.items() if key in loc_lower),
            None
        )
        if not branch_name:
            unrecognised.add(str(loc).strip())
            continue
        branch = branch_lookup.get(branch_name)
        if not branch:
            unrecognised.add(branch_name)
            continue

        if page_idxs:
            pages = sum(int(r[i]) for i in page_idxs if isinstance(r[i], (int, float)))
        elif docs_idx is not None and isinstance(r[docs_idx], (int, float)):
            pages = int(r[docs_idx])
        else:
            continue
        totals[(year, month, branch.id)] += pages

    warnings = [f'Unrecognised locations skipped: {sorted(unrecognised)}'] if unrecognised else []
    created = updated = 0
    for (year, month, branch_id), total in totals.items():
        r = _upsert_branch_stat(cat.id, branch_id, year, month, prints_metric.id, total)
        if r == 'created': created += 1
        else: updated += 1
    period_set = {(y, m) for y, m, _ in totals.keys()}
    db.session.commit()
    return created, updated, period_set, warnings


# ── LPTOne / Princh "Branch Print Summary" export ─────────────────────────────
#
# Some libraries release prints through LPTOne at the desk (mobile "Princh" jobs
# are rolled into the same totals). Their export is one row per branch with no
# date column — the period comes from the file name (e.g. YCL_Print_Summary_June2026).
#
# Each spreadsheet column is tracked as its own Branch Stats metric, per branch,
# per month. "Printed Pages" continues the existing "Total Prints per Month"
# series so the historical Princh data and new data combine into one line.
PRINT_SUMMARY_COL_MAP = {
    'Printed Pages': 'Total Prints per Month',   # existing metric — combines old + new
    'Printed Jobs':  'Printed Jobs',
    'Printed Cost':  'Printed Cost',
}

# New metrics this importer may need to create (name → (group, data_type)).
PRINT_SUMMARY_NEW_METRICS = {
    'Printed Jobs': ('Access & Usage', 'integer'),
    'Printed Cost': ('Access & Usage', 'decimal'),
}

_MONTH_NAMES = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
    'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11,
    'december': 12,
}


def parse_period_from_filename(filename):
    """
    Pull (year, month) out of a file name for exports that carry no date column.
    Handles 'June2026', 'June_2026', 'June 2026', '2026-06', '2026_06'.
    Returns (year, month) or (None, None).
    """
    if not filename:
        return None, None
    name = str(filename)

    # Month name followed (optionally) by a 4-digit year, e.g. 'June2026'
    m = re.search(
        r'(january|february|march|april|may|june|july|august|september|'
        r'october|november|december)[ _-]*((?:19|20)\d{2})',
        name, re.IGNORECASE)
    if m:
        return int(m.group(2)), _MONTH_NAMES[m.group(1).lower()]

    # Numeric YYYY-MM / YYYY_MM
    m = re.search(r'((?:19|20)\d{2})[ _-](0[1-9]|1[0-2])', name)
    if m:
        return int(m.group(1)), int(m.group(2))

    return None, None


def _ensure_metric(cat_id, name, group_name, data_type):
    """
    Find-or-create a Metric row (production DBs have no migration tool, so new
    metrics are added idempotently on first use). Returns the Metric.
    """
    m = Metric.query.filter_by(category_id=cat_id, name=name).first()
    if m:
        return m
    max_sort = db.session.query(db.func.max(Metric.sort_order)).filter_by(
        category_id=cat_id).scalar() or 0
    m = Metric(category_id=cat_id, name=name, group_name=group_name,
               data_type=data_type, sort_order=max_sort + 1)
    db.session.add(m)
    db.session.flush()
    return m


def import_print_summary(ws, branch_lookup, year, month):
    """
    Parse an LPTOne / Princh 'Branch Print Summary' export: one row per branch
    with Printed Jobs / Printed Pages / Printed Cost columns. Period comes from
    the caller (parsed from the file name).

    Each recognised column is upserted as its own Branch Stats metric per branch.
    Returns (created, updated, period_set, warnings).
    """
    if not (year and month):
        return 0, 0, set(), ['Could not determine month/year — expected it in the '
                             'file name (e.g. YCL_Print_Summary_June2026.xlsx)']

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return 0, 0, set(), ['Empty sheet']

    # The header row may not be the first row (some exports have title rows above).
    header = header_idx = None
    for i, r in enumerate(rows[:6]):
        vals = [str(v).strip() if v is not None else '' for v in r]
        if 'Branch' in vals and 'Printed Pages' in vals:
            header, header_idx = vals, i
            break
    if header is None:
        return 0, 0, set(), ['Unrecognised print summary format — expected a '
                             '"Branch" + "Printed Pages" header row']

    branch_col = header.index('Branch')
    # Map each recognised column index → metric name
    col_to_metric = {header.index(col): metric
                     for col, metric in PRINT_SUMMARY_COL_MAP.items()
                     if col in header}

    cat = Category.query.filter_by(name='Branch Stats').first()
    if not cat:
        return 0, 0, set(), ['Branch Stats category not found']

    # Resolve (creating if needed) the metric object for each mapped column.
    metric_ids = {}
    for col_idx, metric_name in col_to_metric.items():
        spec = PRINT_SUMMARY_NEW_METRICS.get(metric_name)
        if spec:
            metric = _ensure_metric(cat.id, metric_name, spec[0], spec[1])
        else:
            metric = Metric.query.filter_by(category_id=cat.id, name=metric_name).first()
        if metric:
            metric_ids[col_idx] = metric.id

    created = updated = 0
    unrecognised = set()
    period_set = set()

    for r in rows[header_idx + 1:]:
        if r is None or all(v is None for v in r):
            continue
        raw = r[branch_col]
        if raw is None:
            continue
        # 'Rock Hill*' / 'Rock Hill (RH)' → strip footnote marks/suffixes for matching
        loc_lower = str(raw).strip().rstrip('*').strip().lower()
        if not loc_lower or loc_lower in ('total', 'totals'):
            continue

        branch_name = next(
            (name for key, name in PRINTING_BRANCH_MAP.items() if key in loc_lower),
            None)
        branch = branch_lookup.get(branch_name) if branch_name else None
        if not branch:
            unrecognised.add(str(raw).strip())
            continue

        for col_idx, metric_id in metric_ids.items():
            val = r[col_idx] if col_idx < len(r) else None
            if not isinstance(val, (int, float)):
                continue
            res = _upsert_branch_stat(cat.id, branch.id, year, month, metric_id, val)
            if res == 'created': created += 1
            else: updated += 1
        period_set.add((year, month))

    warnings = ([f'Unrecognised branches skipped: {sorted(unrecognised)}']
                if unrecognised else [])
    db.session.commit()
    return created, updated, period_set, warnings


# PC Reservation (EnvisionWare) branch-name variants → canonical branch name.
PCRES_BRANCH_MAP = {
    'clover':     'Clover',
    'fort mill':  'Fort Mill',
    'lake wylie': 'Lake Wylie',
    'rock hill':  'Rock Hill',
    'york':       'York',
}


def import_pc_reservations(ws, branch_lookup, year_override=None):
    """
    Parse a PC Reservation usage sheet → the 'PC Reservations' metric in Branch Stats.

    Expects one row per branch per month with columns (header row, any order):
        Branch | Year | Month | Total Uses
    A leading title/metadata block above the header is tolerated. Extra columns
    (Total Time, Average Session, etc.) and any 'TOTALS' rows are ignored.

    Sums 'Total Uses' per (branch, year, month) and upserts into PC Reservations.
    Upsert semantics: existing months/branches are overwritten in place, other
    data is never touched, and re-running the same file is a no-op. Returns
    (created, updated, period_set, warnings).
    """
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return 0, 0, set(), ['Empty sheet']

    # Locate the header row (first row containing a 'Branch' cell) so a title
    # block above the table doesn't break parsing.
    header_i = next((i for i, r in enumerate(rows)
                     if any(v is not None and str(v).strip().lower() == 'branch' for v in r)), None)
    if header_i is None:
        return 0, 0, set(), ['Unrecognised PC Reservations format — no "Branch" header found']

    headers = [str(v).strip().lower() if v is not None else '' for v in rows[header_i]]

    def ci(*names):
        for n in names:
            if n in headers:
                return headers.index(n)
        return None

    branch_idx = ci('branch')
    year_idx   = ci('year')
    month_idx  = ci('month')
    uses_idx   = ci('total uses', 'pc reservations', 'uses')
    if branch_idx is None or uses_idx is None:
        return 0, 0, set(), ['Unrecognised PC Reservations format — expected Branch and Total Uses columns']

    metric_lookup, cat = build_metric_lookup('Branch Stats')
    pc_metric = metric_lookup.get('PC Reservations')
    if not cat or not pc_metric:
        return 0, 0, set(), ['Branch Stats or "PC Reservations" metric not found']

    from collections import defaultdict
    totals = defaultdict(int)      # (year, month, branch_id) → total uses
    unrecognised = set()
    warnings = []

    for r in rows[header_i + 1:]:
        if all(v is None for v in r):
            continue
        branch_val = r[branch_idx] if branch_idx < len(r) else None
        uses_val   = r[uses_idx]   if uses_idx   < len(r) else None
        if not branch_val or not isinstance(uses_val, (int, float)):
            continue
        # Skip any TOTALS / summary rows that slip in.
        if str(branch_val).strip().lower().startswith('total'):
            continue

        # Year / month: prefer explicit columns, fall back to upload year override.
        year = None
        if year_idx is not None and year_idx < len(r) and isinstance(r[year_idx], (int, float)):
            year = int(r[year_idx])
        elif year_override:
            year = year_override
        month = None
        if month_idx is not None and month_idx < len(r) and isinstance(r[month_idx], (int, float)):
            month = int(r[month_idx])
        if not year or not month or not (1 <= month <= 12):
            warnings.append(f'Skipped row with missing/invalid year or month: {branch_val}')
            continue

        # Match branch name (case-insensitive, tolerant of extra words).
        bl = str(branch_val).strip().lower()
        branch_name = PCRES_BRANCH_MAP.get(bl) or next(
            (name for key, name in PCRES_BRANCH_MAP.items() if key in bl), None)
        branch = branch_lookup.get(branch_name) if branch_name else branch_lookup.get(bl)
        if not branch:
            unrecognised.add(str(branch_val).strip())
            continue

        totals[(year, month, branch.id)] += int(uses_val)

    if unrecognised:
        warnings.append(f'Unrecognised branches skipped: {sorted(unrecognised)}')

    created = updated = 0
    for (year, month, branch_id), total in totals.items():
        res = _upsert_branch_stat(cat.id, branch_id, year, month, pc_metric.id, total)
        if res == 'created': created += 1
        else: updated += 1
    period_set = {(y, m) for y, m, _ in totals.keys()}
    db.session.commit()
    return created, updated, period_set, warnings


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
        if location in ('Total', 'Number of Checkouts'):
            continue
        if profile == 'Total' or profile == 'Trans Stat User Profile Name':
            continue
        if profile is None and location is None:
            continue  # grand-total summary rows (e.g. "Total  231280") — not transaction data
        if profile and str(profile).strip() in INTERNAL_PROFILES:
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

    # Write Total Branch Circulation into Branch Stats (per branch + system-wide).
    # Uses find-or-create so other manually entered stats (Gate Count, etc.) are preserved.
    bs_metrics, bs_cat   = build_metric_lookup('Branch Stats')
    total_circ_metric    = bs_metrics.get('Total Branch Circulation')
    hotspot_metric       = bs_metrics.get('Hotspots Circulation')
    circ_entries = 0

    if bs_cat and total_circ_metric:
        # Aggregate: total circ = checkouts + renewals; hotspots = hotspot checkouts only
        branch_totals = {}  # branch_id → [total_circ, hotspots]
        for (branch_id, patron_type, shelving_location), (chk, ren) in detail.items():
            if branch_id not in branch_totals:
                branch_totals[branch_id] = [0, 0]
            branch_totals[branch_id][0] += chk + ren
            if shelving_location == 'A-HOTSPOT':
                branch_totals[branch_id][1] += chk

        for branch_id, (total_circ, hot) in branch_totals.items():
            entry = (Entry.query
                     .filter_by(category_id=bs_cat.id, branch_id=branch_id, year=year, month=month)
                     .first())
            if not entry:
                entry = Entry(category_id=bs_cat.id, branch_id=branch_id,
                              year=year, month=month, submitted_by='SIRSI Import')
                db.session.add(entry)
                db.session.flush()

            ev = EntryValue.query.filter_by(entry_id=entry.id, metric_id=total_circ_metric.id).first()
            if ev:
                ev.value_number = total_circ
            else:
                db.session.add(EntryValue(entry_id=entry.id, metric_id=total_circ_metric.id, value_number=total_circ))

            if hotspot_metric and hot:
                ev_h = EntryValue.query.filter_by(entry_id=entry.id, metric_id=hotspot_metric.id).first()
                if ev_h:
                    ev_h.value_number = hot
                else:
                    db.session.add(EntryValue(entry_id=entry.id, metric_id=hotspot_metric.id, value_number=hot))

            circ_entries += 1

    # Write Locker Circulation (checkouts + renewals) to parent branch entries.
    locker_metric = bs_metrics.get('Locker Circulation')
    if bs_cat and locker_metric and branch_totals:
        locker_to_parent = {}
        for code, name in ILS_BRANCH_MAP.items():
            if not code.endswith('-LOC'):
                continue
            parent_name = name.replace(' - Lockers', '')
            locker_b = branch_lookup.get(name) or branch_lookup.get(name.lower())
            parent_b = branch_lookup.get(parent_name) or branch_lookup.get(parent_name.lower())
            if locker_b and parent_b:
                locker_to_parent[locker_b.id] = parent_b.id

        for branch_id, (locker_circ, _) in branch_totals.items():
            parent_id = locker_to_parent.get(branch_id)
            if parent_id is None or not locker_circ:
                continue
            entry = (Entry.query
                     .filter_by(category_id=bs_cat.id, branch_id=parent_id, year=year, month=month)
                     .first())
            if not entry:
                entry = Entry(category_id=bs_cat.id, branch_id=parent_id,
                              year=year, month=month, submitted_by='SIRSI Import')
                db.session.add(entry)
                db.session.flush()
            ev_l = EntryValue.query.filter_by(entry_id=entry.id, metric_id=locker_metric.id).first()
            if ev_l:
                ev_l.value_number = locker_circ
            else:
                db.session.add(EntryValue(entry_id=entry.id, metric_id=locker_metric.id, value_number=locker_circ))

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
    total_metric    = metric_lookup.get('New Library Card Registrations, Total')
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
        if not ils.startswith('YCL-'):
            continue
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
        if total_metric and (adult or juvenile):
            r = _upsert_branch_stat(cat.id, branch_id, year, month, total_metric.id, adult + juvenile)
            if r == 'created': created += 1
            else: updated += 1

    db.session.commit()
    return created, updated, warnings


def import_door_count(ws, branch_lookup):
    """
    Parse a daily door count sheet (hourly ins/outs per branch).
    Sums 'Outs' per branch per month and updates Gate Count in Branch Stats.
    """
    rows = list(ws.iter_rows(values_only=True))

    metric_lookup, cat = build_metric_lookup('Branch Stats')
    gate_metric = metric_lookup.get('Gate Count')
    if not cat or not gate_metric:
        return 0, 0, set(), ['Branch Stats or Gate Count metric not found']

    # Locate columns by header name so the parser works regardless of column
    # order or a leading index column being present.
    header_idx = next((i for i, r in enumerate(rows)
                       if any(v is not None and 'Location Name' in str(v) for v in r)), None)
    if header_idx is None:
        return 0, 0, set(), ['Header row with "Location Name" not found']

    header = [str(v).strip() if v is not None else '' for v in rows[header_idx]]
    loc_col  = next((i for i, h in enumerate(header) if h == 'Location Name'), None)
    date_col = next((i for i, h in enumerate(header) if h in ('Record Date', 'Date')), None)
    outs_col = next((i for i, h in enumerate(header) if h == 'Outs'), None)
    if loc_col is None or date_col is None or outs_col is None:
        return 0, 0, set(), ['Could not find Location Name / Record Date / Outs columns']

    from collections import defaultdict
    monthly_outs = defaultdict(lambda: defaultdict(int))  # (year,month) → branch_id → total

    for r in rows[header_idx + 1:]:
        loc_name = r[loc_col]  if loc_col  < len(r) else None
        date     = r[date_col] if date_col < len(r) else None
        outs     = r[outs_col] if outs_col < len(r) else None
        if not isinstance(outs, (int, float)) or outs == 0:
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

        monthly_outs[(date.year, date.month)][branch.id] += int(outs)

    created = updated = 0
    for (year, month), branch_totals in monthly_outs.items():
        for branch_id, total in branch_totals.items():
            r = _upsert_branch_stat(cat.id, branch_id, year, month, gate_metric.id, total)
            if r == 'created': created += 1
            else: updated += 1

    db.session.commit()
    period_set = set(monthly_outs.keys())
    return created, updated, period_set, []


def detect_and_import(wb, year_override=None, filename=None):
    """
    Auto-detect the report type from a workbook and route to the correct importer.
    Returns a list of result dicts for display.
    Must be called within an active Flask app context.

    filename is used by date-less exports (e.g. the print summary) to recover the
    period, and by the Year field on the upload form as a fallback/override.
    """
    branch_lookup = build_branch_lookup()
    results = []

    # Detect Annual Comparables format: 'OPERATIONS' sheet with 'REPORT YEAR' header
    if 'OPERATIONS' in wb.sheetnames:
        first_row = next(wb['OPERATIONS'].iter_rows(min_row=1, max_row=1, values_only=True), ())
        if first_row and str(first_row[0]).strip() == 'REPORT YEAR':
            from import_annual import import_annual_comparables
            import tempfile, os
            with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
                tmp_path = tmp.name
            try:
                wb.save(tmp_path)
                created, updated = import_annual_comparables(tmp_path)
            finally:
                os.unlink(tmp_path)
            results.append({
                'sheet': 'Annual Comparables',
                'created': created, 'updated': updated, 'skipped': 0,
                'note': f'{created} values created, {updated} updated across all sections',
                'year': None, 'month': None,
            })
            return results

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))

        # Find first non-blank cell to identify report type
        title = next((str(r[0]) for r in rows if r[0] is not None), '')
        header_row = [str(v) for v in (rows[0] if rows else []) if v is not None]

        if 'Checkouts by Branch and User Profile' in title:
            det, year, month, w = import_sirsi_user_profile(ws, branch_lookup)
            results.append({'sheet': 'SIRSI Checkouts (by User Profile)',
                             'created': det, 'updated': 0, 'skipped': 0, 'warnings': w,
                             'note': f'{det} adult/juvenile rows stored for {month}/{year}' if year else '',
                             'year': year, 'month': month})

        elif 'Checkouts by Branch and Shelving Location' in title:
            report_type, year, month = _detect_sirsi_report_type(rows)
            if year and month:
                det, circ, w = import_sirsi_checkouts(ws, year, month, branch_lookup)
                results.append({'sheet': 'SIRSI Checkouts (by Shelving Location)',
                                 'created': det, 'skipped': 0, 'warnings': w,
                                 'note': f'{circ} Circulation total entries written',
                                 'year': year, 'month': month})
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
                                 'created': created, 'updated': updated, 'skipped': 0, 'warnings': w,
                                 'year': year, 'month': month})
            else:
                results.append({'sheet': sheet_name, 'created': 0, 'updated': 0, 'skipped': 0,
                                 'warnings': ['Could not determine year/month from report']})

        elif any(
                {'Branch', 'Printed Pages'} <= {str(v).strip() for v in (r or []) if v is not None}
                for r in rows[:6]):
            year, month = parse_period_from_filename(filename)
            if year_override:
                year = year_override
            created, updated, periods, w = import_print_summary(ws, branch_lookup, year, month)
            results.append({'sheet': 'Branch Print Summary (Prints)',
                             'created': created, 'updated': updated, 'skipped': 0, 'warnings': w,
                             'periods': sorted(periods),
                             'note': (f'Printed Jobs, Pages & Cost stored for {month}/{year}'
                                      if year and month else ''),
                             'year':  (sorted(periods)[0][0] if periods else year),
                             'month': (sorted(periods)[0][1] if periods else month)})

        elif sheet_name == 'PC Reservations' or \
             ('Branch' in header_row and any(h in header_row for h in ('Total Uses', 'PC Reservations'))):
            created, updated, periods, w = import_pc_reservations(ws, branch_lookup, year_override)
            results.append({'sheet': 'PC Reservations',
                             'created': created, 'updated': updated, 'skipped': 0, 'warnings': w,
                             'periods': sorted(periods),
                             'year':  (sorted(periods)[0][0] if periods else None),
                             'month': (sorted(periods)[0][1] if periods else None)})

        elif (any(v is not None and 'Letter color pages' in str(v) for r in rows[:3] for v in r) or
              ('Location' in header_row and 'Documents' in header_row and 'From' in header_row)):
            created, updated, periods, w = import_printing(ws, branch_lookup)
            results.append({'sheet': 'Total Prints per Month (Printing)',
                             'created': created, 'updated': updated, 'skipped': 0, 'warnings': w,
                             'periods': sorted(periods)})

        elif any(v is not None and 'Location Name' in str(v)
                 for r in rows[:3] for v in r):
            created, updated, periods, w = import_door_count(ws, branch_lookup)
            results.append({'sheet': 'Gate Count (Door Counter)',
                             'created': created, 'updated': updated, 'skipped': 0, 'warnings': w,
                             'periods': sorted(periods)})

        elif sheet_name == 'Form Responses 1' and 'Timestamp' in header_row and 'Select Month' in header_row:
            bs_metrics, bs_cat = build_metric_lookup('Branch Stats')
            if bs_cat:
                c, u, periods, w = import_google_forms_stats(ws, bs_cat, bs_metrics, branch_lookup)
                results.append({'sheet': 'Google Forms Branch Stats',
                                 'created': c, 'updated': u, 'skipped': 0, 'warnings': w,
                                 'periods': sorted(periods)})
            else:
                results.append({'sheet': sheet_name, 'created': 0, 'skipped': 0,
                                 'warnings': ['Branch Stats category not found in DB']})

        elif sheet_name in ('Branch Stats', 'Online Stats', 'Qrtly Ref Stats') or \
             any(sheet_name in wb.sheetnames for sheet_name in ('Branch Stats', 'Online Stats')):
            # Standard stats workbook — use do_import
            results.extend(do_import(wb, year_override))
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

def do_import(wb, year_override=None):
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
        c, s, periods, w = import_branch_stats(wb['Branch Stats'], cat, metric_lookup, branch_lookup, year_override)
        results.append({'sheet': 'Branch Stats', 'created': c, 'skipped': s, 'warnings': w,
                        'periods': sorted(periods)})
    elif 'Branch Stats' not in wb.sheetnames:
        results.append({'sheet': 'Branch Stats', 'created': 0, 'skipped': 0,
                        'warnings': ['Sheet "Branch Stats" not found in workbook']})

    # Online Stats
    metric_lookup, cat = build_metric_lookup('Online Stats')
    if cat and 'Online Stats' in wb.sheetnames:
        c, s, w = import_online_stats(wb['Online Stats'], cat, metric_lookup, year_override)
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
