from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, session
from flask_login import LoginManager, login_user, logout_user, current_user
from models import db, Category, Metric, Branch, Entry, EntryValue, User
from sqlalchemy.orm import joinedload
from sqlalchemy import or_, and_
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

    # Mark Rock Hill desk branches (only Circ and YA report quarterly reference stats)
    for _desk_name in ['Rock Hill - Circulation', 'Rock Hill - YA']:
        _b = Branch.query.filter_by(name=_desk_name).first()
        if _b and not _b.is_desk:
            _b.is_desk = True
    # Rock Hill - Reference is not used; deactivate so it disappears from all lists
    _rhr = Branch.query.filter_by(name='Rock Hill - Reference').first()
    if _rhr and _rhr.is_active:
        _rhr.is_active = False
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
        'nav_categories': Category.query.filter_by(is_active=True).order_by(Category.sort_order).all(),
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

    TYPES = ['ONSITE', 'OFFSITE', 'VIRTUAL']
    AGE   = ['0-5', '6-11', '12-18', '19+', 'General Interest']

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

    # Real service branches for per-branch drill-down (exclude lockers, desks, system-wide)
    _real_branches = Branch.query.filter(
        Branch.is_active == True,
        Branch.is_desk == False,
        ~Branch.name.ilike('%locker%'),
        Branch.name != 'YCL (System Wide)',
        Branch.name != 'Outreach / BKM',
    ).order_by(Branch.sort_order).all()

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
            for b in _real_branches:
                b_last = (Entry.query
                          .filter_by(category_id=cat.id, branch_id=b.id)
                          .order_by(Entry.year.desc(), Entry.month.desc(), Entry.quarter.desc())
                          .first())
                branch_detail.append({'branch': b, 'last_entry': b_last})

        coverage.append({'category': cat, 'last_entry': last, 'branch_detail': branch_detail})

    return render_template('index.html',
                           total_entries=Entry.query.count(),
                           total_categories=Category.query.filter_by(is_active=True).count(),
                           total_branches=Branch.query.filter(
                               Branch.is_active == True,
                               Branch.is_desk == False,
                               ~Branch.name.ilike('%locker%'),
                               Branch.name != 'YCL (System Wide)',
                           ).count(),
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

    q = Entry.query
    if cat_id:
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
                           sel_cat=cat_id, sel_branch=branch_id, sel_year=year)


# ── Create entry ─────────────────────────────────────────────────────────────

def _branches_for_category(category):
    """Return the branch list appropriate for a given category."""
    if category.name == 'Quarterly Reference Stats':
        # Show desks (Circ, YA) but not the parent Rock Hill branch or system-wide
        return (Branch.query.filter_by(is_active=True)
                .filter(~Branch.name.in_(['Rock Hill', 'YCL (System Wide)']))
                .order_by(Branch.is_desk.desc(), Branch.sort_order).all())
    # All other categories: exclude desk-level branches
    return Branch.query.filter_by(is_active=True, is_desk=False).order_by(Branch.name).all()


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
            return str(int(v)) if v == int(v) else f"{v:.2f}".rstrip('0').rstrip('.')
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

    categories = Category.query.filter_by(is_active=True).order_by(Category.sort_order).all()
    available_years = [r[0] for r in db.session.query(Entry.year).distinct()
                                                .order_by(Entry.year.desc()).all()]
    table = branches = category = None

    if cat_id and year and month:
        category = Category.query.get_or_404(cat_id)
        metrics  = Metric.query.filter_by(category_id=cat_id, is_active=True).order_by(Metric.sort_order).all()
        entries  = Entry.query.options(joinedload(Entry.values)).filter_by(category_id=cat_id, year=year, month=month).all()

        branch_set, data = set(), {}
        for e in entries:
            if e.branch_id not in branch_set:
                branch_set.add(e.branch_id)
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
            [b for b in (Branch.query.get(bid) for bid in branch_set) if b],
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
    year       = request.args.get('year',     type=int)
    branch_ids = request.args.getlist('branches', type=int)

    categories  = Category.query.filter_by(is_active=True).order_by(Category.sort_order).all()
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

    if cat_id and metric_id and year:
        category = Category.query.get_or_404(cat_id)
        metric   = Metric.query.get_or_404(metric_id)
        labels   = [MONTHS[mo - 1][:3] for mo in FY_MONTHS]
        datasets = []
        colors   = ['#2c6e8a','#e74c3c','#27ae60','#f39c12','#8e44ad',
                    '#16a085','#d35400','#2980b9','#c0392b','#1abc9c']

        if category.has_branch:
            real_branches = Branch.query.filter(
                Branch.is_active == True,
                Branch.is_desk == False,
                ~Branch.name.ilike('%locker%'),
                Branch.name != 'YCL (System Wide)',
            ).order_by(Branch.name).all()
            locker_branches = Branch.query.filter(
                Branch.is_active == True,
                Branch.name.ilike('%locker%'),
            ).all()
            selected = [b for b in real_branches if b.id in branch_ids] if branch_ids else real_branches
            for i, b in enumerate(selected):
                lockers = [lb for lb in locker_branches
                           if lb.name.lower().startswith(b.name.lower())]
                pts = []
                for mo in FY_MONTHS:
                    yr = year - 1 if mo >= 7 else year
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
            for mo in FY_MONTHS:
                yr = year - 1 if mo >= 7 else year
                e = Entry.query.filter_by(category_id=cat_id, year=yr, month=mo).first()
                ev = EntryValue.query.filter_by(entry_id=e.id, metric_id=metric_id).first() if e else None
                pts.append(ev.value_number if ev else None)
            datasets.append({'label': metric.name, 'data': pts, 'tension': 0.3,
                             'spanGaps': True, 'borderColor': colors[0],
                             'backgroundColor': colors[0] + '22'})

        chart_data = {'labels': labels, 'datasets': datasets}

    all_branches = Branch.query.filter(
        Branch.is_active == True,
        Branch.is_desk == False,
        ~Branch.name.ilike('%locker%'),
        Branch.name != 'YCL (System Wide)',
    ).order_by(Branch.name).all()
    return render_template('reports/trend.html',
                           categories=categories, available_years=available_years,
                           all_branches=all_branches, metrics_json=metrics_json,
                           sel_cat=cat_id, sel_metric=metric_id,
                           sel_year=year, sel_branches=branch_ids,
                           category=category, metric=metric, chart_data=chart_data)


