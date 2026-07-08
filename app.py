from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, session
from flask_login import LoginManager, login_user, logout_user, current_user
from models import db, Category, Metric, Branch, Entry, EntryValue, User, QuarterlyRefClosureDays, ImportLog
from sqlalchemy.orm import joinedload
from sqlalchemy import or_, and_
from jinja2 import ChoiceLoader, FileSystemLoader
from datetime import datetime
from functools import wraps
import hmac
import io
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'library-stats-dev-key')

# Supabase (and some other hosts) provide URLs starting with "postgres://"
# but SQLAlchemy 2.x requires "postgresql://".
_db_url = os.environ.get('DATABASE_URL', 'sqlite:///librarystats.db')
if _db_url.startswith('postgres://'):
    _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

# Allow report templates to live in /reports/ at the project root
app.jinja_loader = ChoiceLoader([
    app.jinja_loader,
    FileSystemLoader(os.path.dirname(__file__)),
])

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# Runs for both `python app.py` and gunicorn
with app.app_context():
    db.create_all()

    # Migrate: add is_desk column if it doesn't exist yet
    try:
        db.session.execute(db.text(
            'ALTER TABLE branches ADD COLUMN is_desk BOOLEAN NOT NULL DEFAULT FALSE'
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()

    # Mark Rock Hill desk branches used in Quarterly Reference Stats
    for _desk_name in ['Rock Hill - Circulation', 'Rock Hill - Reference', 'Rock Hill - YA', "Rock Hill - Children's"]:
        _b = Branch.query.filter_by(name=_desk_name).first()
        if _b:
            _b.is_desk = True
            _b.is_active = True
    # Create Rock Hill - Children's if it doesn't exist yet
    if not Branch.query.filter_by(name="Rock Hill - Children's").first():
        _max_sort = db.session.query(db.func.max(Branch.sort_order)).scalar() or 0
        db.session.add(Branch(name="Rock Hill - Children's", is_desk=True, is_active=True, sort_order=_max_sort + 1))
    # Create Administration branch if it doesn't exist yet
    if not Branch.query.filter_by(name='Administration').first():
        _max_sort = db.session.query(db.func.max(Branch.sort_order)).scalar() or 0
        db.session.add(Branch(name='Administration', is_active=True, is_desk=False, sort_order=_max_sort + 1))
    db.session.commit()

    if Category.query.count() == 0:
        from seed_data import seed
        seed(db)

    # Ensure 'New Library Card Registrations, Total' exists in Branch Stats
    # (missing from early seed data; the SIRSI importer writes to it)
    _bs = Category.query.filter_by(name='Branch Stats').first()
    if _bs and not any(m.name == 'New Library Card Registrations, Total' for m in _bs.metrics):
        _max_sort = max((m.sort_order for m in _bs.metrics), default=0)
        _juv = next((m for m in _bs.metrics if m.name == 'New Library Card Registrations, Juvenile'), None)
        db.session.add(Metric(
            category_id=_bs.id,
            name='New Library Card Registrations, Total',
            group_name='Registrations',
            data_type='integer',
            sort_order=(_juv.sort_order + 1) if _juv else _max_sort + 1,
        ))
        db.session.commit()

    # Backfill Total for entries imported before the Total metric existed
    _bs = Category.query.filter_by(name='Branch Stats').first()
    if _bs:
        _total_m = next((m for m in _bs.metrics if m.name == 'New Library Card Registrations, Total'), None)
        _adult_m = next((m for m in _bs.metrics if m.name == 'New Library Card Registrations, Adult'), None)
        _juv_m   = next((m for m in _bs.metrics if m.name == 'New Library Card Registrations, Juvenile'), None)
        if _total_m and _adult_m and _juv_m:
            _backfilled = 0
            for _entry in Entry.query.filter_by(category_id=_bs.id).all():
                if EntryValue.query.filter_by(entry_id=_entry.id, metric_id=_total_m.id).first():
                    continue
                _a = EntryValue.query.filter_by(entry_id=_entry.id, metric_id=_adult_m.id).first()
                _j = EntryValue.query.filter_by(entry_id=_entry.id, metric_id=_juv_m.id).first()
                if not _a and not _j:
                    continue
                _av = _a.value_number if _a else 0
                _jv = _j.value_number if _j else 0
                if _av or _jv:
                    db.session.add(EntryValue(entry_id=_entry.id, metric_id=_total_m.id,
                                              value_number=(_av or 0) + (_jv or 0)))
                    _backfilled += 1
            if _backfilled:
                db.session.commit()

    # Remove DigitalLearn.org metrics from the Online Stats entry form.
    # Deactivate if they hold recorded data (preserves history), else delete.
    _os = Category.query.filter_by(name='Online Stats').first()
    if _os:
        for _dl in Metric.query.filter(
            Metric.category_id == _os.id,
            Metric.name.in_([
                'DigitalLearn.org - Sessions',
                'DigitalLearn.org - Completed Courses',
            ]),
        ).all():
            if EntryValue.query.filter_by(metric_id=_dl.id).count():
                _dl.is_active = False
            else:
                db.session.delete(_dl)
        db.session.commit()

    # Create import_logs table if it doesn't exist yet
    try:
        db.session.execute(db.text(
            "CREATE TABLE IF NOT EXISTS import_logs ("
            "  id SERIAL PRIMARY KEY,"
            "  created_at TIMESTAMP DEFAULT NOW(),"
            "  file_name VARCHAR(255),"
            "  import_type VARCHAR(500),"
            "  year INTEGER,"
            "  month INTEGER,"
            "  rows_affected INTEGER DEFAULT 0,"
            "  undone_at TIMESTAMP,"
            "  changes_json TEXT"
            ")"
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()

    # Bootstrap: create default admin from env vars if no users exist yet
    if User.query.count() == 0:
        _admin = User(
            username=os.environ.get('LOGIN_USERNAME', 'admin'),
            email=None,
            is_active=True,
            is_admin=True,
        )
        _admin.set_password(os.environ.get('LOGIN_PASSWORD', ''))
        db.session.add(_admin)
        db.session.commit()

MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
          'July', 'August', 'September', 'October', 'November', 'December']

PROG_TYPES = ['ONSITE', 'OFFSITE', 'VIRTUAL']
AGE_GROUPS = ['0-5', '6-11', '12-18', '19+', 'General Interest']


@app.template_filter('commas')
def commas_filter(value):
    if value is None:
        return '—'
    return f"{int(value):,}"

# ── Auth ──────────────────────────────────────────────────────────────────────

_PUBLIC_ENDPOINTS = {'login', 'logout', 'static'}


@app.before_request
def require_login():
    if request.endpoint not in _PUBLIC_ENDPOINTS and not current_user.is_authenticated:
        return redirect(url_for('login', next=request.path))


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            flash('Admin access required.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and user.is_active and user.check_password(password):
            login_user(user, remember=True)
            next_url = request.args.get('next') or url_for('index')
            return redirect(next_url)
        error = 'Invalid username or password.'
    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))


def group_metrics(metrics):
    """Return list of {'name': str, 'metrics': [...]} dicts preserving order."""
    groups = []
    seen = {}
    for m in metrics:
        key = m.group_name or ''
        if key not in seen:
            seen[key] = {'name': key, 'metrics': []}
            groups.append(seen[key])
        seen[key]['metrics'].append(m)
    return groups


@app.context_processor
def inject_nav():
    return {
        'nav_categories': Category.query.filter(Category.is_active == True, Category.name != 'Circulation').order_by(Category.sort_order).all(),
        'now': datetime.now(),
    }


# ── Dashboard ────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    def _sum_month(cat_name, y, m):
        cat = Category.query.filter_by(name=cat_name).first()
        if not cat:
            return {}
        entries = Entry.query.options(joinedload(Entry.values)).filter_by(category_id=cat.id, year=y, month=m).all()
        id_to_name = {mx.id: mx.name for mx in cat.metrics}
        totals = {}
        for e in entries:
            for ev in e.values:
                n = id_to_name.get(ev.metric_id)
                if n and ev.value_number is not None:
                    totals[n] = totals.get(n, 0) + ev.value_number
        return totals

    def _v(d, k):
        v = d.get(k)
        if v is None:
            return None
        return int(v) if v == int(v) else round(v, 1)

    TYPES = PROG_TYPES
    AGE   = AGE_GROUPS

    bs_cat = Category.query.filter_by(name='Branch Stats').first()
    latest_year = latest_month = None
    kpi = kpi_prev = {}
    circ_trend_labels = circ_trend_data = gate_trend_data = []

    if bs_cat:
        # Use the latest month that has Total Branch Circulation data so that
        # imports of other metrics (e.g. door count) don't push the display
        # forward into a month where circulation is missing.
        circ_metric = next((m for m in bs_cat.metrics if m.name == 'Total Branch Circulation'), None)
        if circ_metric:
            latest_ev = (EntryValue.query
                         .join(Entry, Entry.id == EntryValue.entry_id)
                         .filter(Entry.category_id == bs_cat.id,
                                 Entry.month.isnot(None),
                                 EntryValue.metric_id == circ_metric.id)
                         .order_by(Entry.year.desc(), Entry.month.desc())
                         .first())
            latest = latest_ev.entry if latest_ev else None
        else:
            latest = (Entry.query
                      .filter_by(category_id=bs_cat.id)
                      .filter(Entry.month.isnot(None))
                      .order_by(Entry.year.desc(), Entry.month.desc())
                      .first())
        if latest:
            latest_year, latest_month = latest.year, latest.month
            prev_m = latest_month - 1 or 12
            prev_y = latest_year if latest_month > 1 else latest_year - 1

            bs_c = _sum_month('Branch Stats', latest_year, latest_month)
            os_c = _sum_month('Online Stats',  latest_year, latest_month)
            bs_p = _sum_month('Branch Stats', prev_y, prev_m)
            os_p = _sum_month('Online Stats',  prev_y, prev_m)

            def _cards(d):
                a = _v(d, 'New Library Card Registrations, Adult') or 0
                j = _v(d, 'New Library Card Registrations, Juvenile') or 0
                return a + j or None

            def _att(d):
                return sum((_v(d, f'{t} Attendance {a}') or 0) for t in TYPES for a in AGE) or None

            kpi = {
                'circulation': _v(bs_c, 'Total Branch Circulation'),
                'gate':        _v(bs_c, 'Gate Count'),
                'attendance':  _att(bs_c),
                'cards':       _cards(bs_c),
                'website':     _v(os_c, 'yclibrary.org - Web Sessions'),
                'pc':          _v(bs_c, 'PC Reservations'),
            }
            kpi_prev = {
                'circulation': _v(bs_p, 'Total Branch Circulation'),
                'gate':        _v(bs_p, 'Gate Count'),
                'attendance':  _att(bs_p),
                'cards':       _cards(bs_p),
                'website':     _v(os_p, 'yclibrary.org - Web Sessions'),
                'pc':          _v(bs_p, 'PC Reservations'),
            }

            circ_trend_labels = [m[:3] for m in MONTHS]
            circ_trend_data, gate_trend_data = [], []
            for mo in range(1, 13):
                s = _sum_month('Branch Stats', latest_year, mo)
                circ_trend_data.append(_v(s, 'Total Branch Circulation'))
                gate_trend_data.append(_v(s, 'Gate Count'))

    # Per-category: most recent entry period.
    # The "Circulation" category is an alias for SIRSI data stored in Branch Stats —
    # if it has no entries of its own, fall back to the latest Branch Stats entry
    # that has a Total Branch Circulation value so the widget shows the correct date.
    _bs_cat   = Category.query.filter_by(name='Branch Stats').first()
    _circ_m   = next((m for m in _bs_cat.metrics if m.name == 'Total Branch Circulation'), None) \
                if _bs_cat else None

    # Real service branches for per-branch drill-down (exclude lockers, desks, system-wide, admin)
    _real_branches = _real_branch_q().order_by(Branch.sort_order).all()

    coverage = []
    for cat in Category.query.filter_by(is_active=True).order_by(Category.sort_order).all():
        last = (Entry.query.filter_by(category_id=cat.id)
                .order_by(Entry.year.desc(), Entry.month.desc(), Entry.quarter.desc())
                .first())
        if last is None and cat.name == 'Circulation' and _circ_m:
            _ev = (EntryValue.query
                   .join(Entry, Entry.id == EntryValue.entry_id)
                   .filter(Entry.category_id == _bs_cat.id,
                           Entry.month.isnot(None),
                           EntryValue.metric_id == _circ_m.id)
                   .order_by(Entry.year.desc(), Entry.month.desc())
                   .first())
            last = _ev.entry if _ev else None

        branch_detail = []
        if cat.has_branch:
            # Quarterly Reference Stats is entered per Rock Hill desk
            # (Circulation, Reference, YA, Children's), never under the
            # parent "Rock Hill" branch — show the desks here too, matching
            # the branch list the actual Quarterly Ref report uses.
            _branch_list = (_branches_for_category(cat)
                            if cat.name == 'Quarterly Reference Stats' else _real_branches)
            for b in _branch_list:
                b_last = (Entry.query
                          .filter_by(category_id=cat.id, branch_id=b.id)
                          .order_by(Entry.year.desc(), Entry.month.desc(), Entry.quarter.desc())
                          .first())
                if b_last is None and cat.name == 'Circulation' and _circ_m:
                    _bev = (EntryValue.query
                            .join(Entry, Entry.id == EntryValue.entry_id)
                            .filter(Entry.category_id == _bs_cat.id,
                                    Entry.branch_id == b.id,
                                    Entry.month.isnot(None),
                                    EntryValue.metric_id == _circ_m.id)
                            .order_by(Entry.year.desc(), Entry.month.desc())
                            .first())
                    b_last = _bev.entry if _bev else None
                branch_detail.append({'branch': b, 'last_entry': b_last})

        coverage.append({'category': cat, 'last_entry': last, 'branch_detail': branch_detail})

    return render_template('index.html',
                           total_entries=Entry.query.count(),
                           total_categories=Category.query.filter_by(is_active=True).count(),
                           total_branches=_real_branch_q().count(),
                           real_branches=_real_branches,
                           latest_year=latest_year,
                           latest_month=latest_month,
                           kpi=kpi,
                           kpi_prev=kpi_prev,
                           circ_trend_labels=circ_trend_labels,
                           circ_trend_data=circ_trend_data,
                           gate_trend_data=gate_trend_data,
                           coverage=coverage,
                           months=MONTHS)


# ── Browse entries ───────────────────────────────────────────────────────────

@app.route('/entries')
def entries_list():
    cat_id = request.args.get('category', type=int)
    branch_id = request.args.get('branch', type=int)
    year = request.args.get('year', type=int)

    ILL_ICL_PSEUDO = -1  # virtual filter id for ILL/ICL entries

    def _bs_metric_filter(metric_name_set):
        """Return a query filter for Branch Stats entries containing any of the named metrics."""
        bs_cat = Category.query.filter_by(name='Branch Stats').first()
        ids = [m.id for m in (bs_cat.metrics if bs_cat else []) if m.name in metric_name_set]
        return (bs_cat, ids)

    q = Entry.query
    if cat_id == ILL_ICL_PSEUDO:
        bs_cat, ids = _bs_metric_filter(_ILL_METRICS | _ICL_METRICS)
        if bs_cat and ids:
            q = q.filter_by(category_id=bs_cat.id).filter(
                Entry.values.any(EntryValue.metric_id.in_(ids)))
    elif cat_id:
        selected_cat = db.session.get(Category, cat_id)
        if selected_cat and selected_cat.name == 'Circulation':
            bs_cat, ids = _bs_metric_filter(_CIRC_METRICS)
            if bs_cat and ids:
                q = q.filter_by(category_id=bs_cat.id).filter(
                    Entry.values.any(EntryValue.metric_id.in_(ids)))
        else:
            q = q.filter_by(category_id=cat_id)
    if branch_id:
        q = q.filter_by(branch_id=branch_id)
    if year:
        q = q.filter_by(year=year)

    entries = q.order_by(Entry.year.desc(), Entry.month.desc(),
                         Entry.submitted_at.desc()).all()
    years = [r[0] for r in db.session.query(Entry.year).distinct().order_by(Entry.year.desc()).all()]

    return render_template('entries/list.html',
                           entries=entries,
                           all_categories=Category.query.filter_by(is_active=True).order_by(Category.sort_order).all(),
                           all_branches=Branch.query.filter_by(is_active=True).order_by(Branch.name).all(),
                           available_years=years,
                           ILL_ICL_PSEUDO=ILL_ICL_PSEUDO,
                           sel_cat=cat_id, sel_branch=branch_id, sel_year=year)


# ── Create entry ─────────────────────────────────────────────────────────────

def _real_branch_q():
    """Filtered query for the 6 real service branches — excludes lockers, desks, System Wide, Administration."""
    return Branch.query.filter(
        Branch.is_active == True,
        Branch.is_desk == False,
        ~Branch.name.ilike('%locker%'),
        Branch.name != 'YCL (System Wide)',
        Branch.name != 'Administration',
    )


def _branches_for_category(category):
    """Return the branch list appropriate for a given category."""
    if category.name == 'Quarterly Reference Stats':
        # Show desks (Circ, YA) but not the parent Rock Hill branch or system-wide
        return (Branch.query.filter_by(is_active=True)
                .filter(~Branch.name.in_(['Rock Hill', 'YCL (System Wide)', 'Administration']),
                        ~Branch.name.ilike('%locker%'))
                .order_by(Branch.name).all())
    # All other categories: exclude desk-level and locker branches
    return (Branch.query.filter_by(is_active=True, is_desk=False)
            .filter(~Branch.name.ilike('%locker%'),
                    Branch.name != 'YCL (System Wide)')
            .order_by(Branch.name).all())


@app.route('/entries/new/<int:category_id>', methods=['GET', 'POST'])
def entry_create(category_id):
    category = Category.query.get_or_404(category_id)
    branches = _branches_for_category(category)
    all_metrics = Metric.query.filter_by(category_id=category_id, is_active=True).order_by(Metric.sort_order).all()
    if category.name == 'Branch Stats':
        metrics = [m for m in all_metrics if m.name not in _UPLOAD_SOURCED_METRICS]
    else:
        metrics = all_metrics
    year_range = range(datetime.now().year - 5, datetime.now().year + 2)

    if request.method == 'POST':
        year = request.form.get('year', type=int)
        if not year:
            flash('Year is required.', 'danger')
        else:
            entry = Entry(
                category_id=category_id,
                branch_id=request.form.get('branch_id', type=int) or None,
                year=year,
                month=request.form.get('month', type=int) or None,
                quarter=request.form.get('quarter', type=int) or None,
                submitted_by=current_user.username,
                notes=request.form.get('notes', '').strip(),
            )
            db.session.add(entry)
            db.session.flush()

            for m in metrics:
                raw = request.form.get(f'metric_{m.id}', '').strip()
                if raw:
                    ev = EntryValue(entry_id=entry.id, metric_id=m.id)
                    if m.data_type == 'text':
                        ev.value_text = raw
                    else:
                        try:
                            ev.value_number = float(raw)
                        except ValueError:
                            pass
                    db.session.add(ev)

            db.session.commit()
            flash('Entry submitted successfully!', 'success')
            return redirect(url_for('entry_view', entry_id=entry.id))

    return render_template('entries/form.html',
                           category=category,
                           branches=branches,
                           metric_groups=group_metrics(metrics),
                           months=MONTHS,
                           year_range=year_range,
                           entry=None,
                           values={})


# ── View entry ───────────────────────────────────────────────────────────────

@app.route('/entries/<int:entry_id>')
def entry_view(entry_id):
    entry = Entry.query.get_or_404(entry_id)
    all_metrics = Metric.query.filter_by(category_id=entry.category_id).order_by(Metric.sort_order).all()
    values = {ev.metric_id: ev for ev in entry.values}
    return render_template('entries/view.html',
                           entry=entry,
                           metric_groups=group_metrics(all_metrics),
                           values=values)


# ── Edit entry ───────────────────────────────────────────────────────────────

@app.route('/entries/<int:entry_id>/edit', methods=['GET', 'POST'])
def entry_edit(entry_id):
    entry = Entry.query.get_or_404(entry_id)
    category = entry.category
    branches = _branches_for_category(category)
    all_metrics = Metric.query.filter_by(category_id=category.id, is_active=True).order_by(Metric.sort_order).all()
    if category.name == 'Branch Stats':
        metrics = [m for m in all_metrics if m.name not in _UPLOAD_SOURCED_METRICS]
    else:
        metrics = all_metrics
    values = {ev.metric_id: ev for ev in entry.values}
    year_range = range(datetime.now().year - 5, datetime.now().year + 2)

    if request.method == 'POST':
        entry.branch_id = request.form.get('branch_id', type=int) or None
        entry.year = request.form.get('year', type=int)
        entry.month = request.form.get('month', type=int) or None
        entry.quarter = request.form.get('quarter', type=int) or None
        entry.submitted_by = current_user.username
        entry.notes = request.form.get('notes', '').strip()

        for m in metrics:
            raw = request.form.get(f'metric_{m.id}', '').strip()
            ev = values.get(m.id)
            if raw:
                if ev is None:
                    ev = EntryValue(entry_id=entry.id, metric_id=m.id)
                    db.session.add(ev)
                if m.data_type == 'text':
                    ev.value_text = raw
                    ev.value_number = None
                else:
                    try:
                        ev.value_number = float(raw)
                        ev.value_text = None
                    except ValueError:
                        pass
            elif ev is not None:
                db.session.delete(ev)

        db.session.commit()
        flash('Entry updated successfully!', 'success')
        return redirect(url_for('entry_view', entry_id=entry.id))

    return render_template('entries/form.html',
                           category=category,
                           branches=branches,
                           metric_groups=group_metrics(metrics),
                           months=MONTHS,
                           year_range=year_range,
                           entry=entry,
                           values=values)


# ── Delete entry ─────────────────────────────────────────────────────────────

@app.route('/entries/<int:entry_id>/delete', methods=['POST'])
@admin_required
def entry_delete(entry_id):
    entry = Entry.query.get_or_404(entry_id)
    db.session.delete(entry)
    db.session.commit()
    flash('Entry deleted.', 'info')
    return redirect(url_for('entries_list'))


# ── Admin: Categories ─────────────────────────────────────────────────────────

@app.route('/admin/categories', methods=['GET', 'POST'])
def admin_categories():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Name is required.', 'danger')
        elif Category.query.filter_by(name=name).first():
            flash(f'Category "{name}" already exists.', 'warning')
        else:
            max_ord = db.session.query(db.func.max(Category.sort_order)).scalar() or 0
            db.session.add(Category(
                name=name,
                description=request.form.get('description', '').strip(),
                frequency=request.form.get('frequency', 'monthly'),
                has_branch='has_branch' in request.form,
                sort_order=max_ord + 1,
            ))
            db.session.commit()
            flash(f'Category "{name}" created.', 'success')
        return redirect(url_for('admin_categories'))

    return render_template('admin/categories.html',
                           categories=Category.query.order_by(Category.sort_order).all())


@app.route('/admin/categories/<int:cat_id>', methods=['GET', 'POST'])
def admin_category_edit(cat_id):
    cat = Category.query.get_or_404(cat_id)

    if request.method == 'POST':
        cat.name = request.form.get('name', cat.name).strip()
        cat.description = request.form.get('description', '').strip()
        cat.frequency = request.form.get('frequency', cat.frequency)
        cat.has_branch = 'has_branch' in request.form
        db.session.commit()
        flash('Category updated.', 'success')
        return redirect(url_for('admin_category_edit', cat_id=cat_id))

    metrics = Metric.query.filter_by(category_id=cat_id).order_by(Metric.sort_order).all()
    return render_template('admin/category_edit.html', cat=cat, metrics=metrics)


@app.route('/admin/categories/<int:cat_id>/toggle', methods=['POST'])
def admin_category_toggle(cat_id):
    cat = Category.query.get_or_404(cat_id)
    cat.is_active = not cat.is_active
    db.session.commit()
    flash(f'Category {"activated" if cat.is_active else "deactivated"}.', 'success')
    return redirect(url_for('admin_categories'))


@app.route('/admin/categories/<int:cat_id>/delete', methods=['POST'])
def admin_category_delete(cat_id):
    cat = Category.query.get_or_404(cat_id)
    if Entry.query.filter_by(category_id=cat_id).count():
        flash('Cannot delete a category that has existing entries. Deactivate it instead.', 'danger')
    else:
        db.session.delete(cat)
        db.session.commit()
        flash('Category deleted.', 'info')
    return redirect(url_for('admin_categories'))


# ── Admin: Metrics ────────────────────────────────────────────────────────────

@app.route('/admin/categories/<int:cat_id>/metrics/add', methods=['POST'])
def admin_metric_add(cat_id):
    Category.query.get_or_404(cat_id)
    name = request.form.get('name', '').strip()
    if not name:
        flash('Metric name is required.', 'danger')
    else:
        max_ord = db.session.query(db.func.max(Metric.sort_order)).filter_by(category_id=cat_id).scalar() or 0
        db.session.add(Metric(
            category_id=cat_id,
            name=name,
            description=request.form.get('description', '').strip(),
            group_name=request.form.get('group_name', '').strip(),
            data_type=request.form.get('data_type', 'integer'),
            sort_order=max_ord + 1,
        ))
        db.session.commit()
        flash(f'Metric "{name}" added.', 'success')
    return redirect(url_for('admin_category_edit', cat_id=cat_id))


@app.route('/admin/metrics/<int:metric_id>/edit', methods=['GET', 'POST'])
def admin_metric_edit(metric_id):
    m = Metric.query.get_or_404(metric_id)
    if request.method == 'POST':
        m.name = request.form.get('name', m.name).strip()
        m.description = request.form.get('description', '').strip()
        m.group_name = request.form.get('group_name', '').strip()
        m.data_type = request.form.get('data_type', m.data_type)
        db.session.commit()
        flash('Metric updated.', 'success')
        return redirect(url_for('admin_category_edit', cat_id=m.category_id))
    return render_template('admin/metric_edit.html', metric=m)


@app.route('/admin/metrics/<int:metric_id>/toggle', methods=['POST'])
def admin_metric_toggle(metric_id):
    m = Metric.query.get_or_404(metric_id)
    m.is_active = not m.is_active
    db.session.commit()
    flash(f'Metric {"activated" if m.is_active else "deactivated"}.', 'success')
    return redirect(url_for('admin_category_edit', cat_id=m.category_id))


@app.route('/admin/metrics/<int:metric_id>/delete', methods=['POST'])
def admin_metric_delete(metric_id):
    m = Metric.query.get_or_404(metric_id)
    cat_id = m.category_id
    if EntryValue.query.filter_by(metric_id=metric_id).count():
        m.is_active = False
        db.session.commit()
        flash('Metric deactivated — cannot delete because it has recorded data.', 'warning')
    else:
        db.session.delete(m)
        db.session.commit()
        flash('Metric deleted.', 'info')
    return redirect(url_for('admin_category_edit', cat_id=cat_id))


# ── Admin: Branches ───────────────────────────────────────────────────────────

@app.route('/admin/branches', methods=['GET', 'POST'])
def admin_branches():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Branch name is required.', 'danger')
        elif Branch.query.filter_by(name=name).first():
            flash(f'Branch "{name}" already exists.', 'warning')
        else:
            max_ord = db.session.query(db.func.max(Branch.sort_order)).scalar() or 0
            db.session.add(Branch(name=name, sort_order=max_ord + 1))
            db.session.commit()
            flash(f'Branch "{name}" added.', 'success')
        return redirect(url_for('admin_branches'))

    return render_template('admin/branches.html',
                           branches=Branch.query.order_by(Branch.name).all())


@app.route('/admin/branches/<int:branch_id>/toggle', methods=['POST'])
def admin_branch_toggle(branch_id):
    b = Branch.query.get_or_404(branch_id)
    b.is_active = not b.is_active
    db.session.commit()
    flash(f'Branch {"activated" if b.is_active else "deactivated"}.', 'success')
    return redirect(url_for('admin_branches'))


@app.route('/admin/branches/<int:branch_id>/delete', methods=['POST'])
def admin_branch_delete(branch_id):
    b = Branch.query.get_or_404(branch_id)
    if Entry.query.filter_by(branch_id=branch_id).count():
        flash('Cannot delete a branch with existing entries. Deactivate it instead.', 'danger')
    else:
        db.session.delete(b)
        db.session.commit()
        flash('Branch deleted.', 'info')
    return redirect(url_for('admin_branches'))


# ── Reports ───────────────────────────────────────────────────────────────────

def report_data_table(metrics, branch_list, data):
    """
    Build grouped table rows for report templates.
    data: {branch_id_or_None: {metric_id: value}}  (value = float or string)
    Returns list of groups: [{name, rows: [{metric, cells, row_total}]}]
    row_total is summed across branches when values are numeric, else '—'.
    """
    def fmt(v):
        if v is None:
            return '—'
        if isinstance(v, float):
            return f"{int(v):,}" if v == int(v) else f"{v:,.2f}".rstrip('0').rstrip('.')
        return str(v) if v != '' else '—'

    groups, seen = [], {}
    for m in metrics:
        key = m.group_name or ''
        if key not in seen:
            seen[key] = {'name': key, 'rows': []}
            groups.append(seen[key])
        row_sum = 0
        has_numeric = False
        cells = []
        for b in branch_list:
            v = data.get(b.id if b else None, {}).get(m.id)
            if isinstance(v, (int, float)):
                row_sum += v
                has_numeric = True
            cells.append(fmt(v))
        row_total = fmt(row_sum) if has_numeric else '—'
        seen[key]['rows'].append({'metric': m, 'cells': cells, 'row_total': row_total})
    return groups


def metrics_by_category_json():
    """Return {cat_id: [{id, name}]} for use in JS cascading dropdowns."""
    result = {}
    for cat in Category.query.filter_by(is_active=True).all():
        result[cat.id] = [
            {'id': m.id, 'name': m.name}
            for m in Metric.query.filter_by(category_id=cat.id, is_active=True)
                                 .order_by(Metric.sort_order).all()
        ]
    return result


def _xlsx_response(wb, filename):
    """Serialize a workbook to a Flask send_file response."""
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(
        buf,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename,
    )


def _xl_header(ws, bold_font, text):
    """Write a bold section header row and return the next row index."""
    from openpyxl.styles import PatternFill
    ws.append([text])
    row = ws.max_row
    ws.cell(row, 1).font = bold_font
    ws.cell(row, 1).fill = PatternFill('solid', fgColor='D9E1F2')
    return row + 1


@app.route('/reports')
def reports_index():
    return render_template('reports/index.html')


@app.route('/reports/monthly')
def report_monthly():
    cat_id = request.args.get('category', type=int)
    year   = request.args.get('year',     type=int)
    month  = request.args.get('month',    type=int)

    categories = Category.query.filter(Category.is_active == True, Category.name != 'Circulation').order_by(Category.sort_order).all()
    available_years = [r[0] for r in db.session.query(Entry.year).distinct()
                                                .order_by(Entry.year.desc()).all()]
    table = branches = category = None

    if cat_id and year and month:
        category = Category.query.get_or_404(cat_id)
        metrics  = Metric.query.filter_by(category_id=cat_id, is_active=True).order_by(Metric.sort_order).all()
        entries  = Entry.query.options(joinedload(Entry.values)).filter_by(category_id=cat_id, year=year, month=month).all()

        # Show every branch that has ever reported for this category, even if
        # this specific month has no entry yet (rendered as blank by report_data_table).
        branch_set = {r[0] for r in db.session.query(Entry.branch_id)
                                               .filter_by(category_id=cat_id).distinct().all()}
        data = {}
        for e in entries:
            if e.branch_id not in data:
                data[e.branch_id] = {}
            for ev in e.values:
                # Store raw float so report_data_table can compute row totals;
                # fall back to text for text-type metrics
                if ev.metric.data_type == 'text':
                    data[e.branch_id][ev.metric_id] = ev.value_text or ''
                else:
                    data[e.branch_id][ev.metric_id] = ev.value_number

        branches = sorted(
            [b for b in (Branch.query.get(bid) for bid in branch_set) if b and b.name != 'Administration'],
            key=lambda b: b.name
        )
        table = report_data_table(metrics, branches if branches else [None], data)

    return render_template('reports/monthly.html',
                           categories=categories, available_years=available_years,
                           months=MONTHS, sel_cat=cat_id, sel_year=year, sel_month=month,
                           category=category, table=table, branches=branches)


@app.route('/reports/trend')
def report_trend():
    cat_id     = request.args.get('category', type=int)
    metric_id  = request.args.get('metric',   type=int)
    years      = request.args.getlist('year', type=int)
    branch_ids = request.args.getlist('branches', type=int)

    categories  = Category.query.filter(Category.is_active == True, Category.name != 'Circulation').order_by(Category.sort_order).all()
    fy_rows = db.session.query(Entry.year, Entry.month).filter(Entry.month.isnot(None)).distinct().all()
    _now = datetime.now(); _cur_fy = _now.year + 1 if _now.month >= 7 else _now.year
    fy_set = set()
    for yr, mo in fy_rows:
        fy_set.add(yr + 1 if mo >= 7 else yr)
    available_years = sorted(y for y in fy_set if y <= _cur_fy)
    metrics_json = metrics_by_category_json()
    chart_data   = None
    metric = category = None

    FY_MONTHS = list(range(7, 13)) + list(range(1, 7))  # Jul–Dec then Jan–Jun

    if cat_id and metric_id and years:
        category = Category.query.get_or_404(cat_id)
        metric   = Metric.query.get_or_404(metric_id)
        years_sorted = sorted(years)

        # Build a chronological (cal_year, month) sequence across all selected FYs
        all_month_keys = [
            (fy - 1 if mo >= 7 else fy, mo)
            for fy in years_sorted
            for mo in FY_MONTHS
        ]
        multi = len(years_sorted) > 1
        labels = [f"{MONTHS[mo-1][:3]} '{str(yr)[2:]}" if multi else MONTHS[mo-1][:3]
                  for yr, mo in all_month_keys]

        datasets = []
        colors   = ['#2c6e8a','#e74c3c','#27ae60','#f39c12','#8e44ad',
                    '#16a085','#d35400','#2980b9','#c0392b','#1abc9c']

        if category.has_branch:
            real_branches = _real_branch_q().order_by(Branch.name).all()
            locker_branches = Branch.query.filter(
                Branch.is_active == True,
                Branch.name.ilike('%locker%'),
            ).all()
            selected = [b for b in real_branches if b.id in branch_ids] if branch_ids else real_branches
            for i, b in enumerate(selected):
                lockers = [lb for lb in locker_branches
                           if lb.name.lower().startswith(b.name.lower())]
                pts = []
                for yr, mo in all_month_keys:
                    total = None
                    e = Entry.query.filter_by(category_id=cat_id, branch_id=b.id,
                                              year=yr, month=mo).first()
                    ev = EntryValue.query.filter_by(entry_id=e.id, metric_id=metric_id).first() if e else None
                    if ev and ev.value_number is not None:
                        total = ev.value_number
                    for lb in lockers:
                        le = Entry.query.filter_by(category_id=cat_id, branch_id=lb.id,
                                                   year=yr, month=mo).first()
                        lev = EntryValue.query.filter_by(entry_id=le.id, metric_id=metric_id).first() if le else None
                        if lev and lev.value_number is not None:
                            total = (total or 0) + lev.value_number
                    pts.append(total)
                datasets.append({'label': b.name, 'data': pts, 'tension': 0.3,
                                 'spanGaps': True, 'borderColor': colors[i % len(colors)],
                                 'backgroundColor': colors[i % len(colors)] + '22'})
        else:
            pts = []
            for yr, mo in all_month_keys:
                e = Entry.query.filter_by(category_id=cat_id, year=yr, month=mo).first()
                ev = EntryValue.query.filter_by(entry_id=e.id, metric_id=metric_id).first() if e else None
                pts.append(ev.value_number if ev else None)
            datasets.append({'label': metric.name, 'data': pts, 'tension': 0.3,
                             'spanGaps': True, 'borderColor': colors[0],
                             'backgroundColor': colors[0] + '22'})

        chart_data = {'labels': labels, 'datasets': datasets}

    all_branches = _real_branch_q().order_by(Branch.name).all()
    return render_template('reports/trend.html',
                           categories=categories, available_years=available_years,
                           all_branches=all_branches, metrics_json=metrics_json,
                           sel_cat=cat_id, sel_metric=metric_id,
                           sel_years=years, sel_branches=branch_ids,
                           category=category, metric=metric, chart_data=chart_data)


@app.route('/reports/programming')
def report_programming():
    year      = request.args.get('year',   type=int)
    month     = request.args.get('month',  type=int)
    branch_id = request.args.get('branch', type=int)

    available_years = [r[0] for r in db.session.query(Entry.year).distinct()
                                                .order_by(Entry.year.desc()).all()]
    branches = _real_branch_q().order_by(Branch.name).all()
    TYPES      = PROG_TYPES
    summary = outreach = None

    if year:
        cat = Category.query.filter_by(name='Branch Stats').first()
        if cat:
            all_metrics = {m.name: m for m in cat.metrics}
            q = Entry.query.options(joinedload(Entry.values)).filter_by(category_id=cat.id, year=year)
            if month:
                q = q.filter_by(month=month)
            if branch_id:
                q = q.filter_by(branch_id=branch_id)
            entries = q.all()

            ev_map = {}
            for e in entries:
                ev_map[e.id] = {ev.metric_id: (ev.value_number or 0) for ev in e.values}

            summary = {}
            for ptype in TYPES:
                summary[ptype] = {}
                for age in AGE_GROUPS:
                    sm = all_metrics.get(f'{ptype} Sessions {age}')
                    am = all_metrics.get(f'{ptype} Attendance {age}')
                    sess = sum(ev_map.get(e.id, {}).get(sm.id, 0) for e in entries) if sm else 0
                    att  = sum(ev_map.get(e.id, {}).get(am.id, 0) for e in entries) if am else 0
                    summary[ptype][age] = {'sessions': int(sess), 'attendance': int(att)}

            # Outreach totals
            def _sum(name):
                m = all_metrics.get(name)
                return int(sum(ev_map.get(e.id, {}).get(m.id, 0) for e in entries)) if m else 0

            outreach = {
                'activities':  _sum('Number of Outreach Activities Conducted'),
                'attendance':  _sum('Outreach Attendance'),
                'passive':     _sum('Take & Makes / Other Passive Program Participants'),
            }

    return render_template('reports/programming.html',
                           available_years=available_years, branches=branches,
                           months=MONTHS, sel_year=year, sel_month=month,
                           sel_branch=branch_id, summary=summary, outreach=outreach,
                           prog_types=TYPES, age_groups=AGE_GROUPS)


@app.route('/reports/online')
def report_online():
    year  = request.args.get('year',  type=int)
    month = request.args.get('month', type=int)

    available_years = [r[0] for r in db.session.query(Entry.year).distinct()
                                                .order_by(Entry.year.desc()).all()]
    stats = groups = None

    if year and month:
        cat = Category.query.filter_by(name='Online Stats').first()
        if cat:
            metrics = Metric.query.filter_by(category_id=cat.id, is_active=True).order_by(Metric.sort_order).all()
            curr_entry = Entry.query.filter_by(category_id=cat.id, year=year, month=month).first()
            prev_month = month - 1 or 12
            prev_year  = year if month > 1 else year - 1
            prev_entry = Entry.query.filter_by(category_id=cat.id, year=prev_year, month=prev_month).first()

            curr_vals = {ev.metric_id: ev.value_number for ev in curr_entry.values} if curr_entry else {}
            prev_vals = {ev.metric_id: ev.value_number for ev in prev_entry.values} if prev_entry else {}

            stats = []
            for m in metrics:
                cv = curr_vals.get(m.id)
                pv = prev_vals.get(m.id)
                if cv is None:
                    continue
                delta = (cv - pv) if pv is not None else None
                delta_pct = round((delta / pv) * 100, 1) if (delta is not None and pv) else None
                stats.append({'metric': m, 'value': cv, 'prev': pv,
                              'delta': delta, 'delta_pct': delta_pct})

            groups = group_metrics(metrics)

    return render_template('reports/online.html',
                           available_years=available_years, months=MONTHS,
                           sel_year=year, sel_month=month, stats=stats,
                           stats_by_id={s['metric'].id: s for s in stats} if stats else {},
                           groups=groups)


@app.route('/reports/yearoveryear')
def report_yoy():
    cat_id    = request.args.get('category', type=int)
    branch_id = request.args.get('branch',   type=int)
    metric_id = request.args.get('metric',   type=int)
    mode      = request.args.get('mode', 'annual')
    years     = sorted(request.args.getlist('years', type=int))  # fiscal years (e.g. 2024 = Jul 2023–Jun 2024)

    categories   = Category.query.filter(Category.is_active == True, ~Category.name.in_(['Circulation', 'Quarterly Reference Stats'])).order_by(Category.sort_order).all()
    metrics_json = metrics_by_category_json()

    # Derive available fiscal years from stored data
    fy_rows = db.session.query(Entry.year, Entry.month, Entry.quarter).filter(
        or_(Entry.month.isnot(None), Entry.quarter.isnot(None))
    ).distinct().all()
    _now = datetime.now(); _cur_fy = _now.year + 1 if _now.month >= 7 else _now.year
    fy_set = set()
    for yr, mo, q in fy_rows:
        if mo is not None:
            fy_set.add(yr + 1 if mo >= 7 else yr)
        if q is not None:
            fy_set.add(yr + 1 if q in (3, 4) else yr)
    available_years = sorted(y for y in fy_set if y <= _cur_fy)

    all_branches = _real_branch_q().order_by(Branch.name).all()
    table = col_headers = chart_data = category = metric = annual_chart_json = None

    # Fiscal month order: Jul→Jun
    FY_MONTHS = list(range(7, 13)) + list(range(1, 7))
    FY_MONTH_LABELS = ['Jul','Aug','Sep','Oct','Nov','Dec','Jan','Feb','Mar','Apr','May','Jun']

    if cat_id and len(years) >= 2:
        category = Category.query.get_or_404(cat_id)
        metrics  = Metric.query.filter_by(category_id=cat_id, is_active=True).order_by(Metric.sort_order).all()
        colors   = ['#2c6e8a','#e74c3c','#27ae60','#f39c12','#8e44ad','#16a085']

        def _entries(fy_year):
            # Fetch Jul(fy_year-1)–Jun(fy_year), handling monthly and quarterly entries
            q = Entry.query.options(joinedload(Entry.values)).filter_by(category_id=cat_id).filter(
                or_(
                    and_(Entry.year == fy_year - 1,
                         or_(Entry.month >= 7, Entry.quarter.in_([3, 4]))),
                    and_(Entry.year == fy_year,
                         or_(Entry.month <= 6, Entry.quarter.in_([1, 2])))
                )
            )
            if branch_id and category.has_branch:
                q = q.filter_by(branch_id=branch_id)
            return q.all()

        def _fmt(v):
            if not v:
                return '—'
            return str(int(v)) if v == int(v) else f"{v:.1f}"

        def _pct(old, new):
            if not old:
                return None
            p = round(((new - old) / old) * 100, 1)
            return ('+' if p > 0 else '') + str(p) + '%'

        if mode == 'annual':
            # totals[metric_id][fy_year] = sum across Jul–Jun
            totals = {m.id: {} for m in metrics}
            for fy_year in years:
                for e in _entries(fy_year):
                    for ev in e.values:
                        if ev.value_number and ev.metric_id in totals:
                            totals[ev.metric_id][fy_year] = totals[ev.metric_id].get(fy_year, 0) + ev.value_number

            # Column headers: FY2024, [Δ FY2023→FY2024], ...
            col_headers = []
            for j, y in enumerate(years):
                col_headers.append({'label': f'FY{y}', 'is_change': False})
                if j > 0:
                    col_headers.append({'label': f'Δ FY{years[j-1]}→FY{y}', 'is_change': True})

            # Build grouped table
            groups, seen = [], {}
            for m in metrics:
                key = m.group_name or ''
                if key not in seen:
                    seen[key] = {'name': key, 'rows': []}
                    groups.append(seen[key])
                cells = []
                for j, y in enumerate(years):
                    val = totals[m.id].get(y, 0)
                    cells.append({'val': _fmt(val), 'is_change': False})
                    if j > 0:
                        prev = totals[m.id].get(years[j - 1], 0)
                        cells.append({'val': _pct(prev, val) or '—', 'is_change': True,
                                      'up': val > prev if val and prev else None})
                seen[key]['rows'].append({'metric': m, 'cells': cells})
            table = groups

            # Chart data for client-side bar chart (no extra queries)
            annual_chart_json = {
                str(m.id): {
                    'name': m.name,
                    'values': [totals[m.id].get(y, 0) for y in years]
                }
                for m in metrics
            }

        elif mode == 'monthly' and metric_id:
            metric = Metric.query.get_or_404(metric_id)
            # monthly_data[calendar_month][fy_year] = value
            monthly_data = {mo: {} for mo in FY_MONTHS}
            for fy_year in years:
                for e in _entries(fy_year):
                    if e.month:
                        for ev in e.values:
                            if ev.metric_id == metric_id and ev.value_number is not None:
                                monthly_data[e.month][fy_year] = ev.value_number

            # Chart — X axis is Jul→Jun
            datasets = []
            for i, fy_year in enumerate(years):
                pts = [monthly_data[mo].get(fy_year) for mo in FY_MONTHS]
                datasets.append({'label': f'FY{fy_year}', 'data': pts, 'tension': 0.3,
                                 'spanGaps': True, 'borderColor': colors[i % len(colors)],
                                 'backgroundColor': colors[i % len(colors)] + '22'})
            chart_data = {'labels': FY_MONTH_LABELS, 'datasets': datasets}

            # Table: rows = Jul–Jun months, cols = FY years + % change
            col_headers = []
            for j, y in enumerate(years):
                col_headers.append({'label': f'FY{y}', 'is_change': False})
                if j > 0:
                    col_headers.append({'label': f'Δ FY{years[j-1]}→FY{y}', 'is_change': True})

            table = []
            for mo, label in zip(FY_MONTHS, FY_MONTH_LABELS):
                cells = []
                for j, y in enumerate(years):
                    val  = monthly_data[mo].get(y)
                    cells.append({'val': _fmt(val) if val is not None else '—', 'is_change': False})
                    if j > 0:
                        prev = monthly_data[mo].get(years[j - 1])
                        cells.append({'val': _pct(prev, val) if (val and prev) else '—',
                                      'is_change': True,
                                      'up': val > prev if (val and prev) else None})
                table.append({'label': label, 'cells': cells})

    chart_year_labels = [f'FY{y}' for y in years]
    return render_template('reports/yearoveryear.html',
                           categories=categories, available_years=available_years,
                           metrics_json=metrics_json, all_branches=all_branches,
                           sel_cat=cat_id, sel_branch=branch_id, sel_metric=metric_id,
                           sel_mode=mode, sel_years=years,
                           category=category, metric=metric,
                           col_headers=col_headers, table=table, chart_data=chart_data,
                           annual_chart_json=annual_chart_json, chart_years=chart_year_labels)


@app.route('/reports/fiscal')
def report_fiscal():
    from sqlalchemy import or_, and_
    cat_id  = request.args.get('category', type=int)
    fy_year = request.args.get('fy_year',  type=int)  # FY2025 = Jul 2024 – Jun 2025

    categories = Category.query.filter(
        Category.is_active == True,
        Category.name != 'Circulation'
    ).order_by(Category.sort_order).all()

    # Derive available fiscal years from any entry that has a month or quarter
    rows = db.session.query(Entry.year, Entry.month, Entry.quarter).filter(
        or_(Entry.month.isnot(None), Entry.quarter.isnot(None))
    ).distinct().all()
    _now = datetime.now(); _cur_fy = _now.year + 1 if _now.month >= 7 else _now.year
    fy_set = set()
    for yr, mo, q in rows:
        if mo is not None:
            fy_set.add(yr + 1 if mo >= 7 else yr)
        if q is not None:
            fy_set.add(yr + 1 if q in (3, 4) else yr)
    available_fy = sorted((y for y in fy_set if y <= _cur_fy), reverse=True)

    table = branches = category = fy_label = None

    if cat_id and fy_year:
        category = Category.query.get_or_404(cat_id)
        metrics  = Metric.query.filter_by(category_id=cat_id, is_active=True).order_by(Metric.sort_order).all()
        fy_label = f'FY{fy_year}  (Jul {fy_year - 1} – Jun {fy_year})'

        # Monthly categories: months 7-12 of fy_year-1 and months 1-6 of fy_year
        # Quarterly categories: Q3+Q4 of fy_year-1 and Q1+Q2 of fy_year
        entries = Entry.query.options(joinedload(Entry.values)).filter_by(category_id=cat_id).filter(
            or_(
                and_(Entry.year == fy_year - 1,
                     or_(Entry.month >= 7, Entry.quarter.in_([3, 4]))),
                and_(Entry.year == fy_year,
                     or_(Entry.month <= 6, Entry.quarter.in_([1, 2])))
            )
        ).all()

        if category.has_branch:
            bid_set  = {e.branch_id for e in entries if e.branch_id}
            branches = sorted(
                [b for b in (Branch.query.get(bid) for bid in bid_set) if b
                 and b.name != 'Administration'
                 and b.name != 'YCL (System Wide)'
                 and 'locker' not in b.name.lower()
                 and not b.is_desk],
                key=lambda b: b.name
            )
        else:
            branches = []

        branch_list = branches if branches else [None]
        totals = {}
        for e in entries:
            key = e.branch_id if category.has_branch else None
            if key not in totals:
                totals[key] = {}
            for ev in e.values:
                if ev.value_number is not None:
                    totals[key][ev.metric_id] = totals[key].get(ev.metric_id, 0) + ev.value_number

        table = report_data_table(metrics, branch_list, totals)

        # Detect empty-alias categories (e.g. Circulation — data lives in Branch Stats)
        if not table or all(not g['rows'] for g in table):
            has_any_entries = db.session.query(Entry.id).filter_by(
                category_id=cat_id).limit(1).scalar() is not None
            if not has_any_entries:
                bs_cat = Category.query.filter_by(name='Branch Stats').first()
                table = '__alias__'
                alias_target = bs_cat

    if table and table != '__alias__' and request.args.get('format') == 'xlsx':
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        wb = Workbook()
        ws = wb.active
        ws.title = category.name[:31]
        bold = Font(bold=True)

        # Title row
        ws.append([f'{category.name} — {fy_label}'])
        ws.cell(1, 1).font = Font(bold=True, size=13)
        ws.append([])

        # Header row
        hdr = ['Metric'] + [b.name for b in branches] + (['Total'] if len(branches) > 1 else [])
        ws.append(hdr)
        hr = ws.max_row
        for col in range(1, len(hdr) + 1):
            ws.cell(hr, col).font = bold
            ws.cell(hr, col).fill = PatternFill('solid', fgColor='2C6E8A')
            ws.cell(hr, col).font = Font(bold=True, color='FFFFFF')

        for group in table:
            if group['name']:
                ws.append([group['name']])
                r = ws.max_row
                ws.cell(r, 1).font = Font(bold=True)
                ws.cell(r, 1).fill = PatternFill('solid', fgColor='D9E1F2')
                ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=len(hdr))
            for row in group['rows']:
                def _num(s):
                    try: return float(s.replace(',', ''))
                    except Exception: return s
                vals = [row['metric'].name] + [_num(c) for c in row['cells']]
                if len(branches) > 1:
                    vals.append(_num(row['row_total']))
                ws.append(vals)

        ws.column_dimensions['A'].width = 42
        for i in range(len(branches) + 1):
            col_letter = ws.cell(1, i + 2).column_letter
            ws.column_dimensions[col_letter].width = 16

        return _xlsx_response(wb, f'fiscal_{category.name.replace(" ", "_")}_{fy_year}.xlsx')

    return render_template('reports/fiscal.html',
                           categories=categories, available_fy=available_fy,
                           sel_cat=cat_id, sel_fy=fy_year,
                           category=category, table=table, branches=branches,
                           fy_label=fy_label,
                           alias_target=locals().get('alias_target'))


# ── Fiscal-year helper ────────────────────────────────────────────────────────

def _available_fy():
    """Sorted list of fiscal years (descending) derived from monthly entry data."""
    now = datetime.now()
    current_fy = now.year + 1 if now.month >= 7 else now.year
    rows = db.session.query(Entry.year, Entry.month).filter(Entry.month.isnot(None)).distinct().all()
    fy_set = set()
    for yr, mo in rows:
        fy_set.add(yr + 1 if mo >= 7 else yr)
    return sorted((y for y in fy_set if y <= current_fy), reverse=True)


def _fy_label(fy_year):
    return f'FY{fy_year}  (Jul {fy_year - 1} – Jun {fy_year})'


# ── Branch Scorecard ─────────────────────────────────────────────────────────

@app.route('/reports/annual')
def report_annual():
    from sqlalchemy import or_, and_
    fy_year = request.args.get('fy_year', type=int)

    branches = _real_branch_q().order_by(Branch.name).all()

    TYPES = PROG_TYPES
    AGES  = AGE_GROUPS

    COLS = [
        ('Circulation',         'Total Branch Circulation'),
        ('Gate Count',          'Gate Count'),
        ('Cards (Adult)',       'New Library Card Registrations, Adult'),
        ('Cards (Juv.)',        'New Library Card Registrations, Juvenile'),
        ('PC Reservations',     'PC Reservations'),
        ('WiFi Sessions',       'WiFi - Unique Sessions'),
        ('Prog. Sessions',      '_prog_sessions'),
        ('Prog. Attendance',    '_prog_attendance'),
        ('Outreach Activities', 'Number of Outreach Activities Conducted'),
        ('1-on-1 Sessions',     '1-on-1 Total for Month'),
    ]

    scorecard = sys_totals = col_maxes = None

    if fy_year:
        bs_cat = Category.query.filter_by(name='Branch Stats').first()
        if bs_cat:
            id_to_name = {m.id: m.name for m in bs_cat.metrics}

            entries = Entry.query.options(joinedload(Entry.values)).filter_by(category_id=bs_cat.id).filter(
                or_(
                    and_(Entry.year == fy_year - 1, Entry.month >= 7),
                    and_(Entry.year == fy_year,     Entry.month <= 6)
                )
            ).all()

            branch_sums = {b.id: {} for b in branches}
            for e in entries:
                if e.branch_id not in branch_sums:
                    continue
                for ev in e.values:
                    n = id_to_name.get(ev.metric_id)
                    if n and ev.value_number is not None:
                        branch_sums[e.branch_id][n] = branch_sums[e.branch_id].get(n, 0) + ev.value_number

            sess_keys = [f'{t} Sessions {a}' for t in TYPES for a in AGES]
            att_keys  = [f'{t} Attendance {a}' for t in TYPES for a in AGES]

            scorecard = []
            raw_totals = {}
            for b in branches:
                sums = branch_sums[b.id]
                sums['_prog_sessions']   = sum(sums.get(k, 0) for k in sess_keys) or None
                sums['_prog_attendance'] = sum(sums.get(k, 0) for k in att_keys)  or None

                row_vals = []
                for _, key in COLS:
                    v = sums.get(key)
                    val = int(v) if v and v == int(v) else (round(v, 1) if v else None)
                    row_vals.append(val)
                    if val:
                        raw_totals[key] = raw_totals.get(key, 0) + val
                scorecard.append({'branch': b, 'cells': row_vals})

            sys_totals = [raw_totals.get(key) for _, key in COLS]
            col_maxes  = []
            for i in range(len(COLS)):
                vals = [r['cells'][i] for r in scorecard if r['cells'][i]]
                col_maxes.append(max(vals) if vals else 1)

    return render_template('reports/annual.html',
                           available_fy=_available_fy(),
                           cols=COLS,
                           branches=branches,
                           sel_fy=fy_year,
                           fy_label=_fy_label(fy_year) if fy_year else None,
                           scorecard=scorecard,
                           sys_totals=sys_totals,
                           col_maxes=col_maxes)


@app.route('/reports/branch_summary')
def report_branch_summary():
    from sqlalchemy import or_, and_
    branch_id = request.args.get('branch',  type=int)
    fy_year   = request.args.get('fy_year', type=int)

    branches     = _real_branch_q().order_by(Branch.name).all()
    available_fy = _available_fy()

    branch = sections = fy_label = None

    if branch_id and fy_year:
        branch   = db.session.get(Branch, branch_id) or next((b for b in branches if b.id == branch_id), None)
        fy_label = _fy_label(fy_year)

        fy_filter = or_(
            and_(Entry.year == fy_year - 1,
                 or_(Entry.month >= 7, Entry.quarter.in_([3, 4]))),
            and_(Entry.year == fy_year,
                 or_(Entry.month <= 6, Entry.quarter.in_([1, 2])))
        )

        categories = Category.query.filter(
            Category.is_active == True,
            Category.name != 'Circulation'
        ).order_by(Category.sort_order).all()

        def _fmt(v):
            if v is None:
                return '—'
            return f"{int(v):,}" if v == int(v) else f"{v:,.2f}".rstrip('0').rstrip('.')

        sections = []
        for cat in categories:
            metrics = Metric.query.filter_by(
                category_id=cat.id, is_active=True
            ).order_by(Metric.sort_order).all()
            if not metrics:
                continue

            q = Entry.query.options(joinedload(Entry.values)).filter_by(
                category_id=cat.id
            ).filter(fy_filter)
            if cat.has_branch:
                q = q.filter(Entry.branch_id == branch_id)
            entries = q.all()

            totals = {}
            for e in entries:
                for ev in e.values:
                    if ev.value_number is not None:
                        totals[ev.metric_id] = totals.get(ev.metric_id, 0) + ev.value_number

            rows = [{'name': m.name, 'value': _fmt(totals.get(m.id)), 'raw': totals.get(m.id)}
                    for m in metrics]

            if any(r['raw'] is not None for r in rows):
                sections.append({
                    'category': cat.name,
                    'system_wide': not cat.has_branch,
                    'rows': rows,
                })

    if sections and request.args.get('format') == 'xlsx':
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        wb  = Workbook()
        ws  = wb.active
        ws.title = 'Branch Summary'
        ws.append([f'{branch.name} — {fy_label}'])
        ws.cell(1, 1).font = Font(bold=True, size=13)
        ws.append([])
        for sec in sections:
            label = sec['category'] + (' (System Wide)' if sec['system_wide'] else '')
            ws.append([label, ''])
            r = ws.max_row
            ws.cell(r, 1).font = Font(bold=True, color='FFFFFF')
            ws.cell(r, 1).fill = PatternFill('solid', fgColor='2C6E8A')
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=2)
            for row in sec['rows']:
                v = row['raw']
                ws.append([row['name'], int(v) if isinstance(v, float) and v == int(v) else v])
        ws.column_dimensions['A'].width = 42
        ws.column_dimensions['B'].width = 18
        safe_name = branch.name.replace(' ', '_').replace('/', '-')
        return _xlsx_response(wb, f'branch_summary_{safe_name}_{fy_year}.xlsx')

    return render_template('reports/branch_summary.html',
                           branches=branches, available_fy=available_fy,
                           sel_branch=branch_id, sel_fy=fy_year,
                           branch=branch, sections=sections, fy_label=fy_label)


