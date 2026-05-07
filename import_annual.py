"""
One-time (and repeatable) import of Annual Comparables.xlsx into AnnualSurveyMetric
and AnnualSurveyValue tables.

Run with:
    python3 import_annual.py

Applies data-quality corrections:
  - ILL 2024: averaged from 2022 and 2023
  - Programming 2018: averaged from 2017 and 2019
  - Gate Count 2013: averaged from 2012 and 2014
  - Programming 2014-2016 children attendance: back-calculated from total
"""

from dotenv import load_dotenv
load_dotenv()

import openpyxl
from app import app, db
from models import AnnualSurveyMetric, AnnualSurveyValue

# ---------------------------------------------------------------------------
# Metric definitions: (section, name, data_type, is_auto_calculated, note)
# ---------------------------------------------------------------------------
METRIC_DEFS = [
    # OPERATIONS
    ('OPERATIONS', 'Total Systemwide Annual Weekend / Evening Hours', 'integer', False, None),
    ('OPERATIONS', 'Total Systemwide Annual Hours',                    'integer', False, None),
    ('OPERATIONS', 'Number of Library Trustees',                       'integer', False, None),
    ('OPERATIONS', 'Regular Board Meetings',                           'integer', False, None),
    ('OPERATIONS', 'Does the library have a FOL group?',               'text',    False, None),
    ('OPERATIONS', 'Number of FOL groups',                             'integer', False, None),
    ('OPERATIONS', 'Friends Members all groups',                       'integer', False, None),

    # STAFFING
    ('STAFFING', 'MLIS Librarian Positions: Full Time',              'integer', False, None),
    ('STAFFING', 'MLIS Librarian Positions: Part time',              'integer', False, None),
    ('STAFFING', 'Librarian positions: MLIS FTE',                    'decimal', False, None),
    ('STAFFING', 'Full Time Funded Other Librarian Positions',       'integer', False, None),
    ('STAFFING', 'Part Time Funded Other Librarian Positions',       'integer', False, None),
    ('STAFFING', 'FTE Other Librarians',                             'decimal', False, None),
    ('STAFFING', 'Librarian positions: BA/BS Full time',             'integer', False, None),
    ('STAFFING', 'Librarian positions: BA/BS Part time',             'integer', False, None),
    ('STAFFING', 'Librarian positions: BA/BS FTE',                   'decimal', False, None),
    ('STAFFING', 'Librarian positions: Less than BA/BS Full time',   'integer', False, None),
    ('STAFFING', 'Librarian positions: Less than BA/BS Part time',   'integer', False, None),
    ('STAFFING', 'Librarian positions: Less than BA/BS FTE',         'decimal', False, None),
    ('STAFFING', 'Total Librarians',                                 'integer', False, None),
    ('STAFFING', 'All other Full time funded positions',             'integer', False, None),
    ('STAFFING', 'All other Part time funded positions',             'integer', False, None),
    ('STAFFING', 'All other staff FTE',                              'decimal', False, None),
    ('STAFFING', 'Full time positions: Total',                       'integer', False, None),
    ('STAFFING', 'Part time positions: Total',                       'integer', False, None),
    ('STAFFING', 'Grand total library staff FTE',                    'decimal', False, None),
    ('STAFFING', 'New librarian gross annual salary',                'integer', False, None),

    # REVENUE
    ('REVENUE', 'Millage assessed',                   'decimal', False, None),
    ('REVENUE', 'County operating revenue',           'integer', False, None),
    ('REVENUE', 'County capital revenue',             'integer', False, None),
    ('REVENUE', 'Total local operating revenue',      'integer', False, None),
    ('REVENUE', 'Total local capital revenue',        'integer', False, None),
    ('REVENUE', 'State Aid operating revenue',        'decimal', False, None),
    ('REVENUE', 'Total State Aid revenue',            'integer', False, None),
    ('REVENUE', 'Lottery operating revenue',          'integer', False, None),
    ('REVENUE', 'Total state operating revenue',      'integer', False, None),
    ('REVENUE', 'Federal / LSTA operating revenue',   'integer', False, None),
    ('REVENUE', 'Other federal operating revenue',    'integer', False, None),
    ('REVENUE', 'Total federal operating revenue',    'integer', False, None),
    ('REVENUE', 'Total federal capital revenue',      'integer', False, None),
    ('REVENUE', 'Other operating revenue',            'integer', False, None),
    ('REVENUE', 'Other capital revenue',              'integer', False, None),
    ('REVENUE', 'Total operating revenue',            'integer', False, None),
    ('REVENUE', 'Subtotal: Capital outlay',           'integer', False, None),
    ('REVENUE', 'Total capital outlay including other revenue', 'integer', False, None),
    ('REVENUE', 'Grand total operating + capital revenue',      'integer', False, None),

    # EXPENSES STAFF
    ('EXPENSES STAFF', 'Salary / Wages',          'integer', False, None),
    ('EXPENSES STAFF', 'Employee benefits',        'integer', False, None),
    ('EXPENSES STAFF', 'Total staff expenditures', 'integer', False, None),

    # EXPENSES COLLECTION
    ('EXPENSES COLLECTION', 'Expenditures: Print materials',       'integer', False, None),
    ('EXPENSES COLLECTION', 'Expenditures: Electronic materials',   'integer', False, None),
    ('EXPENSES COLLECTION', 'Expenditures: AV materials',           'integer', False, None),
    ('EXPENSES COLLECTION', 'Expenditures: Other materials',        'integer', False, None),
    ('EXPENSES COLLECTION', 'Expenditures: Total Other Materials',  'integer', False, None),
    ('EXPENSES COLLECTION', 'Expenditures: Total for collections',  'integer', False, None),

    # EXPENSES OPERATIONS
    ('EXPENSES OPERATIONS', 'Expenditures: Other operating - Furniture & Equipment',    'integer', False, None),
    ('EXPENSES OPERATIONS', 'Expenditures: Other operating - Plant operations & Maintenance', 'integer', False, None),
    ('EXPENSES OPERATIONS', 'Expenditures: All other operating',    'integer', False, None),
    ('EXPENSES OPERATIONS', 'Expenditures: Total other',            'integer', False, None),
    ('EXPENSES OPERATIONS', 'Expenditures: Total operating',        'integer', False, None),

    # EXPENSES CAPITAL
    ('EXPENSES CAPITAL', 'Expenditures: Capital building',                'integer', False, None),
    ('EXPENSES CAPITAL', 'Expenditures: Capital - Bookmobile / Vehicle',  'integer', False, None),
    ('EXPENSES CAPITAL', 'Expenditures: Capital - Furniture & Equipment', 'integer', False, None),
    ('EXPENSES CAPITAL', 'Expenditures: Capital - Other',                 'integer', False, None),
    ('EXPENSES CAPITAL', 'Expenditures: Capital - Total',                 'integer', False, None),

    # EXPENSES TOTAL
    ('EXPENSES TOTAL', 'Expenditures: GRAND TOTAL Operating + Capital', 'integer', False, None),

    # COLLECTION SIZE
    ('COLLECTION SIZE', 'Collections: Number of print materials added',              'integer', False, None),
    ('COLLECTION SIZE', 'Collections: Number of print materials removed (weeded)',   'integer', False, None),
    ('COLLECTION SIZE', 'Collections: Total print materials held',                   'integer', False, None),
    ('COLLECTION SIZE', 'Collections: Print serials subscriptions added',            'integer', False, None),
    ('COLLECTION SIZE', 'Collections: Print serials subscriptions removed',          'integer', False, None),
    ('COLLECTION SIZE', 'Collections: Total print serials subscriptions held',       'integer', False, None),
    ('COLLECTION SIZE', 'Collections: Audio materials added',                        'integer', False, None),
    ('COLLECTION SIZE', 'Collections: Audio materials removed',                      'integer', False, None),
    ('COLLECTION SIZE', 'Collections: Audio materials held',                         'integer', False, None),
    ('COLLECTION SIZE', 'Collections: Video materials added',                        'integer', False, None),
    ('COLLECTION SIZE', 'Collections: Video materials removed',                      'integer', False, None),
    ('COLLECTION SIZE', 'Collections: Video materials held',                         'integer', False, None),
    ('COLLECTION SIZE', 'Collection: Total Physical Items',                          'integer', False, None),
    ('COLLECTION SIZE', 'Downloadable audio units held',                             'integer', False, None),
    ('COLLECTION SIZE', 'Downloadable video units held',                             'integer', False, None),
    ('COLLECTION SIZE', 'Electronic books (E-books) held',                           'integer', False, None),
    ('COLLECTION SIZE', 'Downloadable periodical titles',                            'integer', False, None),
    ('COLLECTION SIZE', 'Total downloadable units available',                        'integer', False, None),
    ('COLLECTION SIZE', 'Electronic databases subscribed to by the library alone',  'integer', False, None),
    ('COLLECTION SIZE', 'Electronic databases subscribed to as part of a consortium','integer', False, None),
    ('COLLECTION SIZE', 'Total of Discus databases',                                 'integer', False, None),
    ('COLLECTION SIZE', 'Total databases',                                           'integer', False, None),

    # USERS GATE COUNT
    ('USERS GATE COUNT', 'Registered users, Adult',            'integer', False, None),
    ('USERS GATE COUNT', 'Registered users, Juvenile',         'integer', False, None),
    ('USERS GATE COUNT', 'Total registered users',             'integer', False, None),
    ('USERS GATE COUNT', 'Annual Library Visits (gate count)', 'integer', True,
     'Sum of Gate Count across all branches for the fiscal year (Jul–Jun)'),
    ('USERS GATE COUNT', 'Population of the service area',     'integer', False, None),

    # TECH USE
    ('TECH USE', 'Number of public internet computers', 'integer', False, None),
    ('TECH USE', 'Number of wireless sessions',         'integer', True,
     'Sum of WiFi - Unique Sessions across all branches for the fiscal year (Jul–Jun)'),
    ('TECH USE', 'Number of website visits',            'integer', True,
     'Sum of yclibrary.org - Web Sessions (Online Stats) for the fiscal year (Jul–Jun)'),

    # REF MTG RM
    ('REF MTG RM', 'Number of times library facilities were used by external parties', 'integer', False, None),
    ('REF MTG RM', 'Number of Reference Transactions',                                  'integer', False, None),
    ('REF MTG RM', 'Number of scheduled 1:1 sessions',                                  'integer', False, None),

    # CIRC
    ('CIRC', 'Circulation: Juvenile print',                   'integer', False, None),
    ('CIRC', 'Circulation: Juvenile non-print (A/V)',         'integer', False, None),
    ('CIRC', 'Circulation: Juvenile total all physical items','integer', False, None),
    ('CIRC', 'Circulation: Adult print',                      'integer', False, None),
    ('CIRC', 'Circulation: Adult non-print (A/V)',            'integer', False, None),
    ('CIRC', 'Circulation: Adult total all physical items',   'integer', False, None),
    ('CIRC', 'Circulation: Other physical items',             'integer', False, None),
    ('CIRC', 'Circulation: Books and other print materials, all ages', 'integer', False, None),
    ('CIRC', 'Circulation: Non print (A/V physical items), all ages',  'integer', False, None),
    ('CIRC', 'TOTAL COLLECTION USE', 'integer', True,
     'Sum of Total Branch Circulation across all branches for the fiscal year (Jul–Jun)'),
    ('CIRC', 'Usage of (Circulation) E-books',              'integer', False, None),
    ('CIRC', 'Usage of (Circulation) Electronic Audio',     'integer', False, None),
    ('CIRC', 'Usage of (Circulation) Electronic video',     'integer', False, None),
    ('CIRC', 'Usage of (Circulation) Electronic Periodicals','integer', False, None),
    ('CIRC', 'TOTAL CIRC ELECTRONIC',                       'integer', False, None),
    ('CIRC', 'GRAND TOTAL ALL CIRC',                        'integer', False, None),

    # ILL
    ('ILL', 'Interlibrary loans provided to another library', 'integer', False, None),
    ('ILL', 'Interlibrary loans received from another library','integer', False, None),

    # PROGRAMMING
    ('PROGRAMMING', 'Synchronous Pgm Sessions Kids 0-5',    'integer', True,
     'Sum of all ONSITE/OFFSITE/VIRTUAL Sessions 0-5 across all branches for the fiscal year'),
    ('PROGRAMMING', 'Synchronous Pgm Sessions Kids 6-11',   'integer', True,
     'Sum of all ONSITE/OFFSITE/VIRTUAL Sessions 6-11 across all branches for the fiscal year'),
    ('PROGRAMMING', 'Total Programs 0-11',                   'integer', True,
     'Sum of all Sessions 0-5 and Sessions 6-11 across all branches for the fiscal year'),
    ('PROGRAMMING', 'Total YA Programs for ages 12-18',      'integer', True,
     'Sum of all ONSITE/OFFSITE/VIRTUAL Sessions 12-18 across all branches for the fiscal year'),
    ('PROGRAMMING', 'Total Adult Programs for 18+',          'integer', True,
     'Sum of all ONSITE/OFFSITE/VIRTUAL Sessions 19+ across all branches for the fiscal year'),
    ('PROGRAMMING', 'Total Gen Audience',                    'integer', True,
     'Sum of all ONSITE/OFFSITE/VIRTUAL Sessions General Interest across all branches for the fiscal year'),
    ('PROGRAMMING', 'Total of all programs',                 'integer', True,
     'Sum of all programming sessions across all age groups, types, and branches for the fiscal year'),
    ('PROGRAMMING', 'Children 0 to 11 programs attendance',  'integer', True,
     'Sum of all ONSITE/OFFSITE/VIRTUAL Attendance 0-5 and 6-11 across all branches for the fiscal year'),
    ('PROGRAMMING', 'YA 12-18 programs attendance',          'integer', True,
     'Sum of all ONSITE/OFFSITE/VIRTUAL Attendance 12-18 across all branches for the fiscal year'),
    ('PROGRAMMING', 'Adult programs attendance',             'integer', True,
     'Sum of all ONSITE/OFFSITE/VIRTUAL Attendance 19+ across all branches for the fiscal year'),
    ('PROGRAMMING', 'Total General attendance',              'integer', True,
     'Sum of all ONSITE/OFFSITE/VIRTUAL Attendance General Interest across all branches for the fiscal year'),
    ('PROGRAMMING', 'Total Attendance all programs and all ages', 'integer', True,
     'Sum of all programming attendance across all age groups, types, and branches for the fiscal year'),

    # OUTREACH
    ('OUTREACH', 'Number of staff trained',            'integer', True,
     'Sum of Number of Staff Taking Training across all branches for the fiscal year'),
    ('OUTREACH', 'Number of hours of training attended by staff', 'decimal', True,
     'Sum of Number of Hours Staff Attended Training across all branches for the fiscal year'),
    ('OUTREACH', 'Number of items distributed as take-and-makes', 'integer', True,
     'Sum of Take & Makes / Other Passive Program Participants across all branches for the fiscal year'),
]