@app.route('/reports/programming')
def report_programming():
    year      = request.args.get('year',   type=int)
    month     = request.args.get('month',  type=int)
    branch_id = request.args.get('branch', type=int)

    available_years = [r[0] for r in db.session.query(Entry.year).distinct()
                                                .order_by(Entry.year.desc()).all()]
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()
    TYPES      = ['ONSITE', 'OFFSITE', 'VIRTUAL']
    AGE_GROUPS = ['0-5', '6-11', '12-18', '19+', 'General Interest']
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

    categories   = Category.query.filter_by(is_active=True).order_by(Category.sort_order).all()
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

    all_branches = Branch.query.filter(
        Branch.is_active == True,
        Branch.is_desk == False,
        ~Branch.name.ilike('%locker%'),
        Branch.name != 'YCL (System Wide)',
    ).order_by(Branch.name).all()
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

    categories = Category.query.filter_by(is_active=True).order_by(Category.sort_order).all()

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
                [b for b in (Branch.query.get(bid) for bid in bid_set) if b],
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

    if table and request.args.get('format') == 'xlsx':
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
                           fy_label=fy_label)


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

    branches = Branch.query.filter_by(is_active=True, is_desk=False).order_by(Branch.name).all()

    TYPES = ['ONSITE', 'OFFSITE', 'VIRTUAL']
    AGES  = ['0-5', '6-11', '12-18', '19+', 'General Interest']

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

    branches = Branch.query.filter(
        Branch.is_active == True,
        Branch.is_desk == False,
        ~Branch.name.ilike('%locker%'),
        Branch.name != 'YCL (System Wide)',
    ).order_by(Branch.name).all()

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


@app.route('/upload', methods=['GET', 'POST'])
def upload_data():
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
                results = detect_and_import(wb, year_override=year_override)
                total_created = sum(r['created'] for r in results)
                flash(f'Upload complete — {total_created} new records added.', 'success')
                comparison = _import_comparison(results)
            except Exception as e:
                flash(f'Upload failed: {e}', 'danger')
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)
    return render_template('upload.html', results=results, comparison=comparison, now=datetime.utcnow())


# Metrics populated via file upload or dedicated forms — excluded from general entry forms
_UPLOAD_SOURCED_METRICS = {
    'New Library Card Registrations, Adult',
    'New Library Card Registrations, Juvenile',
    'New Library Card Registrations, Total',
    'Gate Count',
    'Total Branch Circulation',
    'Hotspots Circulation',
    'ILL - Sent (Main ONLY)',
    'ILL - Received (Main ONLY)',
    'ICLs - Sent (Main ONLY)',
    'ICLs - Received (Main ONLY)',
}