@app.route('/admin/import', methods=['GET', 'POST'])
def admin_import():
    results = None
    if request.method == 'POST':
        f = request.files.get('file')
        if not f or not f.filename:
            flash('Please select a file to upload.', 'warning')
        else:
            import tempfile, openpyxl
            from import_excel import do_import
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
                    f.save(tmp.name)
                    tmp_path = tmp.name
                wb = openpyxl.load_workbook(tmp_path, data_only=True)
                results = do_import(wb)
                total_created = sum(r['created'] for r in results)
                flash(f'Import complete — {total_created} new entries added.', 'success')
            except Exception as e:
                flash(f'Import failed: {e}', 'danger')
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)
    return render_template('admin/import.html', results=results)


# ── Upload (smart auto-detect) ───────────────────────────────────────────────

_COMPARISON_METRICS = [
    'Total Branch Circulation',
    'Gate Count',
    'New Library Card Registrations, Total',
    'Total Prints per Month',
]

def _import_comparison(results):
    """
    After an import, compare written values to the same months one year prior.
    Returns a list of period dicts, each with rows flagged by size of change.
    """
    from sqlalchemy import or_, and_
    periods = set()
    for r in results:
        if r.get('year') and r.get('month'):
            periods.add((r['year'], r['month']))
        for p in r.get('periods', []):
            periods.add(tuple(p))
    if not periods:
        return []

    branch_cat = Category.query.filter_by(name='Branch Stats').first()
    if not branch_cat:
        return []

    metric_id_map = {m.name: m.id for m in branch_cat.metrics
                     if m.name in _COMPARISON_METRICS}
    if not metric_id_map:
        return []

    branches = _real_branch_q().order_by(Branch.name).all()

    all_periods = periods | {(y - 1, m) for y, m in periods}
    entries = (Entry.query
               .options(joinedload(Entry.values))
               .filter(
                   Entry.category_id == branch_cat.id,
                   or_(*[and_(Entry.year == y, Entry.month == m) for y, m in all_periods])
               ).all())

    lookup = {}
    for e in entries:
        for ev in e.values:
            if ev.value_number is not None:
                lookup[(e.year, e.month, e.branch_id, ev.metric_id)] = ev.value_number

    comparison = []
    for year, month in sorted(periods):
        rows = []
        for b in branches:
            for metric_name in _COMPARISON_METRICS:
                mid = metric_id_map.get(metric_name)
                if not mid:
                    continue
                curr  = lookup.get((year,     month, b.id, mid))
                prior = lookup.get((year - 1, month, b.id, mid))
                if curr is None and prior is None:
                    continue
                pct = flag = None
                if prior and curr is not None:
                    pct = ((curr - prior) / prior) * 100
                    if abs(pct) > 200:
                        flag = 'danger'
                    elif abs(pct) > 50:
                        flag = 'warning'
                elif prior and not curr:
                    flag = 'warning'
                rows.append({
                    'metric':  metric_name,
                    'branch':  b.name,
                    'current': curr,
                    'prior':   prior,
                    'pct':     pct,
                    'flag':    flag,
                })
        if rows:
            comparison.append({
                'label': f'{MONTHS[month - 1]} {year} vs {MONTHS[month - 1]} {year - 1}',
                'rows':  rows,
                'flagged': sum(1 for r in rows if r['flag']),
            })
    return comparison


