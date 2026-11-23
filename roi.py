"""Return on Investment report: what library use would cost residents on the
open market, compared with what the library costs to run.

value = sum(uses x market price) ; return per $1 = value / operating spending

Usage sources (one fiscal year, Jul-Jun):
  physical checkouts  sirsi_checkouts (first checkouts only, by shelving location)
  renewals            sirsi_checkouts.renewals (default price $0 = not counted)
  digital             Annual eResources entry (system-wide, branch_id=None)
  computers           Branch Stats 'PC Reservations'
  programs            Branch Stats {ONSITE,OFFSITE,VIRTUAL} Attendance {age}
  meeting rooms       Branch Stats 'External Party Library Room Use'
  reference help      state annual survey 'Number of Reference Transactions'
  optional extras     WiFi sessions, Take & Make participants (default $0)

Prices are RoiPrice rows (admin-editable). DEFAULT_PRICES seeds missing keys.
"""
import re
from collections import OrderedDict

from sqlalchemy import or_, and_, func

from models import (db, RoiPrice, RoiFiscalYear, Category, Metric, Branch, Entry,
                    EntryValue, SirsiCheckout, AnnualSurveyMetric, AnnualSurveyValue)

MAINE = 'https://www.maine.gov/msl/services/calexplantion.htm'
LRS = 'https://docs.google.com/spreadsheets/d/1ggkF524e8771ssQMJ1zbKQhSDyRRLOfLmQ2GE2LSPu8/edit?gid=0'
SYRACUSE = 'https://truevalue.ischool.syr.edu/data-and-decisions/'
HUMANIT = 'https://www.human-i-t.org/best-affordable-5g-hotspots-in-2026-complete-buyers-guide/'
PEERSPACE = 'https://www.peerspace.com/venues/rock-hill--sc/meetup-venue'
FEDEX = 'https://www.office.fedex.com/default/computer-access'
CINEMARK = 'https://www.cinemark.com/movie-news/articles/movie-ticket-prices-guide'
MACRUMORS = 'https://www.macrumors.com/2025/08/22/F1-NOW-AVAILABLE-TO-BUY-OR-RENT/'

