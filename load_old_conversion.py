#!/usr/bin/env python3
"""
Load historical Branch Stats data from Data files/OldConversion/ into the database.

Run:
    python load_old_conversion.py --dry-run          # preview only, no DB writes
    python load_old_conversion.py                     # live import
    python load_old_conversion.py --file "17-18"      # only files matching substring

Metrics imported (FY2015-16 through FY2022-23):
    Gate Count, Total Branch Circulation,
    New Library Card Registrations Total, PC Reservations, WiFi - Unique Sessions
"""

import os
import re
import sys
import argparse

import xlrd
from dotenv import load_dotenv

load_dotenv()

from app import app, db
from models import Branch, Category, Metric, Entry, EntryValue

# ── paths ──────────────────────────────────────────────────────────────────────

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        'Data files', 'OldConversion')

# ── month mapping ──────────────────────────────────────────────────────────────
# Fiscal year: col 0 = July, col 11 = June

_MONTH_OFFSETS = [7, 8, 9, 10, 11, 12, 1, 2, 3, 4, 5, 6]


def fy_col_to_year_month(fy_start_year: int, col_idx: int):
    """col_idx 0=July … 11=June → (calendar_year, calendar_month)."""
    month = _MONTH_OFFSETS[col_idx]
    year = fy_start_year if col_idx < 6 else fy_start_year + 1
    return year, month


# ── lookup tables ──────────────────────────────────────────────────────────────

BRANCH_MAP = {
    'rock hill':             'Rock Hill',
    'rock hill (sdd site)': 'Rock Hill',
    'clover':                'Clover',
    'fort mill':             'Fort Mill',
    'lake wylie':            'Lake Wylie',
    'york':                  'York',
    'bookmobile/outreach':   'Bookmobile/Outreach',
    'bookmobile':            'Bookmobile/Outreach',
    'outreach':              'Bookmobile/Outreach',
}

# Old sheet label (lowercase, trailing notes stripped) → DB metric name
METRIC_LABEL_MAP = {
    'door count':                      'Gate Count',
    'door count (including curbside)': 'Gate Count',
    'new library cards':               'New Library Card Registrations, Total',
    'pc reservations':                 'PC Reservations',
    'internet usage (wifi)':           'WiFi - Unique Sessions',
    'wi-fi sessions':                  'WiFi - Unique Sessions',
    'wifi sessions':                   'WiFi - Unique Sessions',
}

# Section-header regex for comparison-format sheets: "XX-XX <metric name>"
_COMP_HDR_RE = re.compile(r'^\s*(\d{2}-\d{2})\s+(.+)')

# ── file list ──────────────────────────────────────────────────────────────────
# Tuple: (filename, format, fy_start_year, newer_label|None, main_sheet_name)
# 'dedicated' → one Stats sheet per FY, circ data lives on the same sheet.
# 'comparison' → year-prefixed rows on main sheet; circ on "Circ. Comparison p.2".

FILE_INDEX = [
    ('Annual stats FY 15-16-17.xls', 'dedicated',   2015, None,    'FY15-16'),
    ('Annual stats FY 15-16-17.xls', 'dedicated',   2016, None,    'FY16-17 Stats'),
    ('Annual stats FY 17-18.xls',    'dedicated',   2017, None,    'FY17-18 Stats'),
    ('Annual stats FY 18-19.xls',    'dedicated',   2018, None,    'FY18-19 Stats'),
    ('ANNUAL Stats 19-20.xls',       'comparison',  2019, '19-20', '18-19 to 19-20 Comparison p.1'),
    ('20-21 ANNUAL STATS.xls',       'comparison',  2020, '20-21', '19-20 to 20-21 Comparison p.1'),
    ('21-22 Annual Stats.xls',       'comparison',  2021, '21-22', '20-21 to 21-22 Comparison p.1'),
    ('22-23 Annual Stats.xls',       'comparison',  2022, '22-23', '21-22 to 22-23 Comparison p.1'),
]

# ── helpers ────────────────────────────────────────────────────────────────────

def _cell(sh, row, col):
    """Return trimmed string from cell, or '' for empty/out-of-range."""
    if col >= sh.ncols:
        return ''
    v = sh.cell_value(row, col)
    return str(v).strip() if v != '' else ''


def _num(sh, row, col):
    """Return float from cell, or None for empty / non-numeric."""
    if col >= sh.ncols:
        return None
    try:
        v = sh.cell_value(row, col)
        if v == '' or v is None:
            return None
        return float(v)
    except (ValueError, TypeError):
        return None


def _read_12_months(sh, row):
    """Read cols 3–14 (12 fiscal months) as floats, None for missing/empty."""
    return [_num(sh, row, c) for c in range(3, 15)]


# ── write helper ───────────────────────────────────────────────────────────────