def _import_snapshot():
    """Capture current DB state so we can diff after an import."""
    import json
    ev_snap    = {row[0]: row[1] for row in
                  db.session.execute(db.text('SELECT id, value_number FROM entry_values')).fetchall()}
    entry_snap = {row[0] for row in
                  db.session.execute(db.text('SELECT id FROM entries')).fetchall()}
    sirsi_rows = db.session.execute(db.text(
        'SELECT id, year, month, branch_id, patron_type, shelving_location, checkouts, renewals '
        'FROM sirsi_checkouts'
    )).fetchall()
    sirsi_snap = {r[0] for r in sirsi_rows}
    sirsi_full = {r[0]: dict(year=r[1], month=r[2], branch_id=r[3], patron_type=r[4],
                              shelving_location=r[5], checkouts=r[6], renewals=r[7])
                  for r in sirsi_rows}
    return ev_snap, entry_snap, sirsi_snap, sirsi_full


def _import_diff(ev_before, entries_before, sirsi_before, sirsi_full_before):
    """Compute what changed since the snapshot was taken."""
    ev_after = {row[0]: row[1] for row in
                db.session.execute(db.text('SELECT id, value_number FROM entry_values')).fetchall()}
    entries_after = {row[0] for row in
                     db.session.execute(db.text('SELECT id FROM entries')).fetchall()}
    sirsi_after = {row[0] for row in
                   db.session.execute(db.text('SELECT id FROM sirsi_checkouts')).fetchall()}

    ev_created  = [eid for eid in ev_after if eid not in ev_before]
    ev_updated  = [{'id': eid, 'old': ev_before[eid], 'new': ev_after[eid]}
                   for eid in ev_after
                   if eid in ev_before and ev_before[eid] != ev_after[eid]]
    entries_created  = list(entries_after - entries_before)
    sirsi_created    = list(sirsi_after - sirsi_before)
    sirsi_deleted    = [sirsi_full_before[sid] for sid in (sirsi_before - sirsi_after)]

    return {
        'entries_created': entries_created,
        'ev_created':      ev_created,
        'ev_updated':      ev_updated,
        'sirsi_created':   sirsi_created,
        'sirsi_deleted':   sirsi_deleted,
    }