# key, group, label, price, unit, basis, source_url
# Rows still marked updated_by='default' are refreshed from this list at startup;
# rows an admin has edited are left alone.
DEFAULT_PRICES = [
    ('book_adult',    'materials', 'Adult books', 22.12, 'per checkout', 'AspenCat average price (Library Research Service, Jan 2026)', LRS),
    ('book_children', 'materials', "Children's books", 21.84, 'per checkout', 'AspenCat average price (Library Research Service, Jan 2026)', LRS),
    ('book_teen',     'materials', 'Teen books, paperbacks & graphic novels', 16.34, 'per checkout', 'AspenCat average YA price (Library Research Service, Jan 2026)', LRS),
    ('audiobook',     'materials', 'Audiobooks (CD, Playaway)', 22.59, 'per checkout', 'Top 20 Amazon best sellers (Library Research Service, Jan 2026)', LRS),
    ('movie',         'materials', 'Movies & TV (DVD, Blu-ray)', 5.00, 'per checkout', 'Estimate: standard digital rental (LRS uses the $24.48 purchase price instead)', MACRUMORS),
    ('hotspot',       'materials', 'WiFi hotspots', 25.00, 'per checkout', 'Monthly 5G hotspot rental with unlimited data, $24.99 (Human-I-T, Nov 2026); weekly travel rentals run $56-$109', HUMANIT),
    ('other_item',    'materials', 'Other (kits, video games, music, ILL)', 12.00, 'per checkout', 'Estimate, below LRS prices for CDs ($14.15) and interlibrary loan ($17.50)', LRS),
    ('renewal',       'materials', 'Renewals', 0.00, 'per renewal', "Not counted: a renewal doesn't save a second purchase", ''),
    ('ebook',         'digital', 'eBooks', 7.86, 'per use', 'Top 20 Amazon Kindle best sellers (Library Research Service, Jan 2026)', LRS),
    ('eaudio',        'digital', 'eAudiobooks', 23.99, 'per use', 'Top 20 Amazon audiobook best sellers (Library Research Service, Jan 2026)', LRS),
    ('evideo',        'digital', 'eVideo', 5.00, 'per use', 'Same rental estimate as DVDs', MACRUMORS),
    ('eserial',       'digital', 'eSerials (magazines, newspapers)', 6.70, 'per use', 'Average issue price of 10 popular magazines (Library Research Service, Jan 2026)', LRS),
    ('computer_hour', 'computers', 'Public computer use', 27.00, 'per hour', "FedEx Office (formerly Kinko's), $0.45/minute (same figure in LRS, Jan 2026)", FEDEX),
    ('wifi_session',  'computers', 'WiFi sessions', 0.00, 'per session', 'Not counted: no clear market price', ''),
    ('program_adult', 'programs', 'Program attendee: teen / adult / all ages', 16.08, 'per attendee', '2025 average U.S. movie ticket (Cinemark)', CINEMARK),
    ('program_child', 'programs', 'Program attendee: children 0-11', 12.00, 'per attendee', "Children's movie-ticket value (Maine State Library, Nov 2019)", MAINE),
    ('take_make',     'programs', 'Take & Make / passive program participants', 0.00, 'per participant', 'Not counted by default', ''),
    ('room_hour',     'rooms', 'Meeting room rental (rooms seat 50-75)', 150.00, 'per hour', 'Rock Hill training/event space for 50 (Peerspace, Nov 2026); also the median of 11 local listings for 47-80 guests', PEERSPACE),
    ('room_hour_small', 'rooms', 'Small meeting room rental (Clover, seats about 20)', 70.00, 'per hour', 'Median of local Peerspace meeting rooms for 15-20 guests ($65-$120, Nov 2026)', PEERSPACE),
    ('reference_question', 'reference', 'Reference questions answered', 2.24, 'per question', 'About 5 minutes of library staff time at $26.90/hour (Library Research Service, Jan 2026)', LRS),
    ('pc_hours',      'assumptions', 'Hours per PC reservation', 1.0, 'hours', 'Assumption: PC reservation system does not report session length', ''),
    ('room_hours',    'assumptions', 'Hours per meeting room booking', 2.0, 'hours', 'Assumption: booking length is not recorded', ''),
]

# Branches whose meeting room seats about 20 (valued at room_hour_small);
# every other branch's room seats 50-75 (room_hour).
SMALL_ROOM_BRANCHES = ('Clover',)

GROUP_TITLES = OrderedDict([
    ('materials', 'Materials checkout'),
    ('digital', 'Digital materials'),
    ('computers', 'Computer & internet use'),
    ('programs', 'Programs'),
    ('rooms', 'Meeting rooms'),
    ('reference', 'Reference help'),
    ('assumptions', 'Assumptions'),
])


def seed_roi_prices():
    """Insert missing default price rows, and refresh rows nobody has edited
    (updated_by == 'default') when DEFAULT_PRICES changes. Admin edits are kept."""
    have = {p.key: p for p in RoiPrice.query.all()}
    for i, (key, grp, label, price, unit, basis, url) in enumerate(DEFAULT_PRICES):
        row = have.get(key)
        if row is None:
            db.session.add(RoiPrice(key=key, group_name=grp, label=label, price=price,
                                    unit=unit, basis=basis, source_url=url, sort_order=i,
                                    updated_by='default'))
        elif row.updated_by == 'default':
            row.group_name, row.label, row.price, row.unit = grp, label, price, unit
            row.basis, row.source_url, row.sort_order = basis, url, i
        else:
            row.sort_order = i
    db.session.commit()