# ---------------------------------------------------------------------------
# Excel sheet → column → metric name mapping
# (sheet_name, col_index_1_based, metric_name)
# ---------------------------------------------------------------------------
SHEET_COL_MAP = {
    'OPERATIONS': [
        (2, 'Total Systemwide Annual Weekend / Evening Hours'),
        (3, 'Total Systemwide Annual Hours'),
        (4, 'Number of Library Trustees'),
        (5, 'Regular Board Meetings'),
        (6, 'Does the library have a FOL group?'),
        (7, 'Number of FOL groups'),
        (8, 'Friends Members all groups'),
    ],
    'STAFFING': [
        (2,  'MLIS Librarian Positions: Full Time'),
        (3,  'MLIS Librarian Positions: Part time'),
        (4,  'Librarian positions: MLIS FTE'),
        (5,  'Full Time Funded Other Librarian Positions'),
        (6,  'Part Time Funded Other Librarian Positions'),
        (7,  'FTE Other Librarians'),
        (8,  'Librarian positions: BA/BS Full time'),
        (9,  'Librarian positions: BA/BS Part time'),
        (10, 'Librarian positions: BA/BS FTE'),
        (11, 'Librarian positions: Less than BA/BS Full time'),
        (12, 'Librarian positions: Less than BA/BS Part time'),
        (13, 'Librarian positions: Less than BA/BS FTE'),
        (14, 'Total Librarians'),
        (15, 'All other Full time funded positions'),
        (16, 'All other Part time funded positions'),
        (17, 'All other staff FTE'),
        (18, 'Full time positions: Total'),
        (19, 'Part time positions: Total'),
        (20, 'Grand total library staff FTE'),
        (21, 'New librarian gross annual salary'),
    ],
    'REVENUE': [
        (2,  'Millage assessed'),
        (3,  'County operating revenue'),
        (4,  'County capital revenue'),
        (5,  'Total local operating revenue'),
        (6,  'Total local capital revenue'),
        (7,  'State Aid operating revenue'),
        (8,  'Total State Aid revenue'),
        (9,  'Lottery operating revenue'),
        (10, 'Total state operating revenue'),
        (11, 'Federal / LSTA operating revenue'),
        (12, 'Other federal operating revenue'),
        (13, 'Total federal operating revenue'),
        (14, 'Total federal capital revenue'),
        (15, 'Other operating revenue'),
        (16, 'Other capital revenue'),
        (17, 'Total operating revenue'),
        (18, 'Subtotal: Capital outlay'),
        (19, 'Total capital outlay including other revenue'),
        (20, 'Grand total operating + capital revenue'),
    ],
    'EXPENSES STAFF': [
        (2, 'Salary / Wages'),
        (3, 'Employee benefits'),
        (4, 'Total staff expenditures'),
    ],
    'EXPENSES COLLECTION': [
        (2, 'Expenditures: Print materials'),
        (3, 'Expenditures: Electronic materials'),
        (4, 'Expenditures: AV materials'),
        (5, 'Expenditures: Other materials'),
        (6, 'Expenditures: Total Other Materials'),
        (7, 'Expenditures: Total for collections'),
    ],
    'EXPENSES OPERATIONS': [
        (2, 'Expenditures: Other operating - Furniture & Equipment'),
        (3, 'Expenditures: Other operating - Plant operations & Maintenance'),
        (4, 'Expenditures: All other operating'),
        (5, 'Expenditures: Total other'),
        (6, 'Expenditures: Total operating'),
    ],
    'EXPENSES CAPITAL': [
        (2, 'Expenditures: Capital building'),
        (3, 'Expenditures: Capital - Bookmobile / Vehicle'),
        (4, 'Expenditures: Capital - Furniture & Equipment'),
        (5, 'Expenditures: Capital - Other'),
        (6, 'Expenditures: Capital - Total'),
    ],
    'EXPENSES TOTAL': [
        (2, 'Expenditures: GRAND TOTAL Operating + Capital'),
    ],
    'COLLECTION SIZE': [
        (2,  'Collections: Number of print materials added'),
        (3,  'Collections: Number of print materials removed (weeded)'),
        (4,  'Collections: Total print materials held'),
        (5,  'Collections: Print serials subscriptions added'),
        (6,  'Collections: Print serials subscriptions removed'),
        (7,  'Collections: Total print serials subscriptions held'),
        (8,  'Collections: Audio materials added'),
        (9,  'Collections: Audio materials removed'),
        (10, 'Collections: Audio materials held'),
        (11, 'Collections: Video materials added'),
        (12, 'Collections: Video materials removed'),
        (13, 'Collections: Video materials held'),
        (14, 'Collection: Total Physical Items'),
        # col 15 = blank Column1, skip
        (16, 'Downloadable audio units held'),
        (17, 'Downloadable video units held'),
        (18, 'Electronic books (E-books) held'),
        (19, 'Downloadable periodical titles'),
        (20, 'Total downloadable units available'),
        (21, 'Electronic databases subscribed to by the library alone'),
        (22, 'Electronic databases subscribed to as part of a consortium'),
        (23, 'Total of Discus databases'),
        (24, 'Total databases'),
    ],
    'USERS GATE COUNT': [
        (2, 'Registered users, Adult'),
        (3, 'Registered users, Juvenile'),
        (4, 'Total registered users'),
        (5, 'Annual Library Visits (gate count)'),
        (6, 'Population of the service area'),
    ],
    'TECH USE': [
        (2, 'Number of public internet computers'),
        (3, 'Number of wireless sessions'),
        (4, 'Number of website visits'),
    ],
    'REF MTG RM': [
        (2, 'Number of times library facilities were used by external parties'),
        (3, 'Number of Reference Transactions'),
        (4, 'Number of scheduled 1:1 sessions'),
    ],
    'CIRC': [
        (2,  'Circulation: Juvenile print'),
        (3,  'Circulation: Juvenile non-print (A/V)'),
        (4,  'Circulation: Juvenile total all physical items'),
        (5,  'Circulation: Adult print'),
        (6,  'Circulation: Adult non-print (A/V)'),
        (7,  'Circulation: Adult total all physical items'),
        (8,  'Circulation: Other physical items'),
        (9,  'Circulation: Books and other print materials, all ages'),
        (10, 'Circulation: Non print (A/V physical items), all ages'),
        (11, 'TOTAL COLLECTION USE'),
        # col 12 = blank, skip
        (13, 'Usage of (Circulation) E-books'),
        (14, 'Usage of (Circulation) Electronic Audio'),
        (15, 'Usage of (Circulation) Electronic video'),
        (16, 'Usage of (Circulation) Electronic Periodicals'),
        (17, 'TOTAL CIRC ELECTRONIC'),
        (18, 'GRAND TOTAL ALL CIRC'),
    ],
    'ILL': [
        (2, 'Interlibrary loans provided to another library'),
        (3, 'Interlibrary loans received from another library'),
    ],
    'PROGRAMMING': [
        (2,  'Synchronous Pgm Sessions Kids 0-5'),
        (3,  'Synchronous Pgm Sessions Kids 6-11'),
        (4,  'Total Programs 0-11'),
        (5,  'Total YA Programs for ages 12-18'),
        (6,  'Total Adult Programs for 18+'),
        (7,  'Total Gen Audience'),
        (8,  'Total of all programs'),
        # col 9 = Column1, skip
        (10, 'Children 0 to 11 programs attendance'),
        (11, 'YA 12-18 programs attendance'),
        (12, 'Adult programs attendance'),
        (13, 'Total General attendance'),
        (14, 'Total Attendance all programs and all ages'),
    ],
    'OUTREACH': [
        (2, 'Number of staff trained'),
        (3, 'Number of hours of training attended by staff'),
        (4, 'Number of items distributed as take-and-makes'),
    ],
}


