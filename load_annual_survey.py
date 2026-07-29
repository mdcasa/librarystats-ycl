#!/usr/bin/env python3
"""
Import historical annual survey totals from Data files/OldConversion/
into the AnnualSurveyValue table.

Coverage:  FY2016–FY2024
  FY2024 is already in the DB; skip-if-exists logic protects existing values.

Metrics extracted (system-wide TOTAL rows):
    Annual Library Visits (gate count)
    Number of wireless sessions
    Number of Reference Transactions
    Interlibrary loans received from another library
    Interlibrary loans provided to another library
    Number of times library facilities were used by external parties

NOT in these files (enter via the Annual Survey form):
    Revenue, expenses, staffing, collection size, registered users,
    programming details — run Annual Survey → Calculate after loading
    monthly Branch Stats via load_old_conversion.py

Run:
    python load_annual_survey.py --dry-run
    python load_annual_survey.py
    python load_annual_survey.py --year 2023
"""

import os
import re
import sys
import argparse

import xlrd
from dotenv import load_dotenv

load_dotenv()

from app import app, db
from models import AnnualSurveyMetric, AnnualSurveyValue

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        'Data files', 'OldConversion')

# (filename, format, report_year, sheet_name, newer_year_label)
# format 'dedicated'  — one Stats sheet per FY; all rows belong to report_year
# format 'comparison' — two FYs interleaved; import only rows prefixed with newer_year_label,
#                       plus un-prefixed sections (Reference Statistics, Meeting rooms)
FILE_INDEX = [
    ('Annual stats FY 15-16-17.xls', 'dedicated',  2016, 'FY15-16',                       None),
    ('Annual stats FY 15-16-17.xls', 'dedicated',  2017, 'FY16-17 Stats',                 None),
    ('Annual stats FY 17-18.xls',    'dedicated',  2018, 'FY17-18 Stats',                  None),
    ('Annual stats FY 18-19.xls',    'dedicated',  2019, 'FY18-19 Stats',                  None),
    ('ANNUAL Stats 19-20.xls',       'comparison', 2020, '18-19 to 19-20 Comparison p.1', '19-20'),
    ('20-21 ANNUAL STATS.xls',       'comparison', 2021, '19-20 to 20-21 Comparison p.1', '20-21'),
    ('21-22 Annual Stats.xls',       'comparison', 2022, '20-21 to 21-22 Comparison p.1', '21-22'),
    ('22-23 Annual Stats.xls',       'comparison', 2023, '21-22 to 22-23 Comparison p.1', '22-23'),
    ('23-24 Annual Stats.xls',       'comparison', 2024, '22-23 to 23-24 Comparison p.1', '23-24'),
]

# Section label startswith → DB metric name (or '__ill__' for special handling)
_SECTION_MAP = [
    ('door count',                 'Annual Library Visits (gate count)'),
    ('internet usage (wifi)',      'Number of wireless sessions'),
    ('wi-fi sessions',             'Number of wireless sessions'),
    ('wifi sessions',              'Number of wireless sessions'),
    ('reference statistics',       'Number of Reference Transactions'),
    ('interlibrary loans',         '__ill__'),
    ('outside usage of meeting',   'Number of times library facilities were used by external parties'),
]

# ILL sub-row label → DB metric name
_ILL_SUBROW = {
    'borrowed': 'Interlibrary loans received from another library',
    'loaned':   'Interlibrary loans provided to another library',
}

_COMP_HDR_RE = re.compile(r'^\s*(\d{2}-\d{2})\s+(.+)')


# ── spreadsheet helpers ────────────────────────────────────────────────────────

def _cell(sh, r, c):
    if c >= sh.ncols:
        return ''
    v = sh.cell_value(r, c)
    return str(v).strip() if v != '' else ''


def _annual_sum(sh, r):
    """Sum of cols 3-14 (the 12 fiscal-month columns).

    Safer than reading col 15, which is sometimes a formula-projected value
    rather than an actual annual total (e.g. Reference Statistics in FY15-16).
    For quarterly metrics only 4 cells will be non-zero; for monthly all 12.
    Either way the sum equals the true annual count.
    """
    total = 0.0
    found = False
    for c in range(3, 15):
        if c >= sh.ncols:
            break
        try:
            v = sh.cell_value(r, c)
            if v != '' and v is not None:
                total += float(v)
                found = True
        except (ValueError, TypeError):
            pass
    return total if (found and total > 0) else None


def _match_section(raw_label):
    """Return DB metric name (or '__ill__') for a section label, or None."""
    norm = raw_label.lower().strip()
    for prefix, db_name in _SECTION_MAP:
        if norm.startswith(prefix):
            return db_name
    return None


# ── DB write ───────────────────────────────────────────────────────────────────