def flush_buffer(buf, bs_cat_id, dry_run, counters):
    """
    Write all buffered data points to the DB.
    buf: {(branch_obj, metric_obj, year, month): accumulated_value}
    Values are pre-summed so Bookmobile+Outreach separate rows merge correctly.
    """
    for (branch_obj, metric_obj, year, month), value in sorted(
            buf.items(), key=lambda x: (x[0][0].name, x[0][1].name, x[0][2], x[0][3])):
        if value is None or value <= 0:
            counters['skip_zero'] += 1
            continue

        entry = Entry.query.filter_by(
            category_id=bs_cat_id,
            branch_id=branch_obj.id,
            year=year,
            month=month,
        ).first()

        if entry is None:
            if dry_run:
                print(f'    [DRY RUN] WRITE  {branch_obj.name} | '
                      f'{year}-{month:02d} | {metric_obj.name} | {int(value)}')
                counters['written'] += 1
                continue
            entry = Entry(
                category_id=bs_cat_id,
                branch_id=branch_obj.id,
                year=year,
                month=month,
                submitted_by='OldConversion Import',
            )
            db.session.add(entry)
            db.session.flush()

        ev = EntryValue.query.filter_by(
            entry_id=entry.id,
            metric_id=metric_obj.id,
        ).first()

        if ev is not None:
            counters['skip_exists'] += 1
            continue

        if dry_run:
            print(f'    [DRY RUN] WRITE  {branch_obj.name} | '
                  f'{year}-{month:02d} | {metric_obj.name} | {int(value)}')
            counters['written'] += 1
            continue

        db.session.add(EntryValue(
            entry_id=entry.id,
            metric_id=metric_obj.id,
            value_number=value,
        ))
        counters['written'] += 1


def _buf_add(buf, branch_obj, metric_obj, year, month, value):
    """Accumulate a value into the write buffer (sums duplicates like Bookmobile+Outreach)."""
    if value is None or value <= 0:
        return
    key = (branch_obj, metric_obj, year, month)
    buf[key] = (buf.get(key) or 0) + value


# ── dedicated-format parser ────────────────────────────────────────────────────

def parse_dedicated_sheet(sh, fy_start_year, bs_cat_id, branches, metrics,
                           dry_run, counters):
    """
    Parse a 'dedicated' format Stats sheet (FY15-16 through FY18-19).

    Layout:
      Row n:   <MetricLabel>  ''  ''  July  Aug  …  June  Total
      Row n+1: ''  <BranchName>  ''  val  val  …  val  total_col
      …
      Row m:   ''  TOTAL  ''  …
      (blank row)
      Row m+2: <NextMetricLabel> …

    Values from multiple source rows that map to the same DB branch (e.g. separate
    'Bookmobile' and 'Outreach' rows) are summed via the write buffer.
    """
    current_label = None
    # Buffers for summing Cataloged + Uncataloged circulation
    circ_cat   = {}   # {branch_db_name: [v or None, …]}  12 items
    circ_uncat = {}
    # Write buffer for all other metrics (deduplicates Bookmobile+Outreach)
    write_buf  = {}   # {(branch_obj, metric_obj, year, month): value}

    for r in range(sh.nrows):
        col0 = _cell(sh, r, 0)
        col1 = _cell(sh, r, 1)
        col3 = _cell(sh, r, 3)

        # Metric-header row: col0 non-empty, col3 = month name beginning with 'jul'
        if col0 and col3.lower().startswith('jul'):
            current_label = col0.lower().strip().rstrip('.')
            continue

        if not current_label:
            continue

        # Skip totals / summaries
        if not col1 or col1.upper() in ('TOTAL', 'GRAND TOTAL', 'ICL/CIRC'):
            continue

        branch_db = BRANCH_MAP.get(col1.strip().lower())
        if branch_db is None:
            continue   # sub-item, note, unrecognized name

        branch_obj = branches.get(branch_db)
        if branch_obj is None:
            continue

        vals = _read_12_months(sh, r)

        # Circulation rows: accumulate for later summing
        if 'inhouse' in current_label:
            continue   # in-library use — not counted in Total Branch Circulation

        if 'circs-cataloged' in current_label and 'uncataloged' not in current_label:
            buf = circ_cat.setdefault(branch_db, [None] * 12)
            for i, v in enumerate(vals):
                if v is not None:
                    buf[i] = (buf[i] or 0) + v
            continue

        if 'circs-uncataloged' in current_label:
            buf = circ_uncat.setdefault(branch_db, [None] * 12)
            for i, v in enumerate(vals):
                if v is not None:
                    buf[i] = (buf[i] or 0) + v
            continue

        # Regular metrics — accumulate into write buffer
        db_metric_name = METRIC_LABEL_MAP.get(current_label)
        if db_metric_name is None:
            continue

        metric_obj = metrics.get(db_metric_name)
        if metric_obj is None:
            continue

        for col_i, v in enumerate(vals):
            year, month = fy_col_to_year_month(fy_start_year, col_i)
            _buf_add(write_buf, branch_obj, metric_obj, year, month, v)

    # Fold Circulation into write buffer
    circ_metric = metrics.get('Total Branch Circulation')
    if circ_metric:
        all_circ_branches = set(circ_cat) | set(circ_uncat)
        for branch_db in all_circ_branches:
            branch_obj = branches.get(branch_db)
            if branch_obj is None:
                continue
            cat_vals = circ_cat.get(branch_db, [None] * 12)
            unc_vals = circ_uncat.get(branch_db, [None] * 12)
            for col_i in range(12):
                c = cat_vals[col_i]
                u = unc_vals[col_i]
                if c is None and u is None:
                    continue
                total = (c or 0) + (u or 0)
                year, month = fy_col_to_year_month(fy_start_year, col_i)
                _buf_add(write_buf, branch_obj, circ_metric, year, month, total)

    flush_buffer(write_buf, bs_cat_id, dry_run, counters)