def _num(v):
    """Convert a cell value to float, or None if not numeric."""
    if v is None or (isinstance(v, str) and v.strip() in ('', 'N/A', 'DATA NOT COLLECTED')):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _text(v):
    if v is None:
        return None
    return str(v).strip() or None


def seed_metrics(db_session):
    """Create AnnualSurveyMetric rows if they don't already exist."""
    existing = {m.name: m for m in AnnualSurveyMetric.query.all()}
    created = 0
    for i, (section, name, dtype, is_auto, note) in enumerate(METRIC_DEFS):
        if name not in existing:
            m = AnnualSurveyMetric(
                section=section, name=name, data_type=dtype,
                is_auto_calculated=is_auto, auto_calc_note=note,
                sort_order=i
            )
            db_session.add(m)
            created += 1
    db_session.flush()
    return created


def _apply_corrections(sheet_name, year, values):
    """
    Apply data-quality corrections to a row before inserting.
    values: dict {metric_name: raw_value}
    Returns (corrected_values, adjustments) where adjustments is a list of (metric_name, original, corrected, note).
    """
    adjustments = []

    if sheet_name == 'ILL' and year == 2024:
        for col_name in ('Interlibrary loans provided to another library',
                          'Interlibrary loans received from another library'):
            if col_name in values and values[col_name] is not None:
                original = values[col_name]
                corrected = values[col_name]  # will be set after we read 2022/2023
                adjustments.append((col_name, original, None, 'averaged_ill_2024'))
        values['_needs_ill_avg'] = True

    if sheet_name == 'PROGRAMMING' and year == 2018:
        numeric_cols = [
            'Total Programs 0-11', 'Total YA Programs for ages 12-18',
            'Total Adult Programs for 18+', 'Total of all programs',
            'Children 0 to 11 programs attendance', 'YA 12-18 programs attendance',
            'Adult programs attendance', 'Total Attendance all programs and all ages',
        ]
        for col in numeric_cols:
            if col in values and values[col] is not None:
                adjustments.append((col, values[col], None, 'averaged_pgm_2018'))
        values['_needs_pgm_avg_2018'] = True

    if sheet_name == 'USERS GATE COUNT' and year == 2013:
        col = 'Annual Library Visits (gate count)'
        if col in values and values[col] is not None:
            adjustments.append((col, values[col], None, 'averaged_gate_2013'))
        values['_needs_gate_avg_2013'] = True

    if sheet_name == 'PROGRAMMING' and year in (2014, 2015, 2016):
        col = 'Children 0 to 11 programs attendance'
        total = values.get('Total Attendance all programs and all ages')
        ya = values.get('YA 12-18 programs attendance') or 0
        adult = values.get('Adult programs attendance') or 0
        gen = values.get('Total General attendance') or 0
        if total is not None and values.get(col) is not None:
            corrected = round(total - ya - adult - gen)
            if corrected != values[col]:
                adjustments.append((col, values[col], corrected,
                                     f'back-calculated from total ({total}) - YA ({ya}) - Adult ({adult}) - Gen ({gen})'))
                values[col] = corrected

    return values, adjustments