def classify_shelving(loc):
    """Map a SIRSI shelving location code to a materials price key."""
    s = (loc or '').upper()
    if re.search(r'DVD|BLU-RAY|VIDEO$|-VID$|VIS-MEDI|-AV$', s) and 'VID-GAM' not in s:
        return 'movie'
    if re.search(r'AUD|PLAYAW|SND-REC|CD-BK', s):
        return 'audiobook'
    if 'HOTSPOT' in s:
        return 'hotspot'
    if re.search(r'VID-GAM|GAMING|KIT|MUSIC|^ILL$|MAGAZINE', s):
        return 'other_item'
    if s.startswith('J-'):
        return 'book_children'
    if s.startswith(('YA', 'T-')) or 'PBK' in s or 'GRA' in s or 'MANGA' in s:
        return 'book_teen'
    return 'book_adult'


def _fy_filter(model, fy):
    return or_(and_(model.year == fy - 1, model.month >= 7),
               and_(model.year == fy, model.month <= 6))


def available_fiscal_years():
    """Fiscal years with Branch Stats monthly data, newest first."""
    bs = Category.query.filter_by(name='Branch Stats').first()
    if not bs:
        return []
    rows = (db.session.query(Entry.year, Entry.month)
            .filter(Entry.category_id == bs.id, Entry.month.isnot(None)).distinct().all())
    return sorted({(y + 1 if m >= 7 else y) for y, m in rows}, reverse=True)


def fy_months_loaded(fy):
    bs = Category.query.filter_by(name='Branch Stats').first()
    if not bs:
        return 0
    return (db.session.query(Entry.year, Entry.month)
            .filter(Entry.category_id == bs.id, _fy_filter(Entry, fy)).distinct().count())


def _branch_stats_totals(fy, names):
    """Sum Branch Stats metrics over a fiscal year, excluding the system-wide placeholder."""
    bs = Category.query.filter_by(name='Branch Stats').first()
    if not bs:
        return {}
    sw = Branch.query.filter_by(name='YCL (System Wide)').first()
    q = (db.session.query(Metric.name, func.sum(EntryValue.value_number))
         .join(EntryValue, EntryValue.metric_id == Metric.id)
         .join(Entry, Entry.id == EntryValue.entry_id)
         .filter(Entry.category_id == bs.id, Metric.name.in_(names), _fy_filter(Entry, fy)))
    if sw:
        q = q.filter(or_(Entry.branch_id.is_(None), Entry.branch_id != sw.id))
    return {n: (v or 0) for n, v in q.group_by(Metric.name).all()}


def _survey_value(name, fy):
    """(value, report_year) from the newest state annual survey at or before fy."""
    m = AnnualSurveyMetric.query.filter_by(name=name).first()
    if not m:
        return None, None
    v = (AnnualSurveyValue.query
         .filter(AnnualSurveyValue.metric_id == m.id, AnnualSurveyValue.value.isnot(None),
                 AnnualSurveyValue.report_year <= fy)
         .order_by(AnnualSurveyValue.report_year.desc()).first())
    return (v.value, v.report_year) if v else (None, None)


def _branch_stats_by_branch(fy, name):
    """One Branch Stats metric over a fiscal year, summed per branch name."""
    bs = Category.query.filter_by(name='Branch Stats').first()
    if not bs:
        return {}
    q = (db.session.query(Branch.name, func.sum(EntryValue.value_number))
         .join(Entry, Entry.branch_id == Branch.id)
         .join(EntryValue, EntryValue.entry_id == Entry.id)
         .join(Metric, Metric.id == EntryValue.metric_id)
         .filter(Entry.category_id == bs.id, Metric.name == name, _fy_filter(Entry, fy),
                 Branch.name != 'YCL (System Wide)'))
    return {b: (v or 0) for b, v in q.group_by(Branch.name).all()}


def _spending(fy):
    """(operating spending, population, note) for a fiscal year."""
    row = RoiFiscalYear.query.filter_by(fiscal_year=fy).first()
    spend = row.operating_spending if row else None
    pop = row.population if row else None
    note = (row.note or f'Entered for FY{fy}') if row and spend else None

    spend_is_fallback = False
    if not spend:
        spend, yr = _survey_value('Expenditures: Total operating', fy)
        if spend:
            spend_is_fallback = yr != fy
            note = f'State annual survey, report year {yr}'
    if not pop:
        p, _ = _survey_value('Population of the service area', fy)
        pop = int(p) if p else None
    return spend, pop, note, spend_is_fallback