@app.route('/upload', methods=['GET', 'POST'])
def upload_data():
    import json
    results = None
    comparison = None
    if request.method == 'POST':
        f = request.files.get('file')
        if not f or not f.filename:
            flash('Please select a file to upload.', 'warning')
        else:
            import tempfile, openpyxl
            from import_excel import detect_and_import
            tmp_path = None
            year_override = request.form.get('year', type=int) or None
            try:
                with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
                    f.save(tmp.name)
                    tmp_path = tmp.name
                wb = openpyxl.load_workbook(tmp_path, data_only=True)

                ev_before, entries_before, sirsi_before, sirsi_full = _import_snapshot()
                results = detect_and_import(wb, year_override=year_override, filename=f.filename)
                changes = _import_diff(ev_before, entries_before, sirsi_before, sirsi_full)

                # Derive period + type summary from results
                periods = {(r['year'], r['month']) for r in results if r.get('year') and r.get('month')}
                period_year  = next((r['year']  for r in results if r.get('year')),  None)
                period_month = next((r['month'] for r in results if r.get('month')), None)
                import_type  = '; '.join(r['sheet'] for r in results if r.get('created', 0) + r.get('updated', 0) > 0)
                rows_affected = sum(r.get('created', 0) + r.get('updated', 0) for r in results)

                log = ImportLog(
                    file_name=f.filename,
                    import_type=import_type or 'Unknown',
                    year=period_year,
                    month=period_month,
                    rows_affected=rows_affected,
                    changes_json=json.dumps(changes),
                )
                db.session.add(log)
                db.session.commit()

                total_created = sum(r['created'] for r in results)
                total_updated = sum(r.get('updated', 0) for r in results)
                if total_created or total_updated:
                    parts = []
                    if total_created:
                        parts.append(f'{total_created} new record(s) added')
                    if total_updated:
                        parts.append(f'{total_updated} existing record(s) updated')
                    flash('Upload complete — ' + ', '.join(parts) + '.', 'success')
                else:
                    flash('Upload complete, but no records were added or updated — '
                          'the file may already be fully loaded or its format was not '
                          'recognised. See the import results below.', 'warning')
                comparison = _import_comparison(results)
            except Exception as e:
                flash(f'Upload failed: {e}', 'danger')
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)

    recent_logs = ImportLog.query.order_by(ImportLog.created_at.desc()).limit(20).all()
    return render_template('upload.html', results=results, comparison=comparison,
                           now=datetime.utcnow(), recent_logs=recent_logs)


@app.route('/upload/undo/<int:log_id>', methods=['POST'])
def upload_undo(log_id):
    import json
    from models import SirsiCheckout
    if not current_user.is_admin:
        flash('Admin access required.', 'danger')
        return redirect(url_for('upload_data'))

    log = ImportLog.query.get_or_404(log_id)
    if log.undone_at:
        flash('This import has already been undone.', 'warning')
        return redirect(url_for('upload_data'))

    try:
        changes = json.loads(log.changes_json)

        # Restore updated entry_values to their previous values
        for ch in changes.get('ev_updated', []):
            ev = db.session.get(EntryValue, ch['id'])
            if ev:
                ev.value_number = ch['old']

        # Delete entry_values that were created by this import
        if changes.get('ev_created'):
            EntryValue.query.filter(EntryValue.id.in_(changes['ev_created'])).delete(synchronize_session=False)

        # Delete entries that were created by this import (now empty)
        for entry_id in changes.get('entries_created', []):
            entry = db.session.get(Entry, entry_id)
            if entry:
                db.session.delete(entry)

        # Delete SIRSI checkout rows created by this import
        if changes.get('sirsi_created'):
            SirsiCheckout.query.filter(SirsiCheckout.id.in_(changes['sirsi_created'])).delete(synchronize_session=False)

        # Restore SIRSI checkout rows that were deleted by this import
        for row in changes.get('sirsi_deleted', []):
            db.session.add(SirsiCheckout(
                year=row['year'], month=row['month'], branch_id=row['branch_id'],
                patron_type=row['patron_type'], shelving_location=row['shelving_location'],
                checkouts=row['checkouts'], renewals=row['renewals'],
            ))

        log.undone_at = datetime.utcnow()
        db.session.commit()
        flash(f'Import of "{log.file_name}" has been undone.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Undo failed: {e}', 'danger')

    return redirect(url_for('upload_data'))


# Metrics populated via file upload or dedicated forms — excluded from general entry forms
_UPLOAD_SOURCED_METRICS = {
    'New Library Card Registrations, Adult',
    'New Library Card Registrations, Juvenile',
    'New Library Card Registrations, Total',
    'Total Branch Circulation',
    'Hotspots Circulation',
    'Locker Circulation',
    'WiFi - Unique Sessions',
    'PC Reservations',
    'Total Prints per Month',
    'Printed Jobs',
    'Printed Cost',
    'ILL - Sent (Main ONLY)',
    'ILL - Received (Main ONLY)',
    'ICLs - Sent (Main ONLY)',
    'ICLs - Received (Main ONLY)',
}

_ILL_METRICS  = {'ILL - Sent (Main ONLY)', 'ILL - Received (Main ONLY)'}
_ICL_METRICS  = {'ICLs - Sent (Main ONLY)', 'ICLs - Received (Main ONLY)'}
_CIRC_METRICS = {'Total Branch Circulation', 'Hotspots Circulation', 'Locker Circulation'}


def _ill_icl_entry(metric_names_set, form_title, endpoint):
    """Shared handler for ILL and ICL manual entry forms (Rock Hill only)."""
    branch_cat = Category.query.filter_by(name='Branch Stats').first()
    rock_hill  = Branch.query.filter(Branch.name.ilike('%rock hill%'),
                                     Branch.is_active == True).first()
    metrics    = [m for m in (branch_cat.active_metrics if branch_cat else [])
                  if m.name in metric_names_set]
    year_range = range(datetime.now().year - 5, datetime.now().year + 2)

    year  = request.args.get('year',  type=int) or datetime.now().year
    month = request.args.get('month', type=int) or datetime.now().month

    if request.method == 'POST':
        year         = request.form.get('year',  type=int)
        month        = request.form.get('month', type=int)
        submitted_by = current_user.username

        vals = {}
        for m in metrics:
            raw = request.form.get(f'm{m.id}', '').strip()
            if raw:
                try:
                    vals[m.id] = float(raw)
                except ValueError:
                    pass

        if vals and rock_hill:
            entry = Entry.query.filter_by(category_id=branch_cat.id,
                                          branch_id=rock_hill.id,
                                          year=year, month=month).first()
            if not entry:
                entry = Entry(category_id=branch_cat.id, branch_id=rock_hill.id,
                              year=year, month=month, submitted_by=submitted_by)
                db.session.add(entry)
                db.session.flush()

            for metric_id, val in vals.items():
                ev = EntryValue.query.filter_by(entry_id=entry.id,
                                                metric_id=metric_id).first()
                if ev:
                    ev.value_number = val
                else:
                    db.session.add(EntryValue(entry_id=entry.id,
                                              metric_id=metric_id,
                                              value_number=val))

            db.session.commit()
            flash(f'Data saved for {MONTHS[month - 1]} {year}.', 'success')
        return redirect(url_for(endpoint, year=year, month=month))

    # Load existing values
    rh_entry = (Entry.query.filter_by(category_id=branch_cat.id,
                                      branch_id=rock_hill.id,
                                      year=year, month=month).first()
                if rock_hill else None)
    values = {ev.metric_id: ev for ev in rh_entry.values} if rh_entry else {}

    return render_template('entries/main_only_entry.html',
                           form_title=form_title,
                           branch=rock_hill,
                           redirect_endpoint=endpoint,
                           metrics=metrics,
                           values=values,
                           year=year, month=month,
                           months=MONTHS,
                           year_range=year_range)