def import_annual(filepath):
    wb = openpyxl.load_workbook(filepath, data_only=True)

    # Seed metrics first
    metric_map = {m.name: m for m in AnnualSurveyMetric.query.all()}

    # Read all sheets into memory: {sheet: {year: {metric_name: value}}}
    all_data = {}
    for sheet_name, col_map in SHEET_COL_MAP.items():
        if sheet_name not in wb.sheetnames:
            print(f'  WARNING: sheet "{sheet_name}" not found, skipping')
            continue
        ws = wb[sheet_name]
        sheet_data = {}
        for row in ws.iter_rows(min_row=2, values_only=True):
            year = row[0]
            if not isinstance(year, int):
                continue
            row_vals = {}
            for col_idx, metric_name in col_map:
                raw = row[col_idx - 1]
                m = metric_map.get(metric_name)
                if m and m.data_type == 'text':
                    row_vals[metric_name] = _text(raw)
                else:
                    row_vals[metric_name] = _num(raw)
            sheet_data[year] = row_vals
        all_data[sheet_name] = sheet_data

    # Resolve averages that need surrounding year data
    # ILL 2024: avg of 2022 and 2023
    if 'ILL' in all_data and 2024 in all_data['ILL']:
        d22 = all_data['ILL'].get(2022, {})
        d23 = all_data['ILL'].get(2023, {})
        d24 = all_data['ILL'][2024]
        for col in ('Interlibrary loans provided to another library',
                    'Interlibrary loans received from another library'):
            v22, v23 = d22.get(col), d23.get(col)
            if v22 is not None and v23 is not None:
                avg = round((v22 + v23) / 2)
                orig = d24.get(col)
                print(f'  ILL 2024 {col}: {orig} → {avg} (avg of {v22}, {v23})')
                d24[col] = avg
                d24[f'_adj_{col}'] = f'averaged from 2022 ({int(v22)}) and 2023 ({int(v23)}) — original {int(orig)} was inflated'

    # Programming 2018: avg of 2017 and 2019
    if 'PROGRAMMING' in all_data and 2018 in all_data['PROGRAMMING']:
        d17 = all_data['PROGRAMMING'].get(2017, {})
        d18 = all_data['PROGRAMMING'][2018]
        d19 = all_data['PROGRAMMING'].get(2019, {})
        avg_cols = [
            'Total Programs 0-11', 'Total YA Programs for ages 12-18',
            'Total Adult Programs for 18+', 'Total of all programs',
            'Children 0 to 11 programs attendance', 'YA 12-18 programs attendance',
            'Adult programs attendance', 'Total Attendance all programs and all ages',
        ]
        for col in avg_cols:
            v17, v19 = d17.get(col), d19.get(col)
            if v17 is not None and v19 is not None:
                avg = round((v17 + v19) / 2)
                orig = d18.get(col)
                print(f'  PROGRAMMING 2018 {col}: {orig} → {avg}')
                d18[col] = avg
                d18[f'_adj_{col}'] = f'averaged from 2017 ({int(v17)}) and 2019 ({int(v19)}) — original {int(orig)} was inflated'

    # Gate Count 2013: avg of 2012 and 2014
    if 'USERS GATE COUNT' in all_data and 2013 in all_data['USERS GATE COUNT']:
        col = 'Annual Library Visits (gate count)'
        d12 = all_data['USERS GATE COUNT'].get(2012, {})
        d13 = all_data['USERS GATE COUNT'][2013]
        d14 = all_data['USERS GATE COUNT'].get(2014, {})
        v12, v14 = d12.get(col), d14.get(col)
        if v12 is not None and v14 is not None:
            avg = round((v12 + v14) / 2)
            orig = d13.get(col)
            print(f'  GATE COUNT 2013: {orig} → {avg} (avg of {int(v12)}, {int(v14)})')
            d13[col] = avg
            d13[f'_adj_{col}'] = f'averaged from 2012 ({int(v12)}) and 2014 ({int(v14)}) — original {int(orig)} was inflated'

    # Programming 2014-2016: back-calculate children's attendance
    if 'PROGRAMMING' in all_data:
        for yr in (2014, 2015, 2016):
            if yr not in all_data['PROGRAMMING']:
                continue
            row = all_data['PROGRAMMING'][yr]
            col = 'Children 0 to 11 programs attendance'
            total = row.get('Total Attendance all programs and all ages')
            ya = row.get('YA 12-18 programs attendance') or 0
            adult = row.get('Adult programs attendance') or 0
            gen = row.get('Total General attendance') or 0
            if total is not None and row.get(col) is not None:
                corrected = round(total - ya - adult - gen)
                orig = row[col]
                if corrected != orig:
                    print(f'  PROGRAMMING {yr} children attendance: {orig} → {corrected}')
                    row[col] = corrected
                    row[f'_adj_{col}'] = (f'back-calculated: total ({int(total)}) - YA ({int(ya)}) '
                                           f'- Adult ({int(adult)}) - Gen ({int(gen)}) — original {int(orig)} was inflated')

    # Now insert into DB
    created = updated = 0
    for sheet_name, sheet_data in all_data.items():
        for year, row_vals in sheet_data.items():
            for metric_name, value in row_vals.items():
                if metric_name.startswith('_adj_') or metric_name.startswith('_needs_'):
                    continue
                m = metric_map.get(metric_name)
                if not m:
                    continue

                adj_note = row_vals.get(f'_adj_{metric_name}')
                is_adj = adj_note is not None

                existing = AnnualSurveyValue.query.filter_by(
                    report_year=year, metric_id=m.id).first()

                if m.data_type == 'text':
                    num_val, text_val = None, value
                else:
                    num_val, text_val = value, None

                if existing:
                    existing.value = num_val
                    existing.value_text = text_val
                    if is_adj:
                        existing.is_adjusted = True
                        existing.adjustment_note = adj_note
                    updated += 1
                else:
                    db.session.add(AnnualSurveyValue(
                        report_year=year, metric_id=m.id,
                        value=num_val, value_text=text_val,
                        is_adjusted=is_adj, adjustment_note=adj_note
                    ))
                    created += 1

    db.session.commit()
    return created, updated


if __name__ == '__main__':
    with app.app_context():
        print('Seeding annual survey metrics...')
        n = seed_metrics(db.session)
        db.session.commit()
        print(f'  {n} metrics created')

        print('Importing Annual Comparables.xlsx...')
        created, updated = import_annual(
            'Data files/annual/Annual Comparables.xlsx'
        )
        print(f'  Done: {created} values created, {updated} updated')