# ── comparison-format parsers ──────────────────────────────────────────────────

def parse_comparison_main_sheet(sh, fy_start_year, newer_label,
                                 bs_cat_id, branches, metrics, dry_run, counters):
    """
    Parse the main p.1 sheet of a comparison-format file (FY19-20 through FY22-23).

    Only rows whose section header starts with <newer_label> are imported.
    """
    in_section = False
    current_db_metric_name = None
    write_buf = {}

    for r in range(sh.nrows):
        col0 = _cell(sh, r, 0)
        col3 = _cell(sh, r, 3)

        # Section-header row: "XX-XX <metric>" with col3 = 'July'
        m = _COMP_HDR_RE.match(col0)
        if m and col3.lower().startswith('jul'):
            if m.group(1) == newer_label:
                in_section = True
                raw = m.group(2).strip().lower()
                # Strip trailing parentheticals like "(including curbside)"
                raw = re.sub(r'\s*\(.*\)\s*$', '', raw).strip()
                current_db_metric_name = METRIC_LABEL_MAP.get(raw)
            else:
                in_section = False
            continue

        if not in_section or current_db_metric_name is None:
            continue

        col1 = _cell(sh, r, 1)
        if not col1 or col1.upper() in ('TOTAL', 'GRAND TOTAL', 'COMPARISON'):
            continue

        branch_db = BRANCH_MAP.get(col1.strip().lower())
        if branch_db is None:
            continue

        branch_obj = branches.get(branch_db)
        metric_obj = metrics.get(current_db_metric_name)
        if branch_obj is None or metric_obj is None:
            continue

        vals = _read_12_months(sh, r)
        for col_i, v in enumerate(vals):
            year, month = fy_col_to_year_month(fy_start_year, col_i)
            _buf_add(write_buf, branch_obj, metric_obj, year, month, v)

    flush_buffer(write_buf, bs_cat_id, dry_run, counters)


