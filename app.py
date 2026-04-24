from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, session
from models import db, Category, Metric, Branch, Entry, EntryValue
from datetime import datetime
import hmac
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
    if request.endpoint not in _PUBLIC_ENDPOINTS and not session.get('logged_in'):
        return redirect(url_for('login', next=request.path))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('logged_in'):
        return redirect(url_for('index'))
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        valid_user = os.environ.get('LOGIN_USERNAME', 'admin')
        valid_pass = os.environ.get('LOGIN_PASSWORD', '')
        if (hmac.compare_digest(username, valid_user) and
                hmac.compare_digest(password, valid_pass) and valid_pass):
            session.permanent = True
            session['logged_in'] = True
            next_url = request.args.get('next') or url_for('index')
            return redirect(next_url)
        error = 'Invalid username or password.'
    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    session.clear()
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
        entries = Entry.query.filter_by(category_id=cat.id, year=y, month=m).all()
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

    # Per-category: most recent entry period
    coverage = []
    for cat in Category.query.filter_by(is_active=True).order_by(Category.sort_order).all():
        last = (Entry.query.filter_by(category_id=cat.id)
                .order_by(Entry.year.desc(), Entry.month.desc(), Entry.quarter.desc())
                .first())
        coverage.append({'category': cat, 'last_entry': last})

    return render_template('index.html',
                           total_entries=Entry.query.count(),
                           total_categories=Category.query.filter_by(is_active=True).count(),
                           total_branches=Branch.query.filter_by(is_active=True, is_desk=False).count(),
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
                           all_branches=Branch.query.filter_by(is_active=True).order_by(Branch.sort_order).all(),
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
    return Branch.query.filter_by(is_active=True, is_desk=False).order_by(Branch.sort_order).all()


@app.route('/entries/new/<int:category_id>', methods=['GET', 'POST'])
def entry_create(category_id):
    category = Category.query.get_or_404(category_id)
    branches = _branches_for_category(category)
    metrics = Metric.query.filter_by(category_id=category_id, is_active=True).order_by(Metric.sort_order).all()
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
                submitted_by=request.form.get('submitted_by', '').strip(),
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
    metrics = Metric.query.filter_by(category_id=category.id, is_active=True).order_by(Metric.sort_order).all()
    values = {ev.metric_id: ev for ev in entry.values}
    year_range = range(datetime.now().year - 5, datetime.now().year + 2)

    if request.method == 'POST':
        entry.branch_id = request.form.get('branch_id', type=int) or None
        entry.year = request.form.get('year', type=int)
        entry.month = request.form.get('month', type=int) or None
        entry.quarter = request.form.get('quarter', type=int) or None
        entry.submitted_by = request.form.get('submitted_by', '').strip()
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
                           branches=Branch.query.order_by(Branch.sort_order).all())


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
        entries  = Entry.query.filter_by(category_id=cat_id, year=year, month=month).all()

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
    available_years = [r[0] for r in db.session.query(Entry.year).distinct()
                                                .order_by(Entry.year.asc()).all()]
    metrics_json = metrics_by_category_json()
    chart_data   = None
    metric = category = None

    if cat_id and metric_id and year:
        category = Category.query.get_or_404(cat_id)
        metric   = Metric.query.get_or_404(metric_id)
        labels   = [m[:3] for m in MONTHS]
        datasets = []
        colors   = ['#2c6e8a','#e74c3c','#27ae60','#f39c12','#8e44ad',
                    '#16a085','#d35400','#2980b9','#c0392b','#1abc9c']

        if category.has_branch:
            all_branches = Branch.query.filter_by(is_active=True).order_by(Branch.sort_order).all()
            selected = [b for b in all_branches if b.id in branch_ids] if branch_ids else all_branches
            for i, b in enumerate(selected):
                pts = []
                for mo in range(1, 13):
                    e = Entry.query.filter_by(category_id=cat_id, branch_id=b.id,
                                              year=year, month=mo).first()
                    ev = EntryValue.query.filter_by(entry_id=e.id, metric_id=metric_id).first() if e else None
                    pts.append(ev.value_number if ev else None)
                datasets.append({'label': b.name, 'data': pts, 'tension': 0.3,
                                 'spanGaps': True, 'borderColor': colors[i % len(colors)],
                                 'backgroundColor': colors[i % len(colors)] + '22'})
        else:
            pts = []
            for mo in range(1, 13):
                e = Entry.query.filter_by(category_id=cat_id, year=year, month=mo).first()
                ev = EntryValue.query.filter_by(entry_id=e.id, metric_id=metric_id).first() if e else None
                pts.append(ev.value_number if ev else None)
            datasets.append({'label': metric.name, 'data': pts, 'tension': 0.3,
                             'spanGaps': True, 'borderColor': colors[0],
                             'backgroundColor': colors[0] + '22'})

        chart_data = {'labels': labels, 'datasets': datasets}

    all_branches = Branch.query.filter_by(is_active=True).order_by(Branch.sort_order).all()
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
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.sort_order).all()
    TYPES      = ['ONSITE', 'OFFSITE', 'VIRTUAL']
    AGE_GROUPS = ['0-5', '6-11', '12-18', '19+', 'General Interest']
    summary = outreach = None

    if year:
        cat = Category.query.filter_by(name='Branch Stats').first()
        if cat:
            all_metrics = {m.name: m for m in cat.metrics}
            q = Entry.query.filter_by(category_id=cat.id, year=year)
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
    years     = sorted(request.args.getlist('years', type=int))

    categories      = Category.query.filter_by(is_active=True).order_by(Category.sort_order).all()
    available_years = [r[0] for r in db.session.query(Entry.year).distinct().order_by(Entry.year).all()]
    metrics_json    = metrics_by_category_json()

    all_branches = Branch.query.filter_by(is_active=True).order_by(Branch.sort_order).all()
    table = col_headers = chart_data = category = metric = None

    if cat_id and len(years) >= 2:
        category = Category.query.get_or_404(cat_id)
        metrics  = Metric.query.filter_by(category_id=cat_id, is_active=True).order_by(Metric.sort_order).all()
        colors   = ['#2c6e8a','#e74c3c','#27ae60','#f39c12','#8e44ad','#16a085']

        def _entries(year):
            q = Entry.query.filter_by(category_id=cat_id, year=year)
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
            # totals[metric_id][year] = sum
            totals = {m.id: {} for m in metrics}
            for year in years:
                for e in _entries(year):
                    for ev in e.values:
                        if ev.value_number and ev.metric_id in totals:
                            totals[ev.metric_id][year] = totals[ev.metric_id].get(year, 0) + ev.value_number

            # Column headers: Year, [Δ year→year], Year, ...
            col_headers = []
            for j, y in enumerate(years):
                col_headers.append({'label': str(y), 'is_change': False})
                if j > 0:
                    col_headers.append({'label': f'Δ {years[j-1]}→{y}', 'is_change': True})

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

        elif mode == 'monthly' and metric_id:
            metric = Metric.query.get_or_404(metric_id)
            # monthly_data[month][year] = value
            monthly_data = {mo: {} for mo in range(1, 13)}
            for year in years:
                for e in _entries(year):
                    if e.month:
                        for ev in e.values:
                            if ev.metric_id == metric_id and ev.value_number is not None:
                                monthly_data[e.month][year] = ev.value_number

            # Chart
            labels   = [m[:3] for m in MONTHS]
            datasets = []
            for i, year in enumerate(years):
                pts = [monthly_data[mo].get(year) for mo in range(1, 13)]
                datasets.append({'label': str(year), 'data': pts, 'tension': 0.3,
                                 'spanGaps': True, 'borderColor': colors[i % len(colors)],
                                 'backgroundColor': colors[i % len(colors)] + '22'})
            chart_data = {'labels': labels, 'datasets': datasets}

            # Table: rows = months, cols = years + % change
            col_headers = []
            for j, y in enumerate(years):
                col_headers.append({'label': str(y), 'is_change': False})
                if j > 0:
                    col_headers.append({'label': f'Δ {years[j-1]}→{y}', 'is_change': True})

            table = []
            for mo in range(1, 13):
                cells = []
                for j, y in enumerate(years):
                    val  = monthly_data[mo].get(y)
                    cells.append({'val': _fmt(val) if val is not None else '—', 'is_change': False})
                    if j > 0:
                        prev = monthly_data[mo].get(years[j - 1])
                        cells.append({'val': _pct(prev, val) if (val and prev) else '—',
                                      'is_change': True,
                                      'up': val > prev if (val and prev) else None})
                table.append({'label': MONTHS[mo - 1], 'cells': cells})

    return render_template('reports/yearoveryear.html',
                           categories=categories, available_years=available_years,
                           metrics_json=metrics_json, all_branches=all_branches,
                           sel_cat=cat_id, sel_branch=branch_id, sel_metric=metric_id,
                           sel_mode=mode, sel_years=years,
                           category=category, metric=metric,
                           col_headers=col_headers, table=table, chart_data=chart_data)


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
    fy_set = set()
    for yr, mo, q in rows:
        if mo is not None:
            fy_set.add(yr + 1 if mo >= 7 else yr)
        if q is not None:
            fy_set.add(yr + 1 if q in (3, 4) else yr)
    available_fy = sorted(fy_set, reverse=True)

    table = branches = category = fy_label = None

    if cat_id and fy_year:
        category = Category.query.get_or_404(cat_id)
        metrics  = Metric.query.filter_by(category_id=cat_id, is_active=True).order_by(Metric.sort_order).all()
        fy_label = f'FY{fy_year}  (Jul {fy_year - 1} – Jun {fy_year})'

        # Monthly categories: months 7-12 of fy_year-1 and months 1-6 of fy_year
        # Quarterly categories: Q3+Q4 of fy_year-1 and Q1+Q2 of fy_year
        entries = Entry.query.filter_by(category_id=cat_id).filter(
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

    return render_template('reports/fiscal.html',
                           categories=categories, available_fy=available_fy,
                           sel_cat=cat_id, sel_fy=fy_year,
                           category=category, table=table, branches=branches,
                           fy_label=fy_label)


# ── Fiscal-year helper ────────────────────────────────────────────────────────

def _available_fy():
    """Sorted list of fiscal years (descending) derived from monthly entry data."""
    rows = db.session.query(Entry.year, Entry.month).filter(Entry.month.isnot(None)).distinct().all()
    fy_set = set()
    for yr, mo in rows:
        fy_set.add(yr + 1 if mo >= 7 else yr)
    return sorted(fy_set, reverse=True)


def _fy_label(fy_year):
    return f'FY{fy_year}  (Jul {fy_year - 1} – Jun {fy_year})'


# ── Branch Scorecard ─────────────────────────────────────────────────────────

@app.route('/reports/annual')
def report_annual():
    from sqlalchemy import or_, and_
    fy_year = request.args.get('fy_year', type=int)

    branches = Branch.query.filter_by(is_active=True, is_desk=False).order_by(Branch.sort_order).all()

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

            entries = Entry.query.filter_by(category_id=bs_cat.id).filter(
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


# ── Cross-tab Heat Map ────────────────────────────────────────────────────────

@app.route('/reports/crosstab')
def report_crosstab():
    from sqlalchemy import or_, and_
    cat_id    = request.args.get('category', type=int)
    metric_id = request.args.get('metric',   type=int)
    fy_year   = request.args.get('fy_year',  type=int)

    categories   = Category.query.filter_by(is_active=True).order_by(Category.sort_order).all()
    metrics_json = metrics_by_category_json()
    branches     = Branch.query.filter_by(is_active=True, is_desk=False).order_by(Branch.sort_order).all()

    # Fiscal year month order: Jul → Jun
    FY_MONTHS = list(range(7, 13)) + list(range(1, 7))

    table = metric = category = col_max = col_totals = None

    if cat_id and metric_id and fy_year:
        category = Category.query.get_or_404(cat_id)
        metric   = Metric.query.get_or_404(metric_id)

        cols = branches if category.has_branch else [None]

        data = {}  # (cal_year, month, branch_id_or_None) -> value
        for e in Entry.query.filter_by(category_id=cat_id).filter(
            or_(
                and_(Entry.year == fy_year - 1, Entry.month >= 7),
                and_(Entry.year == fy_year,     Entry.month <= 6)
            )
        ).filter(Entry.month.isnot(None)).all():
            bid = e.branch_id if category.has_branch else None
            for ev in e.values:
                if ev.metric_id == metric_id and ev.value_number is not None:
                    key = (e.year, e.month, bid)
                    data[key] = data.get(key, 0) + ev.value_number

        col_max = max(data.values(), default=1) or 1

        col_totals = []
        for col in cols:
            bid = col.id if col else None
            t = sum(
                data.get((fy_year - 1 if mo >= 7 else fy_year, mo, bid), 0)
                for mo in FY_MONTHS
            )
            col_totals.append(int(t) if t == int(t) else round(t, 1) if t else None)

        table = []
        for mo in FY_MONTHS:
            cal_year = fy_year - 1 if mo >= 7 else fy_year
            cells, row_sum = [], 0
            for col in cols:
                bid = col.id if col else None
                v = data.get((cal_year, mo, bid))
                cells.append(int(v) if v and v == int(v) else (round(v, 1) if v else None))
                if v:
                    row_sum += v
            table.append({
                'month_short': f"{MONTHS[mo - 1][:3]} '{str(cal_year)[2:]}",
                'cells': cells,
                'total': int(row_sum) if row_sum == int(row_sum) else round(row_sum, 1) if row_sum else None,
            })

    return render_template('reports/crosstab.html',
                           categories=categories,
                           available_fy=_available_fy(),
                           metrics_json=metrics_json,
                           branches=branches,
                           sel_cat=cat_id,
                           sel_metric=metric_id,
                           sel_fy=fy_year,
                           fy_label=_fy_label(fy_year) if fy_year else None,
                           category=category,
                           metric=metric,
                           table=table,
                           col_max=col_max,
                           col_totals=col_totals,
                           has_branch=category.has_branch if category else False)


# ── Programming Age / Delivery-Type Cross-tab ─────────────────────────────────

@app.route('/reports/programming_age')
def report_programming_age():
    from sqlalchemy import or_, and_
    fy_year = request.args.get('fy_year', type=int)
    month   = request.args.get('month',  type=int)
    mode    = request.args.get('mode', 'age')   # 'age' | 'type'

    branches = Branch.query.filter_by(is_active=True, is_desk=False).order_by(Branch.sort_order).all()
    TYPES = ['ONSITE', 'OFFSITE', 'VIRTUAL']
    AGES  = ['0-5', '6-11', '12-18', '19+', 'General Interest']
    tables = period_label = None

    if fy_year:
        bs_cat = Category.query.filter_by(name='Branch Stats').first()
        if bs_cat:
            id_to_name = {m.id: m.name for m in bs_cat.metrics}

            if month:
                # Single month within the fiscal year
                cal_year = fy_year - 1 if month >= 7 else fy_year
                q = Entry.query.filter_by(category_id=bs_cat.id, year=cal_year, month=month)
                period_label = f'{MONTHS[month - 1]} {cal_year}'
            else:
                # Full fiscal year
                q = Entry.query.filter_by(category_id=bs_cat.id).filter(
                    or_(
                        and_(Entry.year == fy_year - 1, Entry.month >= 7),
                        and_(Entry.year == fy_year,     Entry.month <= 6)
                    )
                )
                period_label = _fy_label(fy_year)

            branch_sums = {b.id: {} for b in branches}
            for e in q.all():
                if e.branch_id not in branch_sums:
                    continue
                for ev in e.values:
                    n = id_to_name.get(ev.metric_id)
                    if n and ev.value_number is not None:
                        branch_sums[e.branch_id][n] = branch_sums[e.branch_id].get(n, 0) + ev.value_number

            cols = AGES if mode == 'age' else TYPES

            def _build(kind):
                rows, col_totals = [], {c: 0 for c in cols}
                for b in branches:
                    sums = branch_sums[b.id]
                    cells, row_total = {}, 0
                    for c in cols:
                        if mode == 'age':
                            v = sum(sums.get(f'{t} {kind} {c}', 0) for t in TYPES)
                        else:
                            v = sum(sums.get(f'{c} {kind} {a}', 0) for a in AGES)
                        cells[c] = int(v) if v else None
                        row_total += v
                        col_totals[c] += v
                    rows.append({'branch': b, 'cells': cells, 'total': int(row_total) or None})
                return {
                    'kind': kind,
                    'cols': cols,
                    'rows': rows,
                    'col_totals': {c: int(col_totals[c]) or None for c in cols},
                    'grand_total': int(sum(col_totals.values())) or None,
                }

            tables = [_build('Sessions'), _build('Attendance')]

    return render_template('reports/programming_age.html',
                           available_fy=_available_fy(),
                           months=MONTHS,
                           sel_fy=fy_year,
                           sel_month=month,
                           sel_mode=mode,
                           period_label=period_label,
                           tables=tables)


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

@app.route('/upload', methods=['GET', 'POST'])
def upload_data():
    results = None
    if request.method == 'POST':
        f = request.files.get('file')
        if not f or not f.filename:
            flash('Please select a file to upload.', 'warning')
        else:
            import tempfile, openpyxl
            from import_excel import detect_and_import
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
                    f.save(tmp.name)
                    tmp_path = tmp.name
                wb = openpyxl.load_workbook(tmp_path, data_only=True)
                results = detect_and_import(wb)
                total_created = sum(r['created'] for r in results)
                flash(f'Upload complete — {total_created} new records added.', 'success')
            except Exception as e:
                flash(f'Upload failed: {e}', 'danger')
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)
    return render_template('upload.html', results=results)


# ── Manual staff entry ────────────────────────────────────────────────────────

# Metrics populated via file upload — excluded from the manual entry form
_UPLOAD_SOURCED_METRICS = {
    'New Library Card Registrations, Adult',
    'New Library Card Registrations, Juvenile',
    'Gate Count',
}


@app.route('/enter/manual', methods=['GET', 'POST'])
def manual_entry():
    branch_cat  = Category.query.filter_by(name='Branch Stats').first()
    online_cat  = Category.query.filter_by(name='Online Stats').first()

    branch_metrics = [m for m in (branch_cat.active_metrics if branch_cat else [])
                      if m.name not in _UPLOAD_SOURCED_METRICS]
    online_metrics = online_cat.active_metrics if online_cat else []

    # Main branches only — no lockers, no desk branches, no system-wide
    branches = (Branch.query
                .filter_by(is_active=True, is_desk=False)
                .filter(~Branch.name.contains('Lockers'),
                        Branch.name != 'YCL (System Wide)')
                .order_by(Branch.sort_order)
                .all())

    year  = request.args.get('year',  type=int) or datetime.now().year
    month = request.args.get('month', type=int) or datetime.now().month

    if request.method == 'POST':
        year          = request.form.get('year',  type=int)
        month         = request.form.get('month', type=int)
        submitted_by  = request.form.get('submitted_by', '').strip()

        # ── Branch Stats ──────────────────────────────────────────────────
        for branch in branches:
            vals = {}
            for m in branch_metrics:
                raw = request.form.get(f'b{branch.id}_m{m.id}', '').strip()
                if raw:
                    try:
                        vals[m.id] = float(raw)
                    except ValueError:
                        pass
            if not vals:
                continue

            entry = Entry.query.filter_by(category_id=branch_cat.id,
                                          branch_id=branch.id,
                                          year=year, month=month).first()
            if not entry:
                entry = Entry(category_id=branch_cat.id, branch_id=branch.id,
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

        # ── Online Stats ──────────────────────────────────────────────────
        online_vals = {}
        for m in online_metrics:
            raw = request.form.get(f'online_m{m.id}', '').strip()
            if raw:
                try:
                    online_vals[m.id] = float(raw)
                except ValueError:
                    pass

        if online_vals:
            o_entry = Entry.query.filter_by(category_id=online_cat.id,
                                             branch_id=None,
                                             year=year, month=month).first()
            if not o_entry:
                o_entry = Entry(category_id=online_cat.id, branch_id=None,
                                year=year, month=month, submitted_by=submitted_by)
                db.session.add(o_entry)
                db.session.flush()

            for metric_id, val in online_vals.items():
                ev = EntryValue.query.filter_by(entry_id=o_entry.id,
                                                metric_id=metric_id).first()
                if ev:
                    ev.value_number = val
                else:
                    db.session.add(EntryValue(entry_id=o_entry.id,
                                              metric_id=metric_id,
                                              value_number=val))

        db.session.commit()
        flash(f'Data saved for {MONTHS[month - 1]} {year}.', 'success')
        return redirect(url_for('manual_entry', year=year, month=month))

    # ── Load existing values for selected period ──────────────────────────
    branch_values = {}
    for branch in branches:
        entry = Entry.query.filter_by(category_id=branch_cat.id,
                                      branch_id=branch.id,
                                      year=year, month=month).first()
        branch_values[branch.id] = (
            {ev.metric_id: ev for ev in entry.values} if entry else {}
        )

    o_entry = Entry.query.filter_by(category_id=online_cat.id,
                                     branch_id=None,
                                     year=year, month=month).first()
    online_values = {ev.metric_id: ev for ev in o_entry.values} if o_entry else {}

    year_range = range(datetime.now().year - 5, datetime.now().year + 2)
    return render_template('entries/manual.html',
                           branches=branches,
                           branch_metrics=branch_metrics,
                           online_metrics=online_metrics,
                           branch_values=branch_values,
                           online_values=online_values,
                           year=year, month=month,
                           months=MONTHS,
                           year_range=year_range)


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
            entries = Entry.query.filter_by(category_id=cat.id, year=y, month=m).all()
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
    fy_set = set()
    for yr, mo, q in rows:
        if mo is not None:
            fy_set.add(yr + 1 if mo >= 7 else yr)
        if q is not None:
            fy_set.add(yr + 1 if q in (3, 4) else yr)
    available_fy = sorted(fy_set, reverse=True)

    fy_year = request.args.get('fy_year', type=int)
    stats = None

    if fy_year:
        def fy_filter(cat_name):
            cat = Category.query.filter_by(name=cat_name).first()
            if not cat:
                return {}
            entries = Entry.query.filter_by(category_id=cat.id).filter(
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
            for e in Entry.query.filter_by(category_id=cat.id, year=year).all():
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


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