_ILL_METRICS  = {'ILL - Sent (Main ONLY)', 'ILL - Received (Main ONLY)'}
_ICL_METRICS  = {'ICLs - Sent (Main ONLY)', 'ICLs - Received (Main ONLY)'}


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
            entries = Entry.query.options(joinedload(Entry.values)).filter_by(category_id=cat.id, year=y, month=m).all()
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

        AGE  = ['0-5', '6-11', '12-18', '19+', 'General Interest']
        TYPE = ['ONSITE', 'OFFSITE', 'VIRTUAL']

        def prog(sums, kind, age):
            return sum(sums.get(f'{t} {kind} {age}', 0) for t in TYPE) or None

        def pair(curr, prev, label):
            return {'label': label, 'curr': curr, 'prev': prev}

        sections = [
            {
                'title': 'Circulation & Door Count',
                'color': '#1a5276',
                'items': [
                    pair(bs_c.get('Total Branch Circulation'), bs_p.get('Total Branch Circulation'), 'Monthly Circulation'),
                    pair(bs_c.get('Gate Count'),               bs_p.get('Gate Count'),               'Monthly Gate Count'),
                    pair(bs_c.get('Locker Circulation'),       bs_p.get('Locker Circulation'),       'Locker Checkouts'),
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
                'title': 'Monthly Program Sessions',
                'color': '#6c3483',
                'items': [pair(prog(bs_c,'Sessions',a), prog(bs_p,'Sessions',a), f'Sessions {a}') for a in AGE],
            },
            {
                'title': 'Monthly Program Attendance',
                'color': '#784212',
                'items': [pair(prog(bs_c,'Attendance',a), prog(bs_p,'Attendance',a), f'Attendance {a}') for a in AGE],
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

        AGE  = ['0-5', '6-11', '12-18', '19+', 'General Interest']
        TYPES = ['ONSITE', 'OFFSITE', 'VIRTUAL']

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
                           stats=stats, TYPES=['ONSITE', 'OFFSITE', 'VIRTUAL'],
                           AGE=['0-5', '6-11', '12-18', '19+', 'General Interest'])


@app.route('/reports/quarterly_ref')
def report_quarterly_ref():
    year       = request.args.get('year',       type=int)
    holidays   = request.args.get('holidays',   type=int, default=0)
    unexpected = request.args.get('unexpected', type=int, default=0)

    available_years = sorted(
        {r[0] for r in db.session.query(Entry.year).distinct().all()},
        reverse=True
    )

    table = quarterly_totals = None
    open_days = open_weeks = annual_estimate = None

    if year:
        cat = Category.query.filter_by(name='Quarterly Reference Stats').first()
        if cat:
            metric = next((m for m in cat.metrics if m.name == 'Total Transactions for the Week'), None)
            all_branches = _branches_for_category(cat)

            # Raw data: {branch_id: {quarter: value}}
            raw = {b.id: {} for b in all_branches}
            for e in Entry.query.options(joinedload(Entry.values)).filter_by(category_id=cat.id, year=year).all():
                if e.branch_id in raw and e.quarter and metric:
                    for ev in e.values:
                        if ev.metric_id == metric.id and ev.value_number is not None:
                            raw[e.branch_id][e.quarter] = int(ev.value_number)

            # Open-time calculation
            closed_days = (holidays or 0) + (unexpected or 0)
            open_days   = 52 * 6 - closed_days
            open_weeks  = round(open_days / 6, 2)

            def _row(label, branch_ids, is_combined=False):
                """Build one display row by summing across the given branch IDs."""
                q_vals = {}
                for q in range(1, 5):
                    parts = [raw[bid][q] for bid in branch_ids if raw[bid].get(q) is not None]
                    if parts:
                        q_vals[q] = sum(parts)
                avg = round(sum(q_vals.values()) / len(q_vals), 1) if q_vals else None
                est = round(avg * open_weeks) if avg else None
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

            # Annual estimate = sum of per-branch estimates
            annual_estimate = sum(r['estimate'] for r in table if r['estimate']) or None

    return render_template('reports/quarterly_ref.html',
                           available_years=available_years,
                           sel_year=year,
                           holidays=holidays or 0,
                           unexpected=unexpected or 0,
                           table=table,
                           quarterly_totals=quarterly_totals,
                           open_days=open_days,
                           open_weeks=open_weeks,
                           annual_estimate=annual_estimate)


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
    'TOTAL CIRC ALL PHYSICAL',
    'GRAND TOTAL ALL CIRC',
    'Total of all programs',
    'Total Attendance all programs and all ages',
    'Total operating revenue',
    'Expenditures: Total operating',
    'Grand total library staff FTE',
]

_ANNUAL_KPI_METRICS = [
    ('Annual Library Visits (gate count)',       'Gate Count'),
    ('TOTAL CIRC ALL PHYSICAL',                  'Physical Circ'),
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

    # KPI cards for latest year
    kpis = []
    if latest_year:
        ym = by_year[latest_year]
        prev_ym = by_year.get(latest_year - 1, {})
        for metric_name, label in _ANNUAL_KPI_METRICS:
            cur  = _annual_get_value(ym, metric_name)
            prev = _annual_get_value(prev_ym, metric_name)
            kpis.append({'label': label, 'value': cur, 'prev': prev})

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
                           kpis=kpis,
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


@app.route('/annual-survey/<int:year>/calculate', methods=['POST'])
def annual_survey_calculate(year):
    """Auto-calculate metrics that can be derived from the monthly Branch Stats / Online Stats data."""
    from sqlalchemy import or_, and_

    bs_cat     = Category.query.filter_by(name='Branch Stats').first()
    online_cat = Category.query.filter_by(name='Online Stats').first()
    metrics_map = {m.name: m for m in AnnualSurveyMetric.query.all()}

    # FY months: Jul–Dec of year-1, Jan–Jun of year
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

    # Exclude locker branches from branch-level sums
    locker_ids = {b.id for b in Branch.query.filter(Branch.name.ilike('%locker%')).all()}
    bs_entries_no_locker = [e for e in bs_entries if e.branch_id not in locker_ids]

    PROG_TYPES = ['ONSITE', 'OFFSITE', 'VIRTUAL']

    calculated = {}

    def _save(metric_name, value, note):
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

    note = f'Auto-calculated from monthly data for FY{year} (Jul {year-1} – Jun {year})'

    _save('Annual Library Visits (gate count)',
          sum_metric(bs_entries_no_locker, 'Gate Count'), note)
    _save('Number of wireless sessions',
          sum_metric(bs_entries_no_locker, 'WiFi - Unique Sessions'), note)
    _save('Number of website visits',
          sum_metric(online_entries, 'yclibrary.org - Web Sessions'), note)
    _save('TOTAL CIRC ALL PHYSICAL',
          sum_metric(bs_entries_no_locker, 'Total Branch Circulation'), note)

    # Programming sessions by age group
    for age, label in [('0-5', 'Synchronous Pgm Sessions Kids 0-5'),
                        ('6-11', 'Synchronous Pgm Sessions Kids 6-11'),
                        ('12-18', 'Total YA Programs for ages 12-18'),
                        ('19+', 'Total Adult Programs for 18+'),
                        ('General Interest', 'Total Gen Audience')]:
        total = 0
        found = False
        for t in PROG_TYPES:
            v = sum_metric(bs_entries_no_locker, f'{t} Sessions {age}')
            if v is not None:
                total += v
                found = True
        _save(label, round(total) if found else None, note)

    # Derived totals
    kids05  = calculated.get('Synchronous Pgm Sessions Kids 0-5', 0) or 0
    kids611 = calculated.get('Synchronous Pgm Sessions Kids 6-11', 0) or 0
    ya      = calculated.get('Total YA Programs for ages 12-18', 0) or 0
    adult   = calculated.get('Total Adult Programs for 18+', 0) or 0
    gen     = calculated.get('Total Gen Audience', 0) or 0
    if any([kids05, kids611, ya, adult, gen]):
        _save('Total Programs 0-11', kids05 + kids611, note)
        _save('Total of all programs', kids05 + kids611 + ya + adult + gen, note)

    # Programming attendance
    for age, label in [('0-5',  'children_05'), ('6-11', 'children_611'),
                        ('12-18', 'ya'), ('19+', 'adult'), ('General Interest', 'gen')]:
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

    _save('Children 0 to 11 programs attendance', c05 + c611, note)
    _save('YA 12-18 programs attendance', ya_a, note)
    _save('Adult programs attendance', ad_a, note)
    _save('Total General attendance', ge_a, note)
    if any([c05, c611, ya_a, ad_a, ge_a]):
        _save('Total Attendance all programs and all ages',
              c05 + c611 + ya_a + ad_a + ge_a, note)

    # Outreach / training
    _save('Number of staff trained',
          sum_metric(bs_entries_no_locker, 'Number of Staff Taking Training'), note)
    _save('Number of hours of training attended by staff',
          sum_metric(bs_entries_no_locker, 'Number of Hours Staff Attended Training'), note)
    _save('Number of items distributed as take-and-makes',
          sum_metric(bs_entries_no_locker, 'Take & Makes / Other Passive Program Participants'), note)

    db.session.commit()
    flash(f'{len(calculated)} metrics auto-calculated for FY{year} from monthly data.', 'success')
    return redirect(url_for('annual_survey_enter', year=year))


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