@app.route('/enter/ill', methods=['GET', 'POST'])
def ill_entry():
    return _ill_icl_entry(_ILL_METRICS, 'ILL Entry (Main only)', 'ill_entry')


@app.route('/enter/icl', methods=['GET', 'POST'])
def icl_entry():
    return _ill_icl_entry(_ICL_METRICS, 'ICL Entry (Main only)', 'icl_entry')



@app.route('/admin/export')
def admin_export():
    import io
    from export_excel import generate_export
    buf = generate_export()
    filename = f'library_stats_{datetime.now().strftime("%Y%m%d")}.xlsx'
    return send_file(
        buf,
        download_name=filename,
        as_attachment=True,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


@app.route('/reports/monthlystats')
def report_monthly_stats():
    month = request.args.get('month', type=int)
    year  = request.args.get('year',  type=int)

    available_years = sorted(
        {r[0] for r in db.session.query(Entry.year).distinct().all()},
        reverse=True
    )

    sections = prev_year = None

    if month and year:
        prev_year = year - 1

        def get_sums(cat_name, y, m):
            cat = Category.query.filter_by(name=cat_name).first()
            if not cat:
                return {}
            q = Entry.query.options(joinedload(Entry.values)).filter_by(category_id=cat.id, year=y, month=m)
            if cat.has_branch:
                excluded_ids = [b.id for b in Branch.query.filter(
                    db.or_(
                        Branch.name.ilike('%locker%'),
                        Branch.name == 'YCL (System Wide)',
                        Branch.name == 'Administration',
                        Branch.is_desk == True,
                    )
                ).with_entities(Branch.id).all()]
                if excluded_ids:
                    q = q.filter(~Entry.branch_id.in_(excluded_ids))
            entries = q.all()
            id_to_name = {mx.id: mx.name for mx in cat.metrics}
            totals = {}
            for e in entries:
                for ev in e.values:
                    n = id_to_name.get(ev.metric_id)
                    if n and ev.value_number is not None:
                        totals[n] = totals.get(n, 0) + ev.value_number
            return totals

        bs_c = get_sums('Branch Stats', year,      month)
        bs_p = get_sums('Branch Stats', prev_year, month)
        os_c = get_sums('Online Stats', year,      month)
        os_p = get_sums('Online Stats', prev_year, month)

        AGE  = AGE_GROUPS

        def prog(sums, ptype, kind, age):
            return sums.get(f'{ptype} {kind} {age}') or None

        def pair(curr, prev, label):
            return {'label': label, 'curr': curr, 'prev': prev}

        sections = [
            {
                'title': 'Circulation & Door Count',
                'color': '#1a5276',
                'items': [
                    pair(bs_c.get('Total Branch Circulation'), bs_p.get('Total Branch Circulation'), 'Monthly Circulation'),
                    pair(bs_c.get('Gate Count'),               bs_p.get('Gate Count'),               'Monthly Gate Count'),
                ],
            },
            {
                'title': 'New Library Cards',
                'color': '#1e8449',
                'items': [
                    pair(bs_c.get('New Library Card Registrations, Adult'), bs_p.get('New Library Card Registrations, Adult'), 'New Cards, Adult (incl. YA)'),
                    pair(bs_c.get('New Library Card Registrations, Juvenile'), bs_p.get('New Library Card Registrations, Juvenile'), 'New Cards, Juvenile'),
                ],
            },
            {
                'title': 'ONSITE Program Sessions',
                'color': '#6c3483',
                'items': [pair(prog(bs_c,'ONSITE','Sessions',a), prog(bs_p,'ONSITE','Sessions',a), f'Sessions {a}') for a in AGE],
            },
            {
                'title': 'ONSITE Program Attendance',
                'color': '#784212',
                'items': [pair(prog(bs_c,'ONSITE','Attendance',a), prog(bs_p,'ONSITE','Attendance',a), f'Attendance {a}') for a in AGE],
            },
            {
                'title': 'Online Usage',
                'color': '#117a65',
                'items': [
                    pair(os_c.get('yclibrary.org - Web Sessions'), os_p.get('yclibrary.org - Web Sessions'), 'Website Hits'),
                    pair(os_c.get('Website Messages'),             os_p.get('Website Messages'),             'Contact Us'),
                    pair(os_c.get('YCL App - Users'),              os_p.get('YCL App - Users'),              'YCL App Users'),
                    pair(os_c.get('YCL App - Sessions'),           os_p.get('YCL App - Sessions'),           'YCL App Sessions'),
                ],
            },
            {
                'title': 'Social Media',
                'color': '#1a5276',
                'items': [
                    pair(os_c.get('Instagram - Subscribers'), os_p.get('Instagram - Subscribers'), 'Instagram Subscriptions'),
                    pair(os_c.get('Facebook Followers'),       os_p.get('Facebook Followers'),       'Facebook Followers'),
                    pair(os_c.get('YouTube - Views'),          os_p.get('YouTube - Views'),          'YouTube Views'),
                    pair(os_c.get('YouTube - Subscribers'),    os_p.get('YouTube - Subscribers'),    'YouTube Subscribers'),
                ],
            },
            {
                'title': 'Technology Use',
                'color': '#922b21',
                'items': [
                    pair(bs_c.get('PC Reservations'),       bs_p.get('PC Reservations'),       'Monthly PC Reservations'),
                    pair(bs_c.get('WiFi - Unique Sessions'), bs_p.get('WiFi - Unique Sessions'), 'WiFi – Unique Sessions'),
                    pair(bs_c.get('Hotspots Circulation'),  bs_p.get('Hotspots Circulation'),  'Hotspots – Circulation'),
                    pair(bs_c.get('Total Prints per Month'), bs_p.get('Total Prints per Month'), 'Monthly Total Prints'),
                ],
            },
        ]

        # Drop sections where every item has no data in either year
        sections = [s for s in sections
                    if any(it['curr'] is not None or it['prev'] is not None
                           for it in s['items'])]

    return render_template('reports/monthly_stats.html',
                           months=MONTHS, available_years=available_years,
                           sel_month=month, sel_year=year, prev_year=prev_year,
                           sections=sections)


@app.route('/director')
def director_dashboard():
    from sqlalchemy import or_, and_

    rows = db.session.query(Entry.year, Entry.month, Entry.quarter).filter(
        or_(Entry.month.isnot(None), Entry.quarter.isnot(None))
    ).distinct().all()
    _now = datetime.now(); _cur_fy = _now.year + 1 if _now.month >= 7 else _now.year
    fy_set = set()
    for yr, mo, q in rows:
        if mo is not None:
            fy_set.add(yr + 1 if mo >= 7 else yr)
        if q is not None:
            fy_set.add(yr + 1 if q in (3, 4) else yr)
    available_fy = sorted((y for y in fy_set if y <= _cur_fy), reverse=True)

    fy_year = request.args.get('fy_year', type=int)
    stats = None

    if fy_year:
        def fy_filter(cat_name):
            cat = Category.query.filter_by(name=cat_name).first()
            if not cat:
                return {}
            entries = Entry.query.options(joinedload(Entry.values)).filter_by(category_id=cat.id).filter(
                or_(
                    and_(Entry.year == fy_year - 1,
                         or_(Entry.month >= 7, Entry.quarter.in_([3, 4]))),
                    and_(Entry.year == fy_year,
                         or_(Entry.month <= 6, Entry.quarter.in_([1, 2])))
                )
            ).all()
            id_to_name = {m.id: m.name for m in cat.metrics}
            totals = {}
            for e in entries:
                for ev in e.values:
                    n = id_to_name.get(ev.metric_id)
                    if n and ev.value_number is not None:
                        totals[n] = totals.get(n, 0) + ev.value_number
            return totals

        bs = fy_filter('Branch Stats')
        os = fy_filter('Online Stats')
        qs = fy_filter('Quarterly Reference Stats')

        AGE   = AGE_GROUPS
        TYPES = PROG_TYPES

        def v(d, key):
            val = d.get(key)
            return int(val) if val is not None and val == int(val) else (round(val, 1) if val else None)

        def prog_sum(kind, age_group):
            return v(bs, f'ONSITE {kind} {age_group}') or 0 + \
                   (v(bs, f'OFFSITE {kind} {age_group}') or 0) + \
                   (v(bs, f'VIRTUAL {kind} {age_group}') or 0)

        # Outreach branch vs bookmobile split
        ob_branch = Branch.query.filter_by(name='Outreach/Bookmobile').first()
        ob_id = ob_branch.id if ob_branch else None

        def fy_filter_by_branch(cat_name, branch_id):
            cat = Category.query.filter_by(name=cat_name).first()
            if not cat:
                return {}
            q = Entry.query.filter_by(category_id=cat.id, branch_id=branch_id).filter(
                or_(
                    and_(Entry.year == fy_year - 1, Entry.month >= 7),
                    and_(Entry.year == fy_year,     Entry.month <= 6)
                )
            ).all()
            id_to_name = {m.id: m.name for m in cat.metrics}
            totals = {}
            for e in q:
                for ev in e.values:
                    n = id_to_name.get(ev.metric_id)
                    if n and ev.value_number is not None:
                        totals[n] = totals.get(n, 0) + ev.value_number
            return totals

        bs_bkm    = fy_filter_by_branch('Branch Stats', ob_id) if ob_id else {}
        outreach_branches = int(bs.get('Number of Outreach Activities Conducted', 0) -
                                bs_bkm.get('Number of Outreach Activities Conducted', 0))

        def session_row(type_, age):
            return v(bs, f'{type_} Sessions {age}')
        def attend_row(type_, age):
            return v(bs, f'{type_} Attendance {age}')

        stats = {
            'users': [
                ('G1',  'Registered Users, Adult',            v(bs, 'New Library Card Registrations, Adult')),
                ('G2',  'Registered Users, Juvenile',         v(bs, 'New Library Card Registrations, Juvenile')),
                ('G4',  'Gate Count',                         v(bs, 'Gate Count')),
                ('G6',  'Public Internet Computer Use',       v(bs, 'PC Reservations')),
                ('G9',  'WiFi Sessions',                      v(bs, 'WiFi - Unique Sessions')),
                ('G11', 'Website Visits',                     v(os, 'yclibrary.org - Web Sessions')),
                ('G12', 'External Party Meeting Room Use',    v(bs, 'External Party Library Room Use')),
            ],
            'circulation': [
                ('',    'Total Branch Circulation',           v(bs, 'Total Branch Circulation')),
                ('H1',  'Annual Reference Transactions',      v(qs, 'Total Transactions for the Week')),
                ('H3',  '1-on-1 Sessions',                    v(bs, '1-on-1 Total for Month')),
                ('H4',  "Children's Print Circ",              None),
                ('H5',  "Children's Non-Print Circ",          None),
                ('H7',  'Adult Print Circ',                   None),
                ('H8',  'Adult Non-Print Circ',               None),
                ('H10', 'Circ of Other Physical Materials',   None),
                ('H14', 'eBook Circ',                         None),
                ('H15', 'eAudio Circ',                        None),
                ('H16', 'eVideo Circ',                        None),
                ('H17', 'eSerial Circ',                       None),
                ('H20', 'ILLs Sent',                          v(bs, 'ILL - Sent (Main ONLY)')),
                ('H21', 'ILLs Received',                      v(bs, 'ILL - Received (Main ONLY)')),
                ('',    'Locker Circulation',                  v(bs, 'Locker Circulation')),
                ('',    'Curbside',                            v(bs, 'Curbside')),
                ('',    'Hotspots Circulation',                v(bs, 'Hotspots Circulation')),
            ],
            'sessions': {t: [(a, session_row(t, a)) for a in AGE] for t in TYPES},
            'attendance': {t: [(a, attend_row(t, a)) for a in AGE] for t in TYPES},
            'async_': [
                ('Asynchronous Presentations – YouTube',      v(os, 'YouTube Uploads')),
                ('Asynchronous Presentations – Dial-A-Story', v(os, 'Dial A Story Uploads')),
                ('Asynchronous Views – YouTube',              v(os, 'YouTube - Views')),
                ('Asynchronous Views – Dial-A-Story',         v(os, 'Dial A Story - Views')),
            ],
            'outreach': [
                ('Outreach Activities – Branches',            outreach_branches if outreach_branches else None),
                ('Outreach Activities – Bookmobile',          v(bs_bkm, 'Number of Outreach Activities Conducted')),
                ('Outreach Attendance',                       v(bs, 'Outreach Attendance')),
                ('Passive Programming Participants',          v(bs, 'Take & Makes / Other Passive Program Participants')),
                ('Training – # of Staff Trained',             v(bs, 'Number of Staff Taking Training')),
                ('Training – # of Hours',                     v(bs, 'Number of Hours Staff Attended Training')),
            ],
            'online': [
                ('Website Hits',         v(os, 'yclibrary.org - Web Sessions')),
                ('Contact Us',           v(os, 'Website Messages')),
                ('YCL App Users',        v(os, 'YCL App - Users')),
                ('YCL App Sessions',     v(os, 'YCL App - Sessions')),
                ('Facebook Followers',   v(os, 'Facebook Followers')),
                ('Instagram Subscribers',v(os, 'Instagram - Subscribers')),
                ('YouTube Subscribers',  v(os, 'YouTube - Subscribers')),
                ('YouTube Views',        v(os, 'YouTube - Views')),
            ],
            'totals': {
                'circulation': v(bs, 'Total Branch Circulation'),
                'gate':        v(bs, 'Gate Count'),
                'programs':    sum(
                    (v(bs, f'{t} Sessions {a}') or 0)
                    for t in TYPES for a in AGE
                ) or None,
                'website':     v(os, 'yclibrary.org - Web Sessions'),
                'cards':       (v(bs, 'New Library Card Registrations, Adult') or 0) +
                               (v(bs, 'New Library Card Registrations, Juvenile') or 0) or None,
                'attendance':  sum(
                    (v(bs, f'{t} Attendance {a}') or 0)
                    for t in TYPES for a in AGE
                ) or None,
            },
        }

    if stats and request.args.get('format') == 'xlsx':
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
        wb = Workbook()
        ws = wb.active
        ws.title = 'Director Dashboard'
        bold = Font(bold=True)
        hdr_fill = PatternFill('solid', fgColor='1A5276')
        hdr_font = Font(bold=True, color='FFFFFF')
        fy_lbl = f'FY{fy_year} (Jul {fy_year-1} – Jun {fy_year})'
        ws.column_dimensions['A'].width = 12
        ws.column_dimensions['B'].width = 48
        ws.column_dimensions['C'].width = 16

        ws.append(['York County Library', '', fy_lbl])
        ws.cell(1, 1).font = Font(bold=True, size=14)
        ws.cell(1, 3).font = Font(italic=True)
        ws.append([])

        def section(title, rows, has_code=True):
            ws.append([title])
            r = ws.max_row
            ws.cell(r, 1).font = Font(bold=True, color='FFFFFF')
            ws.cell(r, 1).fill = PatternFill('solid', fgColor='2C3E50')
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=3)
            if has_code:
                ws.append(['Code', 'Metric', 'FY Total'])
            else:
                ws.append(['Metric', 'FY Total'])
            hr = ws.max_row
            for col in range(1, 4 if has_code else 3):
                ws.cell(hr, col).font = bold
                ws.cell(hr, col).fill = PatternFill('solid', fgColor='D9E1F2')
            for row in rows:
                if has_code:
                    code, label, val = row
                    ws.append([code, label, val if val is not None else ''])
                else:
                    label, val = row
                    ws.append([label, val if val is not None else ''])
            ws.append([])

        section('Library Users, Visits & Internet Usage', stats['users'])
        section('Reference & Circulation', stats['circulation'])

        ws.append(['Programming'])
        r = ws.max_row
        ws.cell(r, 1).font = Font(bold=True, color='FFFFFF')
        ws.cell(r, 1).fill = PatternFill('solid', fgColor='2C3E50')
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=7)
        hdrs = ['Age Group'] + [f'{t} Sessions' for t in TYPES] + [f'{t} Attendance' for t in TYPES]
        ws.append(hdrs)
        hr = ws.max_row
        for col in range(1, len(hdrs) + 1):
            ws.cell(hr, col).font = bold
            ws.cell(hr, col).fill = PatternFill('solid', fgColor='D9E1F2')
        for age in AGE:
            row_data = [age]
            for t in TYPES:
                sv = next((val for a, val in stats['sessions'][t] if a == age), None)
                row_data.append(sv if sv is not None else '')
            for t in TYPES:
                av = next((val for a, val in stats['attendance'][t] if a == age), None)
                row_data.append(av if av is not None else '')
            ws.append(row_data)
        ws.append([])

        for col_idx in range(2, 8):
            ws.column_dimensions[ws.cell(1, col_idx).column_letter].width = 16

        section('Outreach & Other', stats['outreach'], has_code=False)
        section('Asynchronous Programs', stats['async_'], has_code=False)
        section('Online & Social Media', stats['online'], has_code=False)

        return _xlsx_response(wb, f'director_dashboard_{fy_year}.xlsx')

    return render_template('director.html',
                           available_fy=available_fy, sel_fy=fy_year,
                           fy_label=f'FY{fy_year} (Jul {fy_year-1} – Jun {fy_year})' if fy_year else None,
                           stats=stats, TYPES=PROG_TYPES,
                           AGE=AGE_GROUPS)


