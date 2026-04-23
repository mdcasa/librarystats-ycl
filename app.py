from flask import Flask, render_template, request, redirect, url_for, flash
from models import db, Category, Metric, Branch, Entry, EntryValue
from datetime import datetime
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

MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
          'July', 'August', 'September', 'October', 'November', 'December']


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
    recent = Entry.query.order_by(Entry.submitted_at.desc()).limit(10).all()
    return render_template('index.html',
                           recent_entries=recent,
                           total_entries=Entry.query.count(),
                           total_categories=Category.query.filter_by(is_active=True).count(),
                           total_branches=Branch.query.filter_by(is_active=True).count())


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

@app.route('/entries/new/<int:category_id>', methods=['GET', 'POST'])
def entry_create(category_id):
    category = Category.query.get_or_404(category_id)
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.sort_order).all()
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
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.sort_order).all()
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


# ── Startup ───────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        if Category.query.count() == 0:
            from seed_data import seed
            seed(db)
    app.run(debug=True, host='0.0.0.0', port=5000)