def compute_roi(fy):
    prices = {p.key: p for p in RoiPrice.query.order_by(RoiPrice.sort_order).all()}

    def price(key):
        p = prices.get(key)
        return p.price if p else 0.0

    sections = OrderedDict()

    def add(group, key, label, uses, unit_price, use_label, note=None):
        sections.setdefault(group, []).append({
            'key': key, 'label': label, 'uses': uses, 'price': unit_price,
            'value': round((uses or 0) * unit_price, 2), 'use_label': use_label,
            'counted': unit_price > 0, 'note': note,
        })

    # ── Physical materials ────────────────────────────────────────────────
    rows = (db.session.query(SirsiCheckout.shelving_location,
                             func.sum(SirsiCheckout.checkouts), func.sum(SirsiCheckout.renewals))
            .filter(_fy_filter(SirsiCheckout, fy))
            .group_by(SirsiCheckout.shelving_location).all())
    has_sirsi = bool(rows)
    by_key = {k: 0 for k in ('book_adult', 'book_children', 'book_teen', 'audiobook', 'movie', 'hotspot', 'other_item')}
    renewals = 0
    for loc, co, rn in rows:
        by_key[classify_shelving(loc)] += int(co or 0)
        renewals += int(rn or 0)
    for key in ('book_adult', 'book_children', 'book_teen', 'audiobook', 'movie', 'hotspot', 'other_item'):
        p = prices.get(key)
        add('materials', key, p.label if p else key, by_key[key], price(key), 'checkouts')
    add('materials', 'renewal', prices['renewal'].label if 'renewal' in prices else 'Renewals',
        renewals, price('renewal'), 'renewals')

    # ── Digital ───────────────────────────────────────────────────────────
    digital_names = OrderedDict([('eaudio', 'E-Audio Circulation'), ('ebook', 'E-Book Circulation'),
                                 ('eserial', 'E-Serials Circulation'), ('evideo', 'E-Video Circulation')])
    eres = Category.query.filter_by(name='Annual eResources').first()
    dvals = {}
    if eres:
        e = Entry.query.filter_by(category_id=eres.id, branch_id=None, year=fy, month=None).first()
        if e:
            for ev in e.values:
                if ev.value_number is not None:
                    dvals[ev.metric.name] = ev.value_number
    has_digital = bool(dvals)
    for key, mname in digital_names.items():
        p = prices.get(key)
        add('digital', key, p.label if p else key, int(dvals.get(mname, 0)), price(key), 'uses')

    # ── Branch Stats-based measures ───────────────────────────────────────
    ages_child, ages_adult = ['0-5', '6-11'], ['12-18', '19+', 'General Interest']
    att_names = [f'{t} Attendance {a}' for t in ('ONSITE', 'OFFSITE', 'VIRTUAL')
                 for a in ages_child + ages_adult]
    bs = _branch_stats_totals(fy, att_names + [
        'PC Reservations', 'WiFi - Unique Sessions', 'External Party Library Room Use',
        'Take & Makes / Other Passive Program Participants', 'Outreach Attendance',
        'Total Prints per Month'])

    pc = int(bs.get('PC Reservations', 0))
    pc_hours = price('pc_hours') or 1.0
    add('computers', 'computer_hour', 'Public computer sessions', pc, price('computer_hour') * pc_hours,
        'sessions', f'{pc_hours:g} hour(s) per session at ${price("computer_hour"):,.2f}/hour')
    add('computers', 'wifi_session', 'WiFi sessions', int(bs.get('WiFi - Unique Sessions', 0)),
        price('wifi_session'), 'sessions')

    age_labels = {'0-5': 'Children 0-5', '6-11': 'Children 6-11', '12-18': 'Teens 12-18',
                  '19+': 'Adults 19+', 'General Interest': 'General interest (all ages)'}
    for a in ages_child + ages_adult:
        n = int(sum(bs.get(f'{t} Attendance {a}', 0) for t in ('ONSITE', 'OFFSITE', 'VIRTUAL')))
        key = 'program_child' if a in ages_child else 'program_adult'
        add('programs', key, age_labels[a], n, price(key), 'attendees')
    add('programs', 'take_make', prices['take_make'].label if 'take_make' in prices else 'Take & Make',
        int(bs.get('Take & Makes / Other Passive Program Participants', 0)), price('take_make'), 'participants')

    room_hours = price('room_hours') or 1.0
    by_branch = _branch_stats_by_branch(fy, 'External Party Library Room Use')
    small = int(sum(v for b, v in by_branch.items() if b in SMALL_ROOM_BRANCHES))
    large = int(sum(v for b, v in by_branch.items() if b not in SMALL_ROOM_BRANCHES))
    add('rooms', 'room_hour', 'Meeting room bookings, rooms for 50-75', large,
        price('room_hour') * room_hours, 'bookings',
        f'{room_hours:g} hour(s) per booking at ${price("room_hour"):,.2f}/hour')
    add('rooms', 'room_hour_small', f'Meeting room bookings, {", ".join(SMALL_ROOM_BRANCHES)} (room for about 20)',
        small, price('room_hour_small') * room_hours, 'bookings',
        f'{room_hours:g} hour(s) per booking at ${price("room_hour_small"):,.2f}/hour')

    # ── Reference help (annual state survey count) ────────────────────────
    ref_n, ref_yr = _survey_value('Number of Reference Transactions', fy)
    add('reference', 'reference_question', 'Reference questions answered', int(ref_n or 0),
        price('reference_question'), 'questions',
        f'State annual survey, report year {ref_yr}' if ref_yr else 'No state survey count')

    # ── Totals ────────────────────────────────────────────────────────────
    summary = []
    for grp, items in sections.items():
        counted = [i for i in items if i['counted']]
        summary.append({
            'group': grp, 'title': GROUP_TITLES[grp],
            'uses': sum(i['uses'] for i in counted),
            'use_label': counted[0]['use_label'] if counted else '',
            'value': round(sum(i['value'] for i in counted), 2),
        })
    total = round(sum(s['value'] for s in summary), 2)
    spend, pop, spend_note, spend_is_fallback = _spending(fy)

    not_counted = [i for items in sections.values() for i in items if not i['counted'] and i['uses']]
    not_counted.append({'label': 'Outreach attendance (likely overlaps off-site counts)',
                        'uses': int(bs.get('Outreach Attendance', 0)), 'use_label': 'attendees'})
    not_counted.append({'label': 'Prints', 'uses': int(bs.get('Total Prints per Month', 0)),
                        'use_label': 'prints'})

    warnings = []
    if ref_yr and ref_yr != fy:
        warnings.append(f'Reference questions use the report year {ref_yr} state survey count '
                        f'(no FY{fy} figure yet).')
    months = fy_months_loaded(fy)
    if months < 12:
        warnings.append(f'Only {months} of 12 months of Branch Stats are loaded for FY{fy}; totals are partial.')
    if not has_sirsi:
        warnings.append(f'No SIRSI checkout detail for FY{fy} (that table starts July 2025), '
                        'so physical materials are valued at $0.')
    if not has_digital:
        warnings.append(f'No Annual eResources entry for FY{fy}, so digital materials are valued at $0.')
    if spend_is_fallback:
        warnings.append(f'No FY{fy} operating spending entered; using {spend_note}. '
                        'An admin can enter the actual figure in ROI Settings.')

    return {
        'fy': fy, 'sections': sections, 'summary': summary, 'total': total,
        'spending': spend, 'population': pop, 'spending_note': spend_note,
        'roi': (total / spend) if spend else None,
        'value_per_resident': (total / pop) if pop else None,
        'cost_per_resident': (spend / pop) if (spend and pop) else None,
        'prices': list(prices.values()), 'not_counted': not_counted, 'warnings': warnings,
        'group_titles': GROUP_TITLES,
    }