@app.route('/reports/quarterly_ref')
def report_quarterly_ref():
    fy_year = request.args.get('year', type=int)

    # Derive available FY years from stored entries.
    # Q1+Q2 belong to FY = calendar_year + 1; Q3+Q4 belong to FY = calendar_year.
    cat_check = Category.query.filter_by(name='Quarterly Reference Stats').first()
    if cat_check:
        rows = db.session.query(Entry.year, Entry.quarter).filter_by(
            category_id=cat_check.id
        ).distinct().all()
        fy_set = set()
        for yr, q in rows:
            if q in (1, 2):
                fy_set.add(yr + 1)
            elif q in (3, 4):
                fy_set.add(yr)
        available_years = sorted(fy_set, reverse=True)
    else:
        available_years = []

    table = quarterly_totals = None
    open_days = open_weeks = annual_estimate = None
    closure_saved = False
    holidays = unexpected = 0

    if fy_year:
        # Load saved closure days keyed by FY year
        saved = QuarterlyRefClosureDays.query.filter_by(year=fy_year).first()
        if saved:
            holidays = saved.holidays
            unexpected = saved.unexpected
            closure_saved = True

        cat = cat_check
        if cat:
            metric = next((m for m in cat.metrics if m.name == 'Total Transactions for the Week'), None)
            all_branches = _branches_for_category(cat)

            # Fetch entries spanning two calendar years:
            # Q1+Q2 from year fy_year-1, Q3+Q4 from year fy_year
            raw = {b.id: {} for b in all_branches}
            fy_entries = Entry.query.options(joinedload(Entry.values)).filter(
                Entry.category_id == cat.id,
                or_(
                    and_(Entry.year == fy_year - 1, Entry.quarter.in_([1, 2])),
                    and_(Entry.year == fy_year,     Entry.quarter.in_([3, 4]))
                )
            ).all()
            for e in fy_entries:
                if e.branch_id in raw and e.quarter and metric:
                    for ev in e.values:
                        if ev.metric_id == metric.id and ev.value_number is not None:
                            raw[e.branch_id][e.quarter] = int(ev.value_number)

            closed_days = holidays + unexpected
            open_days   = 52 * 6 - closed_days
            open_weeks  = round(open_days / 6, 2)

            def _row(label, branch_ids, is_combined=False):
                q_vals = {}
                for q in range(1, 5):
                    parts = [raw[bid][q] for bid in branch_ids if raw[bid].get(q) is not None]
                    if parts:
                        q_vals[q] = sum(parts)
                avg = round(sum(q_vals.values()) / len(q_vals), 1) if q_vals else None
                est = round(avg * open_weeks) if (avg and closure_saved) else None
                return {
                    'label':       label,
                    'quarters':    [q_vals.get(q) for q in range(1, 5)],
                    'avg':         avg,
                    'estimate':    est,
                    'is_combined': is_combined,
                }

            desk_branches    = [b for b in all_branches if b.is_desk]
            regular_branches = [b for b in all_branches if not b.is_desk]

            table = []
            if desk_branches:
                table.append(_row('Rock Hill (all desks)',
                                  [b.id for b in desk_branches],
                                  is_combined=True))
            for b in regular_branches:
                table.append(_row(b.name, [b.id]))

            # System quarterly totals (across all individual branches)
            quarterly_totals = {}
            for q in range(1, 5):
                parts = [raw[b.id][q] for b in all_branches if raw[b.id].get(q) is not None]
                if parts:
                    quarterly_totals[q] = sum(parts)

            # Annual estimate only when closure days have been saved
            if closure_saved:
                annual_estimate = sum(r['estimate'] for r in table if r['estimate']) or None

    return render_template('reports/quarterly_ref.html',
                           available_years=available_years,
                           sel_year=fy_year,
                           holidays=holidays,
                           unexpected=unexpected,
                           closure_saved=closure_saved,
                           table=table,
                           quarterly_totals=quarterly_totals,
                           open_days=open_days,
                           open_weeks=open_weeks,
                           annual_estimate=annual_estimate)


@app.route('/reports/quarterly_ref/save_closure', methods=['POST'])
def quarterly_ref_save_closure():
    year       = request.form.get('year',       type=int)
    holidays   = request.form.get('holidays',   type=int, default=0) or 0
    unexpected = request.form.get('unexpected', type=int, default=0) or 0
    if not year:
        flash('Year is required.', 'danger')
        return redirect(url_for('report_quarterly_ref'))
    saved = QuarterlyRefClosureDays.query.filter_by(year=year).first()
    if saved:
        saved.holidays   = holidays
        saved.unexpected = unexpected
        saved.saved_by   = current_user.username
        saved.saved_at   = datetime.utcnow()
    else:
        db.session.add(QuarterlyRefClosureDays(
            year=year, holidays=holidays, unexpected=unexpected,
            saved_by=current_user.username
        ))
    db.session.commit()
    flash(f'Closure days saved for {year}.', 'success')
    return redirect(url_for('report_quarterly_ref', year=year))


@app.route('/reports/quarterly_ref/clear_closure', methods=['POST'])
def quarterly_ref_clear_closure():
    year = request.form.get('year', type=int)
    if not year:
        flash('Year is required.', 'danger')
        return redirect(url_for('report_quarterly_ref'))
    saved = QuarterlyRefClosureDays.query.filter_by(year=year).first()
    if saved:
        db.session.delete(saved)
        db.session.commit()
        flash(f'Closure days cleared for {year}.', 'info')
    return redirect(url_for('report_quarterly_ref', year=year))


# ── User Management ──────────────────────────────────────────────────────────

@app.route('/admin/users')
@admin_required
def admin_users():
    users = User.query.order_by(User.username).all()
    return render_template('admin/users.html', users=users)


@app.route('/admin/users/new', methods=['GET', 'POST'])
@admin_required
def admin_user_new():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email    = request.form.get('email', '').strip() or None
        password = request.form.get('password', '')
        is_admin = bool(request.form.get('is_admin'))

        if not username or not password:
            flash('Username and password are required.', 'danger')
            return render_template('admin/user_form.html', editing=False)

        if User.query.filter_by(username=username).first():
            flash(f'Username "{username}" is already taken.', 'danger')
            return render_template('admin/user_form.html', editing=False)

        user = User(username=username, email=email, is_admin=is_admin, is_active=True)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash(f'User "{username}" created.', 'success')
        return redirect(url_for('admin_users'))

    return render_template('admin/user_form.html', editing=False)


@app.route('/admin/users/<int:user_id>/edit', methods=['GET', 'POST'])
@admin_required
def admin_user_edit(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('admin_users'))

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'reset_password':
            new_pw = request.form.get('new_password', '')
            if not new_pw:
                flash('New password cannot be blank.', 'danger')
            else:
                user.set_password(new_pw)
                db.session.commit()
                flash(f'Password for "{user.username}" updated.', 'success')
            return redirect(url_for('admin_user_edit', user_id=user_id))

        username  = request.form.get('username', '').strip()
        email     = request.form.get('email', '').strip() or None
        is_admin  = bool(request.form.get('is_admin'))
        is_active = bool(request.form.get('is_active'))

        if not username:
            flash('Username cannot be blank.', 'danger')
            return render_template('admin/user_form.html', editing=True, user=user)

        existing = User.query.filter_by(username=username).first()
        if existing and existing.id != user_id:
            flash(f'Username "{username}" is already taken.', 'danger')
            return render_template('admin/user_form.html', editing=True, user=user)

        # Prevent locking yourself out
        if user.id == current_user.id:
            is_admin  = True
            is_active = True

        user.username  = username
        user.email     = email
        user.is_admin  = is_admin
        user.is_active = is_active
        db.session.commit()
        flash(f'User "{username}" updated.', 'success')
        return redirect(url_for('admin_users'))

    return render_template('admin/user_form.html', editing=True, user=user)


@app.route('/admin/users/<int:user_id>/toggle', methods=['POST'])
@admin_required
def admin_user_toggle(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('admin_users'))
    if user.id == current_user.id:
        flash('You cannot deactivate your own account.', 'warning')
        return redirect(url_for('admin_users'))
    user.is_active = not user.is_active
    db.session.commit()
    flash(f'User "{user.username}" {"activated" if user.is_active else "deactivated"}.', 'success')
    return redirect(url_for('admin_users'))


# ── Annual Survey Dashboard ───────────────────────────────────────────────────

from models import AnnualSurveyMetric, AnnualSurveyValue

_ANNUAL_CHART_METRICS = [
    'Annual Library Visits (gate count)',
    'TOTAL COLLECTION USE',
    'GRAND TOTAL ALL CIRC',
    'Total of all programs',
    'Total Attendance all programs and all ages',
    'Total operating revenue',
    'Expenditures: Total operating',
    'Grand total library staff FTE',
]

_ANNUAL_KPI_METRICS = [
    ('Annual Library Visits (gate count)',       'Gate Count'),
    ('TOTAL COLLECTION USE',                  'Collection Use'),
    ('GRAND TOTAL ALL CIRC',                     'Total Circ'),
    ('Total of all programs',                    'Programs'),
    ('Total Attendance all programs and all ages','Attendance'),
    ('Total operating revenue',                  'Revenue'),
    ('Expenditures: Total operating',            'Expenses'),
    ('Grand total library staff FTE',            'Staff FTE'),
]


def _annual_get_value(year_map, metric_name):
    sv = year_map.get(metric_name)
    return int(sv.value) if sv and sv.value is not None else None


@app.route('/annual-survey')
def annual_survey_dashboard():
    all_metrics  = AnnualSurveyMetric.query.order_by(AnnualSurveyMetric.sort_order).all()
    all_values   = AnnualSurveyValue.query.all()
    metric_by_id = {m.id: m for m in all_metrics}

    # Build: {year: {metric_name: AnnualSurveyValue}}
    by_year = {}
    for v in all_values:
        m = metric_by_id.get(v.metric_id)
        if not m:
            continue
        by_year.setdefault(v.report_year, {})[m.name] = v

    years = sorted(by_year.keys())
    latest_year = years[-1] if years else None

    # KPI cards for all years (used by JS year picker)
    kpis_by_year = {}
    for y in years:
        ym = by_year[y]
        prev_ym = by_year.get(y - 1, {})
        kpis_by_year[y] = [
            {'label': label, 'value': _annual_get_value(ym, metric_name),
             'prev': _annual_get_value(prev_ym, metric_name)}
            for metric_name, label in _ANNUAL_KPI_METRICS
        ]

    # Chart data — all years for every numeric metric (for interactive chart builder)
    chart_data = {}
    for m in all_metrics:
        if m.data_type in ('integer', 'decimal'):
            chart_data[m.name] = {
                'labels': years,
                'values': [_annual_get_value(by_year.get(y, {}), m.name) for y in years],
            }

    # Section summary table — group metrics by section, one col per year
    sections = {}
    for m in all_metrics:
        sections.setdefault(m.section, []).append(m)

    section_order = [
        'USERS GATE COUNT', 'CIRC', 'PROGRAMMING', 'OUTREACH',
        'TECH USE', 'REF MTG RM', 'ILL',
        'OPERATIONS', 'STAFFING', 'REVENUE',
        'EXPENSES STAFF', 'EXPENSES COLLECTION', 'EXPENSES OPERATIONS',
        'EXPENSES CAPITAL', 'EXPENSES TOTAL', 'COLLECTION SIZE',
    ]
    section_labels = {
        'USERS GATE COUNT':      'Users & Gate Count',
        'CIRC':                  'Circulation',
        'PROGRAMMING':           'Programming',
        'OUTREACH':              'Outreach',
        'TECH USE':              'Technology Use',
        'REF MTG RM':            'Reference & Meeting Rooms',
        'ILL':                   'Interlibrary Loans',
        'OPERATIONS':            'Operations',
        'STAFFING':              'Staffing',
        'REVENUE':               'Revenue',
        'EXPENSES STAFF':        'Expenses: Staff',
        'EXPENSES COLLECTION':   'Expenses: Collection',
        'EXPENSES OPERATIONS':   'Expenses: Operations',
        'EXPENSES CAPITAL':      'Expenses: Capital',
        'EXPENSES TOTAL':        'Expenses: Total',
        'COLLECTION SIZE':       'Collection Size',
    }

    return render_template('annual/dashboard.html',
                           years=years,
                           latest_year=latest_year,
                           kpis_by_year=kpis_by_year,
                           chart_data=chart_data,
                           sections=sections,
                           section_order=section_order,
                           section_labels=section_labels,
                           by_year=by_year,
                           all_metrics=all_metrics)


@app.route('/annual-survey/<int:year>/enter', methods=['GET', 'POST'])
def annual_survey_enter(year):
    all_metrics = AnnualSurveyMetric.query.order_by(AnnualSurveyMetric.sort_order).all()
    existing    = {v.metric_id: v for v in AnnualSurveyValue.query.filter_by(report_year=year).all()}

    section_order = [
        'USERS GATE COUNT', 'CIRC', 'PROGRAMMING', 'OUTREACH',
        'TECH USE', 'REF MTG RM', 'ILL',
        'OPERATIONS', 'STAFFING', 'REVENUE',
        'EXPENSES STAFF', 'EXPENSES COLLECTION', 'EXPENSES OPERATIONS',
        'EXPENSES CAPITAL', 'EXPENSES TOTAL', 'COLLECTION SIZE',
    ]
    sections = {}
    for m in all_metrics:
        sections.setdefault(m.section, []).append(m)

    if request.method == 'POST':
        saved = 0
        for m in all_metrics:
            if m.is_auto_calculated:
                continue
            raw = request.form.get(f'm{m.id}', '').strip()
            sv  = existing.get(m.id)
            if m.data_type == 'text':
                val_num, val_text = None, raw or None
            else:
                try:
                    val_num, val_text = float(raw), None
                except ValueError:
                    val_num, val_text = None, None

            if sv:
                sv.value      = val_num
                sv.value_text = val_text
            else:
                if val_num is not None or val_text is not None:
                    db.session.add(AnnualSurveyValue(
                        report_year=year, metric_id=m.id,
                        value=val_num, value_text=val_text
                    ))
            saved += 1

        db.session.commit()
        flash(f'Annual survey data saved for Report Year {year}.', 'success')
        return redirect(url_for('annual_survey_enter', year=year))

    available_years = sorted({v.report_year for v in AnnualSurveyValue.query.all()}, reverse=True)
    all_years = sorted(set(list(available_years) + [year]), reverse=True)

    return render_template('annual/entry.html',
                           year=year,
                           all_years=all_years,
                           sections=sections,
                           section_order=section_order,
                           existing=existing)


def _calculate_annual_metrics(year):
    """Calculate auto-metrics for one FY year from monthly Branch/Online Stats.

    Returns the number of metrics saved (inserted or updated).
    Does NOT commit — caller must call db.session.commit().
    """
    from sqlalchemy import or_, and_

    bs_cat     = Category.query.filter_by(name='Branch Stats').first()
    online_cat = Category.query.filter_by(name='Online Stats').first()
    metrics_map = {m.name: m for m in AnnualSurveyMetric.query.all()}

    def fy_entries(cat):
        if not cat:
            return []
        return Entry.query.options(joinedload(Entry.values)).filter_by(category_id=cat.id).filter(
            or_(
                and_(Entry.year == year - 1, Entry.month >= 7),
                and_(Entry.year == year,     Entry.month <= 6)
            )
        ).all()

    def sum_metric(entries, metric_name):
        m = Metric.query.filter_by(name=metric_name).first()
        if not m:
            return None
        total = 0
        found = False
        for e in entries:
            for ev in e.values:
                if ev.metric_id == m.id and ev.value_number is not None:
                    total += ev.value_number
                    found = True
        return round(total) if found else None

    bs_entries     = fy_entries(bs_cat)
    online_entries = fy_entries(online_cat)
    locker_ids = {b.id for b in Branch.query.filter(Branch.name.ilike('%locker%')).all()}
    bs_entries_no_locker = [e for e in bs_entries if e.branch_id not in locker_ids]

    calculated = {}
    note = f'Auto-calculated from monthly data for FY{year} (Jul {year-1} – Jun {year})'

    def _save(metric_name, value):
        if value is None:
            return
        am = metrics_map.get(metric_name)
        if not am:
            return
        sv = AnnualSurveyValue.query.filter_by(report_year=year, metric_id=am.id).first()
        if sv:
            sv.value = value
            sv.is_adjusted = False
            sv.adjustment_note = note
        else:
            db.session.add(AnnualSurveyValue(
                report_year=year, metric_id=am.id,
                value=value, adjustment_note=note
            ))
        calculated[metric_name] = value

    _save('Annual Library Visits (gate count)',
          sum_metric(bs_entries_no_locker, 'Gate Count'))
    _save('Number of wireless sessions',
          sum_metric(bs_entries_no_locker, 'WiFi - Unique Sessions'))
    _save('Number of website visits',
          sum_metric(online_entries, 'yclibrary.org - Web Sessions'))
    _save('TOTAL COLLECTION USE',
          sum_metric(bs_entries_no_locker, 'Total Branch Circulation'))

    for age, label in [('0-5',              'Synchronous Pgm Sessions Kids 0-5'),
                        ('6-11',             'Synchronous Pgm Sessions Kids 6-11'),
                        ('12-18',            'Total YA Programs for ages 12-18'),
                        ('19+',              'Total Adult Programs for 18+'),
                        ('General Interest', 'Total Gen Audience')]:
        total = 0
        found = False
        for t in PROG_TYPES:
            v = sum_metric(bs_entries_no_locker, f'{t} Sessions {age}')
            if v is not None:
                total += v
                found = True
        _save(label, round(total) if found else None)

    kids05  = calculated.get('Synchronous Pgm Sessions Kids 0-5', 0) or 0
    kids611 = calculated.get('Synchronous Pgm Sessions Kids 6-11', 0) or 0
    ya      = calculated.get('Total YA Programs for ages 12-18', 0) or 0
    adult   = calculated.get('Total Adult Programs for 18+', 0) or 0
    gen     = calculated.get('Total Gen Audience', 0) or 0
    if any([kids05, kids611, ya, adult, gen]):
        _save('Total Programs 0-11', kids05 + kids611)
        _save('Total of all programs', kids05 + kids611 + ya + adult + gen)

    for age, label in [('0-5',              'children_05'),
                        ('6-11',             'children_611'),
                        ('12-18',            'ya'),
                        ('19+',              'adult'),
                        ('General Interest', 'gen')]:
        total = 0
        found = False
        for t in PROG_TYPES:
            v = sum_metric(bs_entries_no_locker, f'{t} Attendance {age}')
            if v is not None:
                total += v
                found = True
        calculated[f'att_{label}'] = round(total) if found else None

    c05  = calculated.get('att_children_05', 0) or 0
    c611 = calculated.get('att_children_611', 0) or 0
    ya_a = calculated.get('att_ya', 0) or 0
    ad_a = calculated.get('att_adult', 0) or 0
    ge_a = calculated.get('att_gen', 0) or 0

    _save('Children 0 to 11 programs attendance', c05 + c611)
    _save('YA 12-18 programs attendance', ya_a)
    _save('Adult programs attendance', ad_a)
    _save('Total General attendance', ge_a)
    if any([c05, c611, ya_a, ad_a, ge_a]):
        _save('Total Attendance all programs and all ages',
              c05 + c611 + ya_a + ad_a + ge_a)

    _save('Number of staff trained',
          sum_metric(bs_entries_no_locker, 'Number of Staff Taking Training'))
    _save('Number of hours of training attended by staff',
          sum_metric(bs_entries_no_locker, 'Number of Hours Staff Attended Training'))
    _save('Number of items distributed as take-and-makes',
          sum_metric(bs_entries_no_locker, 'Take & Makes / Other Passive Program Participants'))

    return len(calculated)