def parse_comparison_circ_sheet(sh, fy_start_year,
                                  bs_cat_id, branches, metrics, dry_run, counters):
    """
    Parse the 'Circ. Comparison p.2' sheet of a comparison-format file.

    The branch-level Cataloged and Uncataloged rows on this sheet always belong
    to the newer year (confirmed by the 'XX-XX CIRC TOTAL' row at the bottom).
    """
    current_label = None
    circ_cat   = {}
    circ_uncat = {}

    for r in range(sh.nrows):
        col0 = _cell(sh, r, 0)
        col1 = _cell(sh, r, 1)
        col3 = _cell(sh, r, 3)

        # Section-header row: col0 non-empty, col1 empty, col3 = 'July'
        if col0 and col1 == '' and col3.lower().startswith('jul'):
            current_label = col0.lower().strip()
            continue

        if not current_label:
            continue

        if not col1 or col1.upper() in ('TOTAL', 'GRAND TOTAL', 'COMPARISON'):
            continue

        # Skip INHOUSE rows
        if 'inhouse' in current_label:
            continue

        branch_db = BRANCH_MAP.get(col1.strip().lower())
        if branch_db is None:
            continue

        vals = _read_12_months(sh, r)

        if 'circs-cataloged' in current_label and 'uncataloged' not in current_label:
            buf = circ_cat.setdefault(branch_db, [None] * 12)
            for i, v in enumerate(vals):
                if v is not None:
                    buf[i] = (buf[i] or 0) + v

        elif 'circs-uncataloged' in current_label:
            buf = circ_uncat.setdefault(branch_db, [None] * 12)
            for i, v in enumerate(vals):
                if v is not None:
                    buf[i] = (buf[i] or 0) + v

    # Fold into write buffer and flush
    circ_metric = metrics.get('Total Branch Circulation')
    if not circ_metric:
        return

    write_buf = {}
    all_circ_branches = set(circ_cat) | set(circ_uncat)
    for branch_db in all_circ_branches:
        branch_obj = branches.get(branch_db)
        if branch_obj is None:
            continue
        cat_vals = circ_cat.get(branch_db, [None] * 12)
        unc_vals = circ_uncat.get(branch_db, [None] * 12)
        for col_i in range(12):
            c = cat_vals[col_i]
            u = unc_vals[col_i]
            if c is None and u is None:
                continue
            total = (c or 0) + (u or 0)
            year, month = fy_col_to_year_month(fy_start_year, col_i)
            _buf_add(write_buf, branch_obj, circ_metric, year, month, total)

    flush_buffer(write_buf, bs_cat_id, dry_run, counters)


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true',
                        help='Print what would be written; make no DB changes')
    parser.add_argument('--file', default='',
                        help='Only process filenames containing this substring')
    args = parser.parse_args()
    dry_run = args.dry_run
    file_filter = args.file.lower()

    with app.app_context():
        bs_cat = Category.query.filter_by(name='Branch Stats').first()
        if not bs_cat:
            sys.exit('ERROR: Branch Stats category not found in DB')

        # Load all active Branch Stats metrics by name
        metrics = {
            m.name: m
            for m in Metric.query.filter_by(
                category_id=bs_cat.id, is_active=True
            ).all()
        }

        # Load real service branches (exclude lockers, desks, system-wide)
        branches = {
            b.name: b
            for b in Branch.query.filter(
                Branch.is_active == True,
                Branch.is_desk == False,
                ~Branch.name.ilike('%locker%'),
                Branch.name != 'YCL (System Wide)',
                Branch.name != 'Administration',
            ).all()
        }

        print(f'Loaded {len(metrics)} metrics, {len(branches)} branches')
        if dry_run:
            print('DRY RUN — no changes will be written\n')

        total_counters = {'written': 0, 'skip_exists': 0, 'skip_zero': 0}

        for (filename, fmt, fy_start, newer_label, main_sheet) in FILE_INDEX:
            if file_filter and file_filter not in filename.lower():
                continue

            fpath = os.path.join(DATA_DIR, filename)
            if not os.path.exists(fpath):
                print(f'SKIP (not found): {filename}')
                continue

            print(f'\n=== {filename}  (FY{fy_start}-{str(fy_start+1)[2:]}  {fmt}) ===')
            counters = {'written': 0, 'skip_exists': 0, 'skip_zero': 0}

            try:
                wb = xlrd.open_workbook(fpath)
            except Exception as e:
                print(f'  ERROR opening workbook: {e}')
                continue

            if fmt == 'dedicated':
                try:
                    sh = wb.sheet_by_name(main_sheet)
                except xlrd.XLRDError:
                    print(f'  ERROR: sheet "{main_sheet}" not found '
                          f'(available: {wb.sheet_names()})')
                    continue
                print(f'  Sheet: {main_sheet}  ({sh.nrows} rows)')
                parse_dedicated_sheet(sh, fy_start, bs_cat.id,
                                       branches, metrics, dry_run, counters)

            elif fmt == 'comparison':
                # Main sheet (non-circ metrics)
                try:
                    sh_main = wb.sheet_by_name(main_sheet)
                    print(f'  Main sheet: {main_sheet}  ({sh_main.nrows} rows)')
                    parse_comparison_main_sheet(
                        sh_main, fy_start, newer_label,
                        bs_cat.id, branches, metrics, dry_run, counters)
                except xlrd.XLRDError as e:
                    print(f'  ERROR (main sheet): {e}')

                # Circulation sheet
                circ_sheet_name = 'Circ. Comparison p.2'
                try:
                    sh_circ = wb.sheet_by_name(circ_sheet_name)
                    print(f'  Circ sheet: {circ_sheet_name}  ({sh_circ.nrows} rows)')
                    parse_comparison_circ_sheet(
                        sh_circ, fy_start,
                        bs_cat.id, branches, metrics, dry_run, counters)
                except xlrd.XLRDError as e:
                    print(f'  ERROR (circ sheet): {e}')

            print(f'  → written={counters["written"]}  '
                  f'skip_exists={counters["skip_exists"]}  '
                  f'skip_zero={counters["skip_zero"]}')

            if not dry_run:
                db.session.commit()
                print('  committed.')

            for k in total_counters:
                total_counters[k] += counters[k]

        print(f'\n{"DRY RUN " if dry_run else ""}TOTAL: '
              f'written={total_counters["written"]}  '
              f'skip_exists={total_counters["skip_exists"]}  '
              f'skip_zero={total_counters["skip_zero"]}')


if __name__ == '__main__':
    main()