def _write(metrics, report_year, metric_name, value, dry_run, counters):
    if value is None or value <= 0:
        counters['skip_zero'] += 1
        return
    metric = metrics.get(metric_name)
    if metric is None:
        print(f'    WARN: metric not in DB: {metric_name!r}')
        return
    if AnnualSurveyValue.query.filter_by(
            report_year=report_year, metric_id=metric.id).first():
        counters['skip_exists'] += 1
        return
    if dry_run:
        print(f'    [DRY RUN] FY{report_year} | {metric_name} | {int(value):,}')
        counters['written'] += 1
        return
    db.session.add(AnnualSurveyValue(
        report_year=report_year,
        metric_id=metric.id,
        value=value,
    ))
    counters['written'] += 1


# ── sheet parser ───────────────────────────────────────────────────────────────

def parse_sheet(sh, report_year, metrics, dry_run, counters, newer_label=None):
    """
    Parse one worksheet.  newer_label=None → dedicated format (all rows apply).
    newer_label='XX-YY' → comparison format (only import newer-year sections
    plus un-prefixed sections).
    """
    current_metric = None
    in_ill = False

    for r in range(sh.nrows):
        col0 = _cell(sh, r, 0)
        col1 = _cell(sh, r, 1)
        col3 = _cell(sh, r, 3)

        # ── Section header: col3 must be the month-name 'July' ────────────
        if col3.lower().startswith('jul'):
            if newer_label:
                # Comparison format
                m = _COMP_HDR_RE.match(col0)
                if m:
                    year_lbl, section_lbl = m.group(1), m.group(2).strip()
                    if year_lbl == newer_label:
                        current_metric = _match_section(section_lbl)
                    else:
                        current_metric = None   # older-year block — skip
                    in_ill = (current_metric == '__ill__')
                    continue
                elif col0 and col1 == '':
                    # Un-prefixed section (Reference Statistics, Meeting rooms)
                    current_metric = _match_section(col0)
                    in_ill = (current_metric == '__ill__')
                    continue
            else:
                # Dedicated format — section header: col0=metric, col1=empty
                if col0 and col1 == '':
                    current_metric = _match_section(col0)
                    in_ill = (current_metric == '__ill__')
                    continue

        if current_metric is None:
            continue

        col1_lower = col1.lower().strip()
        col1_upper = col1.upper().strip()

        if in_ill:
            # ILL: capture Borrowed and Loaned sub-rows (skip TOTAL / IMS)
            db_name = _ILL_SUBROW.get(col1_lower)
            if db_name:
                _write(metrics, report_year, db_name,
                       _annual_sum(sh, r), dry_run, counters)
        else:
            # Accept TOTAL rows for all metrics; also accept YCL for WiFi
            # (older dedicated files track WiFi as a single system-wide YCL row)
            if col1_upper in ('TOTAL', 'YCL'):
                _write(metrics, report_year, current_metric,
                       _annual_sum(sh, r), dry_run, counters)


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview only; no DB writes')
    parser.add_argument('--year', type=int, default=0,
                        help='Process only this report_year (e.g. 2023)')
    args = parser.parse_args()
    dry_run = args.dry_run

    with app.app_context():
        metrics = {m.name: m for m in AnnualSurveyMetric.query.all()}
        print(f'Loaded {len(metrics)} AnnualSurveyMetric records')
        if dry_run:
            print('DRY RUN — no changes will be written\n')
        else:
            # Sync the PK sequence in case it's behind existing rows
            from sqlalchemy import text
            db.session.execute(text(
                "SELECT setval('annual_survey_values_id_seq', "
                "COALESCE((SELECT MAX(id) FROM annual_survey_values), 0))"
            ))
            db.session.commit()

        total = {'written': 0, 'skip_exists': 0, 'skip_zero': 0}

        for (filename, fmt, report_year, sheet_name, newer_label) in FILE_INDEX:
            if args.year and report_year != args.year:
                continue

            fpath = os.path.join(DATA_DIR, filename)
            if not os.path.exists(fpath):
                print(f'SKIP (not found): {filename}')
                continue

            print(f'\n=== FY{report_year}  {filename}  [{sheet_name}] ===')
            counters = {'written': 0, 'skip_exists': 0, 'skip_zero': 0}

            try:
                wb = xlrd.open_workbook(fpath)
                sh = wb.sheet_by_name(sheet_name)
            except Exception as e:
                print(f'  ERROR: {e}')
                continue

            print(f'  {sh.nrows} rows × {sh.ncols} cols')
            parse_sheet(sh, report_year, metrics, dry_run, counters,
                        newer_label=newer_label)

            if not dry_run:
                db.session.commit()
                print('  committed.')

            print(f'  → written={counters["written"]}  '
                  f'skip_exists={counters["skip_exists"]}  '
                  f'skip_zero={counters["skip_zero"]}')

            for k in total:
                total[k] += counters[k]

        print(f'\n{"DRY RUN " if dry_run else ""}TOTAL: '
              f'written={total["written"]}  '
              f'skip_exists={total["skip_exists"]}  '
              f'skip_zero={total["skip_zero"]}')


if __name__ == '__main__':
    main()