@app.route('/annual-survey/<int:year>/calculate', methods=['POST'])
def annual_survey_calculate(year):
    n = _calculate_annual_metrics(year)
    db.session.commit()
    flash(f'{n} metrics auto-calculated for FY{year} from monthly data.', 'success')
    if request.form.get('next') == 'dashboard':
        return redirect(url_for('annual_survey_dashboard'))
    return redirect(url_for('annual_survey_enter', year=year))


@app.route('/annual-survey/calculate-bulk', methods=['POST'])
def annual_survey_calculate_bulk():
    years = request.form.getlist('years', type=int)
    if not years:
        flash('No years selected.', 'warning')
        return redirect(url_for('annual_survey_dashboard'))
    total = sum(_calculate_annual_metrics(y) for y in years)
    db.session.commit()
    flash(f'{total} metrics auto-calculated across {len(years)} fiscal year(s): '
          + ', '.join(f'FY{y}' for y in sorted(years)) + '.', 'success')
    return redirect(url_for('annual_survey_dashboard'))


@app.route('/reports/overview')
def report_overview():
    bs_cat = Category.query.filter_by(name='Branch Stats').first()

    full_fy_years = []
    if bs_cat:
        bs_months = db.session.query(Entry.year, Entry.month).filter(
            Entry.category_id == bs_cat.id,
            Entry.month.isnot(None)
        ).distinct().all()

        fy_months = {}
        for yr, mo in bs_months:
            fy = yr + 1 if mo >= 7 else yr
            fy_months.setdefault(fy, set()).add((yr, mo))

        def is_full_fy(fy_year, month_set):
            needed = (
                {(fy_year - 1, m) for m in range(7, 13)} |
                {(fy_year, m) for m in range(1, 7)}
            )
            return needed.issubset(month_set)

        now = datetime.now()
        cur_fy = now.year + 1 if now.month >= 7 else now.year
        full_fy_years = sorted(
            [fy for fy, months in fy_months.items() if fy < cur_fy and is_full_fy(fy, months)],
            reverse=True
        )

    fy1 = fy2 = stats = None

    if len(full_fy_years) >= 2:
        fy2, fy1 = full_fy_years[0], full_fy_years[1]

        def fy_totals(fy_year):
            entries = Entry.query.options(joinedload(Entry.values)).filter_by(
                category_id=bs_cat.id
            ).filter(
                or_(
                    and_(Entry.year == fy_year - 1, Entry.month >= 7),
                    and_(Entry.year == fy_year, Entry.month <= 6)
                )
            ).all()
            id_to_name = {m.id: m.name for m in bs_cat.metrics}
            totals = {}
            for e in entries:
                if e.branch and ('system wide' in e.branch.name.lower() or
                                 'locker' in e.branch.name.lower() or
                                 e.branch.name == 'Administration'):
                    continue
                for ev in e.values:
                    n = id_to_name.get(ev.metric_id)
                    if n and ev.value_number is not None:
                        totals[n] = totals.get(n, 0) + ev.value_number
            return totals

        d1 = fy_totals(fy1)
        d2 = fy_totals(fy2)

        AGE   = AGE_GROUPS
        TYPES = PROG_TYPES

        def iv(d, key):
            val = d.get(key)
            if val is None:
                return None
            return int(val) if val == int(val) else round(val, 1)

        def prog_sessions(d):
            total = sum((iv(d, f'{t} Sessions {a}') or 0) for t in TYPES for a in AGE)
            return total or None

        def prog_attendance(d):
            total = sum((iv(d, f'{t} Attendance {a}') or 0) for t in TYPES for a in AGE)
            return total or None

        def new_cards(d):
            total = (iv(d, 'New Library Card Registrations, Adult') or 0) + \
                    (iv(d, 'New Library Card Registrations, Juvenile') or 0)
            return total or None

        stats = [
            ('bi-arrow-repeat',    'Total Circulation',            iv(d1, 'Total Branch Circulation'), iv(d2, 'Total Branch Circulation'), True),
            ('bi-wifi',            'Hotspot Circulation',          iv(d1, 'Hotspots Circulation'),     iv(d2, 'Hotspots Circulation'),     True),
            ('bi-door-open',       'Gate Count',                   iv(d1, 'Gate Count'),               iv(d2, 'Gate Count'),               True),
            ('bi-calendar-event',  'Program Sessions',             prog_sessions(d1),                   prog_sessions(d2),                  True),
            ('bi-people-fill',     'Program Attendance',           prog_attendance(d1),                 prog_attendance(d2),                True),
            ('bi-credit-card',     'New Library Card Applications',new_cards(d1),                       new_cards(d2),                      True),
            ('bi-printer',         'Total Prints',                  iv(d1, 'Total Prints per Month'),   iv(d2, 'Total Prints per Month'),   True),
        ]

    return render_template('reports/overview.html',
                           full_fy_years=full_fy_years,
                           fy1=fy1, fy2=fy2,
                           stats=stats)


@app.route('/reports/impact')
@admin_required
def report_impact():
    bs_cat = Category.query.filter_by(name='Branch Stats').first()

    fy1, fy2 = 2023, 2024
    data = None
    selectable_years = []
    sel_fy = fy2

    if fy1 and fy2:
        def fy_totals(fy_year):
            entries = Entry.query.options(joinedload(Entry.values)).filter_by(
                category_id=bs_cat.id
            ).filter(
                or_(
                    and_(Entry.year == fy_year - 1, Entry.month >= 7),
                    and_(Entry.year == fy_year, Entry.month <= 6)
                )
            ).all()
            id_to_name = {m.id: m.name for m in bs_cat.metrics}
            totals = {}
            for e in entries:
                bname = e.branch.name if e.branch else ''
                if bname == 'YCL (System Wide)' or 'Lockers' in bname or bname == 'Administration':
                    continue
                for ev in e.values:
                    n = id_to_name.get(ev.metric_id)
                    if n and ev.value_number is not None:
                        totals[n] = totals.get(n, 0) + ev.value_number
            return totals

        d1 = fy_totals(fy1)
        d2 = fy_totals(fy2)
        AGE   = AGE_GROUPS
        TYPES = PROG_TYPES

        def iv(d, key):
            val = d.get(key)
            if val is None:
                return None
            return int(val) if val == int(val) else round(val, 1)

        def pct(old, new):
            if not old or not new:
                return None
            return round((new - old) / old * 100, 1)

        def prog_sessions(d):
            return sum((iv(d, f'{t} Sessions {a}') or 0) for t in TYPES for a in AGE) or None

        def prog_attendance(d):
            return sum((iv(d, f'{t} Attendance {a}') or 0) for t in TYPES for a in AGE) or None

        # Annual Comparables: physical + digital from system-wide annual entries
        eres_cat = Category.query.filter_by(name='eResources').first()

        def ac_totals(fy_year):
            sw = Branch.query.filter(Branch.name == 'YCL (System Wide)').first()
            if not sw:
                return None, None
            phys = None
            bs_e = Entry.query.options(joinedload(Entry.values)).filter_by(
                category_id=bs_cat.id, branch_id=sw.id, year=fy_year, month=None
            ).first()
            if bs_e:
                circ_m = next((m for m in bs_cat.metrics if m.name == 'Total Branch Circulation'), None)
                if circ_m:
                    ev = next((v for v in bs_e.values if v.metric_id == circ_m.id), None)
                    if ev and ev.value_number is not None:
                        phys = int(ev.value_number)
            dig = None
            if eres_cat:
                er_e = Entry.query.options(joinedload(Entry.values)).filter_by(
                    category_id=eres_cat.id, branch_id=sw.id, year=fy_year, month=None
                ).first()
                if er_e:
                    total = sum(v.value_number for v in er_e.values if v.value_number is not None)
                    if total > 0:
                        dig = int(total)
            return phys, dig

        ac_phys1, digital1 = ac_totals(fy1)
        ac_phys2, digital2 = ac_totals(fy2)

        circ1      = ac_phys1 if ac_phys1 is not None else iv(d1, 'Total Branch Circulation')
        circ2      = ac_phys2 if ac_phys2 is not None else iv(d2, 'Total Branch Circulation')
        hot1       = iv(d1, 'Hotspots Circulation')
        hot2       = iv(d2, 'Hotspots Circulation')
        gate1      = iv(d1, 'Gate Count')
        gate2      = iv(d2, 'Gate Count')
        sess1      = prog_sessions(d1)
        sess2      = prog_sessions(d2)
        att1       = prog_attendance(d1)
        att2       = prog_attendance(d2)
        cards1     = (iv(d1, 'New Library Card Registrations, Adult') or 0) + \
                     (iv(d1, 'New Library Card Registrations, Juvenile') or 0) or None
        cards2     = (iv(d2, 'New Library Card Registrations, Adult') or 0) + \
                     (iv(d2, 'New Library Card Registrations, Juvenile') or 0) or None
        pc_res1    = iv(d1, 'PC Reservations')
        pc_res2    = iv(d2, 'PC Reservations')

        # Only show physical/total % change when both years come from Annual Comparables
        phys_pct  = pct(circ1, circ2) if (ac_phys1 is not None and ac_phys2 is not None) else None
        total1    = (circ1 + digital1) if (ac_phys1 is not None and digital1 is not None) else None
        total2    = (circ2 + digital2) if (ac_phys2 is not None and digital2 is not None) else None
        total_pct = pct(total1, total2) if (total1 is not None and total2 is not None) else None

        CHILD_AGES = ['0-5', '6-11']
        YA_AGES    = ['12-18']
        child1 = sum((iv(d1, f'{t} Sessions {a}') or 0) for t in TYPES for a in CHILD_AGES) or None
        child2 = sum((iv(d2, f'{t} Sessions {a}') or 0) for t in TYPES for a in CHILD_AGES) or None
        ya1    = sum((iv(d1, f'{t} Sessions {a}') or 0) for t in TYPES for a in YA_AGES) or None
        ya2    = sum((iv(d2, f'{t} Sessions {a}') or 0) for t in TYPES for a in YA_AGES) or None

        data = {
            'circulation':    {'v1': circ1,    'v2': circ2,    'pct': phys_pct},
            'digital':        {'v1': digital1, 'v2': digital2, 'pct': pct(digital1, digital2)},
            'total_checkout': {'v1': total1,   'v2': total2,   'pct': total_pct},
            'hotspots':       {'v1': hot1,     'v2': hot2,     'pct': pct(hot1,     hot2)},
            'gate':           {'v1': gate1,    'v2': gate2,    'pct': pct(gate1,    gate2)},
            'sessions':       {'v1': sess1,    'v2': sess2,    'pct': pct(sess1,    sess2)},
            'attendance':     {'v1': att1,     'v2': att2,     'pct': pct(att1,     att2)},
            'cards':          {'v1': cards1,   'v2': cards2,   'pct': pct(cards1,   cards2)},
            'pc_reservations': {'v1': pc_res1, 'v2': pc_res2,  'pct': pct(pc_res1,  pc_res2)},
            'children_sess':  {'v1': child1,   'v2': child2,   'pct': pct(child1,   child2)},
            'ya_sess':        {'v1': ya1,      'v2': ya2,      'pct': pct(ya1,      ya2)},
        }

    return render_template('reports/impact.html',
                           selectable_years=selectable_years,
                           sel_fy=sel_fy,
                           fy1=fy1, fy2=fy2,
                           data=data)


@app.route('/reports/impact.pdf')
@admin_required
def report_impact_pdf():
    bs_cat = Category.query.filter_by(name='Branch Stats').first()

    fy1, fy2 = 2023, 2024

    def fy_totals(fy_year):
        entries = Entry.query.options(joinedload(Entry.values)).filter_by(
            category_id=bs_cat.id
        ).filter(
            or_(
                and_(Entry.year == fy_year - 1, Entry.month >= 7),
                and_(Entry.year == fy_year, Entry.month <= 6)
            )
        ).all()
        id_to_name = {m.id: m.name for m in bs_cat.metrics}
        totals = {}
        for e in entries:
            bname = e.branch.name if e.branch else ''
            if bname == 'YCL (System Wide)' or 'Lockers' in bname or bname == 'Administration':
                continue
            for ev in e.values:
                n = id_to_name.get(ev.metric_id)
                if n and ev.value_number is not None:
                    totals[n] = totals.get(n, 0) + ev.value_number
        return totals

    d1 = fy_totals(fy1)
    d2 = fy_totals(fy2)
    AGE   = AGE_GROUPS
    TYPES = PROG_TYPES

    def iv(d, key):
        val = d.get(key)
        if val is None:
            return None
        return int(val) if val == int(val) else round(val, 1)

    def pct(old, new):
        if not old or not new:
            return None
        return round((new - old) / old * 100, 1)

    # Annual Comparables: physical + digital from system-wide annual entries
    eres_cat = Category.query.filter_by(name='eResources').first()

    def ac_totals(fy_year):
        sw = Branch.query.filter(Branch.name == 'YCL (System Wide)').first()
        if not sw:
            return None, None
        phys = None
        bs_e = Entry.query.options(joinedload(Entry.values)).filter_by(
            category_id=bs_cat.id, branch_id=sw.id, year=fy_year, month=None
        ).first()
        if bs_e:
            circ_m = next((m for m in bs_cat.metrics if m.name == 'Total Branch Circulation'), None)
            if circ_m:
                ev = next((v for v in bs_e.values if v.metric_id == circ_m.id), None)
                if ev and ev.value_number is not None:
                    phys = int(ev.value_number)
        dig = None
        if eres_cat:
            er_e = Entry.query.options(joinedload(Entry.values)).filter_by(
                category_id=eres_cat.id, branch_id=sw.id, year=fy_year, month=None
            ).first()
            if er_e:
                total = sum(v.value_number for v in er_e.values if v.value_number is not None)
                if total > 0:
                    dig = int(total)
        return phys, dig

    ac_phys1, digital1 = ac_totals(fy1)
    ac_phys2, digital2 = ac_totals(fy2)

    circ1   = ac_phys1 if ac_phys1 is not None else iv(d1, 'Total Branch Circulation')
    circ2   = ac_phys2 if ac_phys2 is not None else iv(d2, 'Total Branch Circulation')
    hot1    = iv(d1, 'Hotspots Circulation')
    hot2    = iv(d2, 'Hotspots Circulation')
    gate1   = iv(d1, 'Gate Count')
    gate2   = iv(d2, 'Gate Count')
    CHILD_AGES = ['0-5', '6-11']
    YA_AGES    = ['12-18']
    sess1   = sum((iv(d1, f'{t} Sessions {a}') or 0) for t in TYPES for a in AGE) or None
    sess2   = sum((iv(d2, f'{t} Sessions {a}') or 0) for t in TYPES for a in AGE) or None
    att1    = sum((iv(d1, f'{t} Attendance {a}') or 0) for t in TYPES for a in AGE) or None
    att2    = sum((iv(d2, f'{t} Attendance {a}') or 0) for t in TYPES for a in AGE) or None
    child1  = sum((iv(d1, f'{t} Sessions {a}') or 0) for t in TYPES for a in CHILD_AGES) or None
    child2  = sum((iv(d2, f'{t} Sessions {a}') or 0) for t in TYPES for a in CHILD_AGES) or None
    ya1     = sum((iv(d1, f'{t} Sessions {a}') or 0) for t in TYPES for a in YA_AGES) or None
    ya2     = sum((iv(d2, f'{t} Sessions {a}') or 0) for t in TYPES for a in YA_AGES) or None
    cards1  = (iv(d1, 'New Library Card Registrations, Adult') or 0) + \
              (iv(d1, 'New Library Card Registrations, Juvenile') or 0) or None
    cards2  = (iv(d2, 'New Library Card Registrations, Adult') or 0) + \
              (iv(d2, 'New Library Card Registrations, Juvenile') or 0) or None
    pc_res1 = iv(d1, 'PC Reservations')
    pc_res2 = iv(d2, 'PC Reservations')

    # Only show physical/total % change when both years come from Annual Comparables
    phys_pct  = pct(circ1, circ2) if (ac_phys1 is not None and ac_phys2 is not None) else None
    total1    = (circ1 + digital1) if (ac_phys1 is not None and digital1 is not None) else None
    total2    = (circ2 + digital2) if (ac_phys2 is not None and digital2 is not None) else None
    total_pct = pct(total1, total2) if (total1 is not None and total2 is not None) else None

    data = {
        'circulation':    {'v1': circ1,    'v2': circ2,    'pct': phys_pct},
        'digital':        {'v1': digital1, 'v2': digital2, 'pct': pct(digital1, digital2)},
        'total_checkout': {'v1': total1,   'v2': total2,   'pct': total_pct},
        'hotspots':       {'v1': hot1,     'v2': hot2,     'pct': pct(hot1,     hot2)},
        'gate':           {'v1': gate1,    'v2': gate2,    'pct': pct(gate1,    gate2)},
        'sessions':       {'v1': sess1,    'v2': sess2,    'pct': pct(sess1,    sess2)},
        'attendance':     {'v1': att1,     'v2': att2,     'pct': pct(att1,     att2)},
        'cards':          {'v1': cards1,   'v2': cards2,   'pct': pct(cards1,   cards2)},
        'pc_reservations': {'v1': pc_res1, 'v2': pc_res2,  'pct': pct(pc_res1,  pc_res2)},
        'children_sess':  {'v1': child1,   'v2': child2,   'pct': pct(child1,   child2)},
        'ya_sess':        {'v1': ya1,      'v2': ya2,      'pct': pct(ya1,      ya2)},
    }

    import traceback
    try:
        from weasyprint import HTML as WeasyprintHTML
        html_str = render_template('reports/impact.html',
                                   fy1=fy1, fy2=fy2, data=data,
                                   selectable_years=[], sel_fy=fy2)
        pdf_bytes = WeasyprintHTML(string=html_str, base_url=request.url_root).write_pdf()
    except Exception:
        tb = traceback.format_exc()
        app.logger.error('PDF generation failed:\n%s', tb)
        return f'<pre style="white-space:pre-wrap">PDF generation error — please send this to your admin:\n\n{tb}</pre>', 500

    filename = f'YCL_Impact_Report_FY{fy1}-FY{fy2}.pdf'
    return send_file(io.BytesIO(pdf_bytes), mimetype='application/pdf',
                     as_attachment=True, download_name=filename)


@app.route('/reports/impact.docx')
@admin_required
def report_impact_docx():
    from docx import Document
    from docx.shared import Pt, RGBColor, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    bs_cat   = Category.query.filter_by(name='Branch Stats').first()
    eres_cat = Category.query.filter_by(name='eResources').first()
    fy1, fy2 = 2023, 2024

    def _fy_totals(fy_year):
        entries = Entry.query.options(joinedload(Entry.values)).filter_by(
            category_id=bs_cat.id
        ).filter(
            or_(
                and_(Entry.year == fy_year - 1, Entry.month >= 7),
                and_(Entry.year == fy_year, Entry.month <= 6)
            )
        ).all()
        id_to_name = {m.id: m.name for m in bs_cat.metrics}
        totals = {}
        for e in entries:
            bname = e.branch.name if e.branch else ''
            if bname == 'YCL (System Wide)' or 'Lockers' in bname or bname == 'Administration':
                continue
            for ev in e.values:
                n = id_to_name.get(ev.metric_id)
                if n and ev.value_number is not None:
                    totals[n] = totals.get(n, 0) + ev.value_number
        return totals

    def _iv(d, key):
        val = d.get(key)
        if val is None:
            return None
        return int(val) if val == int(val) else round(val, 1)

    def _ac_totals(fy_year):
        sw = Branch.query.filter(Branch.name == 'YCL (System Wide)').first()
        if not sw:
            return None, None
        phys = None
        bs_e = Entry.query.options(joinedload(Entry.values)).filter_by(
            category_id=bs_cat.id, branch_id=sw.id, year=fy_year, month=None
        ).first()
        if bs_e:
            circ_m = next((m for m in bs_cat.metrics if m.name == 'Total Branch Circulation'), None)
            if circ_m:
                ev = next((v for v in bs_e.values if v.metric_id == circ_m.id), None)
                if ev and ev.value_number is not None:
                    phys = int(ev.value_number)
        dig = None
        if eres_cat:
            er_e = Entry.query.options(joinedload(Entry.values)).filter_by(
                category_id=eres_cat.id, branch_id=sw.id, year=fy_year, month=None
            ).first()
            if er_e:
                total = sum(v.value_number for v in er_e.values if v.value_number is not None)
                if total > 0:
                    dig = int(total)
        return phys, dig

    d2 = _fy_totals(fy2)
    AGE   = AGE_GROUPS
    TYPES = PROG_TYPES

    ac_phys2, digital2 = _ac_totals(fy2)
    circ2   = ac_phys2 if ac_phys2 is not None else _iv(d2, 'Total Branch Circulation')
    hot2    = _iv(d2, 'Hotspots Circulation')
    gate2   = _iv(d2, 'Gate Count')
    sess2   = sum((_iv(d2, f'{t} Sessions {a}') or 0) for t in TYPES for a in AGE) or None
    att2    = sum((_iv(d2, f'{t} Attendance {a}') or 0) for t in TYPES for a in AGE) or None
    cards2  = (_iv(d2, 'New Library Card Registrations, Adult') or 0) + \
              (_iv(d2, 'New Library Card Registrations, Juvenile') or 0) or None
    pc_res2 = _iv(d2, 'PC Reservations')
    total2  = (circ2 + digital2) if (ac_phys2 is not None and digital2 is not None) else None

    def fmt(v):
        return f'{int(v):,}' if v is not None else '—'

    # ── Build document ──
    doc = Document()
    sec = doc.sections[0]
    sec.top_margin    = Inches(0.75)
    sec.bottom_margin = Inches(0.75)
    sec.left_margin   = Inches(1.0)
    sec.right_margin  = Inches(1.0)

    BLUE   = RGBColor(0x1a, 0x4f, 0x9e)
    GREEN  = RGBColor(0x1e, 0x84, 0x49)
    PURPLE = RGBColor(0x6c, 0x34, 0x83)
    TEAL   = RGBColor(0x11, 0x7a, 0x65)
    BROWN  = RGBColor(0x78, 0x42, 0x12)
    DKBLUE = RGBColor(0x1a, 0x52, 0x76)
    GREY   = RGBColor(0x55, 0x55, 0x55)
    LGREY  = RGBColor(0x88, 0x88, 0x88)

    def shade_cell(cell, hex_color):
        tc   = cell._tc
        tcPr = tc.get_or_add_tcPr()
        shd  = OxmlElement('w:shd')
        shd.set(qn('w:val'),   'clear')
        shd.set(qn('w:color'), 'auto')
        shd.set(qn('w:fill'),  hex_color)
        tcPr.append(shd)

    def add_heading2(text, color):
        h = doc.add_heading(text, level=2)
        for run in h.runs:
            run.font.color.rgb = color

    def add_body(parts):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(6)
        for text, bold in parts:
            r = p.add_run(text)
            r.bold       = bold
            r.font.size  = Pt(10)
        return p

    def add_quote(text, source):
        p = doc.add_paragraph(style='No Spacing')
        p.paragraph_format.left_indent  = Inches(0.4)
        p.paragraph_format.right_indent = Inches(0.4)
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after  = Pt(2)
        pPr  = p._p.get_or_add_pPr()
        pBdr = OxmlElement('w:pBdr')
        lel  = OxmlElement('w:left')
        lel.set(qn('w:val'),   'single')
        lel.set(qn('w:sz'),    '18')
        lel.set(qn('w:space'), '6')
        lel.set(qn('w:color'), '4a7fce')
        pBdr.append(lel)
        pPr.append(pBdr)
        r = p.add_run(f'“{text}”')
        r.italic     = True
        r.font.size  = Pt(10)
        r.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
        sp = doc.add_paragraph(style='No Spacing')
        sp.paragraph_format.left_indent = Inches(0.4)
        sp.paragraph_format.space_after = Pt(10)
        sr = sp.add_run(source)
        sr.font.size      = Pt(9)
        sr.font.color.rgb = LGREY

    # Title
    tp = doc.add_paragraph()
    tp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    tp.paragraph_format.space_after = Pt(2)
    tr = tp.add_run('Community Impact Report')
    tr.bold = True; tr.font.size = Pt(22); tr.font.color.rgb = BLUE

    sp = doc.add_paragraph()
    sp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sp.paragraph_format.space_after = Pt(12)
    sr = sp.add_run(f'York County Library  ·  FY{fy2} (Jul {fy2 - 1}–Jun {fy2})')
    sr.font.size = Pt(11); sr.font.color.rgb = GREY

    # Survey intro
    bp = doc.add_paragraph()
    bp.paragraph_format.space_after = Pt(10)
    br = bp.add_run(
        'In our 2026 patron survey, 544 community members shared what the library means to them. '
        '92.3% had visited in the past year — and their responses, shown throughout this report, '
        'tell the story behind the numbers.'
    )
    br.italic = True; br.font.size = Pt(10)

    # At a Glance table
    add_heading2(f'At a Glance — FY{fy2}', BLUE)
    at_a_glance = [
        ('Total Physical Checkouts', circ2),
        ('Digital Checkouts',        digital2),
        ('Visits (Gate Count)',      gate2),
        ('Program Attendance',       att2),
        ('New Library Cards',        cards2),
        ('PC Reservations',          pc_res2),
        ('Program Sessions',         sess2),
        ('Hotspot Circulation',      hot2),
    ]
    tbl = doc.add_table(rows=2, cols=4)
    tbl.style = 'Table Grid'
    for i, (label, val) in enumerate(at_a_glance):
        cell = tbl.cell(i // 4, i % 4)
        shade_cell(cell, 'e8f0ff')
        cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        nr = cell.paragraphs[0].add_run(fmt(val) + '\n')
        nr.bold = True; nr.font.size = Pt(14); nr.font.color.rgb = BLUE
        lr = cell.paragraphs[0].add_run(label)
        lr.font.size = Pt(8); lr.font.color.rgb = GREY
    doc.add_paragraph()

    # Section 1: You Keep Coming Back
    add_heading2('You Keep Coming Back', GREEN)
    add_body([
        ('The library recorded ', False), (f'{fmt(gate2)} visits', True),
        (f' in FY{fy2}. Our survey confirms the pattern: ', False),
        ('92.3% of respondents had visited in the past year', True),
        (', with teens leading the way — ', False), ('57.1% visit every week', True),
        (', and nearly half of 25–40 year-olds (49.7%) do the same.', False),
    ])
    add_body([
        (f'{fmt(pc_res2)} PC reservation sessions', True),
        (' show that for many patrons, the library is their primary point of internet and computer '
         'access — a function that survey respondents consistently rated among our most valued services.', False),
    ])
    add_body([
        ('Even patrons who visit less frequently stay connected: ', False),
        ('86–93% use our website', True),
        (' across all age groups, and ', False), ('50–64% use the YCL mobile app', True),
        (' — including 59% of seniors aged 65 and older.', False),
    ])
    add_quote(
        'Western York County needs another library. It doesn’t have to have all the programs… '
        'but a location with computers, books, and a hold shelf so people in Hickory Grove don’t '
        'have to plan their trips based on when they’re running to York.',
        '— Survey respondent'
    )

    # Section 2: Connecting You to Stories
    add_heading2('Connecting You to Stories & Ideas', DKBLUE)
    add_body([
        ('Borrowing books', True),
        (' is the single highest-rated service across every age group in our survey — averaging ', False),
        ('3.79 to 4.00 out of 5', True), (' (“Very Important”). That demand shows in the numbers:', False),
    ])
    for label, val in [('Physical checkouts', circ2), ('Digital checkouts', digital2)]:
        pb = doc.add_paragraph(style='List Bullet')
        pb.paragraph_format.space_after = Pt(2)
        pb.add_run(f'{label}: ').font.size = Pt(10)
        vr = pb.add_run(fmt(val)); vr.bold = True; vr.font.size = Pt(10)
    if total2 is not None:
        pb = doc.add_paragraph(style='List Bullet')
        pb.paragraph_format.space_after = Pt(6)
        pb.add_run('Combined total: ').font.size = Pt(10)
        vr = pb.add_run(fmt(total2)); vr.bold = True; vr.font.size = Pt(10)
    add_body([
        ('Patron feedback points to clear growth opportunities: more physical copies at smaller branches, '
         'complete series in digital collections, and reduced hold wait times for new releases on '
         'Libby and Hoopla. These are gaps the library is actively working to address.', False),
    ])
    add_quote(
        'It is hard to browse books as the selection is small in person. I do appreciate being able to '
        'get them online, but I love spontaneously getting books.',
        '— Survey respondent'
    )

    # Section 3: Learning Together
    add_heading2('Learning Together', PURPLE)
    add_body([
        ('YCL offered ', False), (f'{fmt(sess2)} program sessions', True),
        (f' in FY{fy2}, drawing ', False), (f'{fmt(att2)} participants', True),
        ('. Our survey found that ', False),
        ('61.2% of patrons attended at least one YCL signature event', True),
        (', with teens and young adults leading at 71.4%.', False),
    ])
    add_body([
        ('Signature events were a particular strength: the ', False),
        ('Summer Learning Challenge', True), (' received 272 selections and the ', False),
        ('Winter Reading Challenge', True),
        (' 218 — showing that structured reading programs resonate across age groups.', False),
    ])
    add_body([
        ('Lifelong learning programs', True),
        (' topped the list of what patrons want more of, chosen by ', False),
        ('53% of respondents', True),
        (' (288 selections). But a clear barrier emerged: the majority of employed adults simply cannot '
         'attend programs held during working hours. Evening (after 5 p.m.) and Saturday programming '
         'were among the most-requested changes.', False),
    ])
    add_body([
        ('Equity note: ', True),
        ('Fort Mill-only patrons attended signature events at a rate of 51.6% — nearly 20 points '
         'below Rock Hill patrons (71.5%). Capacity and space constraints at Fort Mill are a key driver '
         'of this gap.', False),
    ])
    add_quote(
        'The majority of the programs I am interested in are held during working hours. I’m only '
        'in my 40s and work full time but would love to connect with other people through these clubs '
        '— and it’s just not possible during the week. Why are there no weekend clubs?',
        '— Survey respondent'
    )
    add_quote(
        'More events for kids aged 8–13. More science programs. I would love to see more Tween '
        'programming — my 10-year-old feels stuck between little kid programs and teen programs.',
        '— Survey respondent (composite)'
    )

    # Section 4: Growing Our Community
    add_heading2('Growing Our Community', TEAL)
    add_body([
        ('YCL issued ', False), (f'{fmt(cards2)} new library cards', True),
        (f' in FY{fy2}. New cardholders represent fresh connections to the community — and an '
         'opportunity to retain them through the services they value most.', False),
    ])
    add_body([
        ('Our survey skews toward established users (92.3% had visited in the past year), which means '
         'the 7.7% of respondents who are non-users or lapsed visitors are a window into who we’re '
         'not yet reaching. Among non-users, ', False),
        ('17 of 42 cited being too busy', True),
        (' — pointing again to scheduling and convenience as the primary barrier.', False),
    ])
    add_body([
        ('Young adults aged 19–24 show the most untapped potential: only ', False),
        ('15.4% visit weekly', True),
        (' (vs. 57.1% of teens), suggesting that the transition out of school-age programming '
         'leaves a gap the library can fill with targeted young adult services.', False),
    ])
    add_quote(
        'Events for 20–30 somethings looking to make friends. Young adult activities (18–28)? '
        'More programs for the 18–22 college age range.',
        '— Survey respondents'
    )

    # Section 5: Expanding Access
    add_heading2('Expanding Access Beyond Our Walls', BROWN)
    add_body([
        (f'{fmt(hot2)} hotspot checkouts', True),
        (' put internet access in the hands of patrons who need it most — at home, at work, and '
         'in transit. For many families, a YCL hotspot is the difference between connected and left behind.', False),
    ])
    add_body([
        ('In-branch, ', False), (f'{fmt(pc_res2)} PC reservation sessions', True),
        (' reflect the library’s role as a technology access point. Help from librarians — '
         'rated ', False), ('3.62 to 3.93 out of 5', True),
        (' across all age groups — is the trusted guide that makes that access meaningful.', False),
    ])
    add_quote(
        'Having a tool rental/makerspace or woodshop area would be incredible! The Richland library '
        'in Columbia has a great makerspace that creates accessibility for a lot of people.',
        '— Survey respondent'
    )

    # Section 6: What You're Asking For Next
    add_heading2('What You’re Asking For Next', BLUE)
    add_body([
        ('When asked what they want added or improved, ', False),
        ('430 patrons wrote detailed open-ended responses', True),
        (' (a 99.4% response rate). Their top strategic priorities, by selection:', False),
    ])
    for label, count, pct_val in [
        ('Lifelong Learning Programs',     '288 selections', '53%'),
        ('Library of Things',              '273 selections', '50%'),
        ('Makerspace',                     '230 selections', '42%'),
        ('Meeting Spaces',                 '183 selections', '34%'),
        ('Career & Workforce Development', '176 selections', '32%'),
    ]:
        pb = doc.add_paragraph(style='List Bullet')
        pb.paragraph_format.space_after = Pt(2)
        br2 = pb.add_run(label); br2.bold = True; br2.font.size = Pt(10)
        nr2 = pb.add_run(f' — {count} ({pct_val} of respondents)')
        nr2.font.size = Pt(10)
    doc.add_paragraph()
    add_body([
        ('The Fort Mill branch came up repeatedly — patrons called it “too small” and '
         '“cramped,” and multiple respondents specifically requested a second location or major '
         'expansion. Fort Mill patrons’ event attendance gap (51.6% vs. 71.5% system-wide) is a '
         'measurable consequence of those space constraints.', False),
    ])
    add_quote(
        'Fort Mill library is too small!!! We need a bigger location or another branch in Fort Mill desperately!',
        '— Survey respondent'
    )
    add_quote(
        'Heavy emphasis on Library of Things and Makerspaces. These spaces will encourage creativity '
        'and provide community support by making it more accessible.',
        '— Survey respondent'
    )

    # Full data table
    add_heading2(f'Full Data — FY{fy2}', BLUE)
    data_rows = [
        ('Total Physical Checkouts',             circ2),
        ('Digital Checkouts',                    digital2),
        ('Total Checkouts (Physical + Digital)',  total2),
        ('Hotspot Circulation',                  hot2),
        ('Gate Count',                           gate2),
        ('Program Sessions',                     sess2),
        ('Program Attendance',                   att2),
        ('New Library Cards',                    cards2),
        ('PC Reservations',                      pc_res2),
    ]
    dtbl = doc.add_table(rows=len(data_rows) + 1, cols=2)
    dtbl.style = 'Table Grid'
    hdr_row = dtbl.rows[0]
    for cell in hdr_row.cells:
        shade_cell(cell, 'dce6f1')
    hr0 = hdr_row.cells[0].paragraphs[0].add_run('Metric')
    hr0.bold = True; hr0.font.size = Pt(10)
    hr1 = hdr_row.cells[1].paragraphs[0].add_run(f'FY{fy2}')
    hr1.bold = True; hr1.font.size = Pt(10)
    hdr_row.cells[1].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
    for i, (label, val) in enumerate(data_rows):
        row = dtbl.rows[i + 1]
        row.cells[0].paragraphs[0].add_run(label).font.size = Pt(10)
        vr = row.cells[1].paragraphs[0].add_run(fmt(val))
        vr.bold = True; vr.font.size = Pt(10)
        row.cells[1].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    filename = f'YCL_Impact_Report_FY{fy2}.docx'
    return send_file(buf,
                     mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                     as_attachment=True,
                     download_name=filename)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
