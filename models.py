from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80), unique=True, nullable=False)
    email         = db.Column(db.String(200), unique=True, nullable=True)
    password_hash = db.Column(db.String(256), nullable=False)
    is_active     = db.Column(db.Boolean, default=True, nullable=False)
    is_admin      = db.Column(db.Boolean, default=False, nullable=False)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True, nullable=False)
    description = db.Column(db.Text)
    frequency = db.Column(db.String(20), default='monthly')  # monthly, quarterly, annual
    has_branch = db.Column(db.Boolean, default=True)
    is_active = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    metrics = db.relationship('Metric', back_populates='category',
                               order_by='Metric.sort_order',
                               cascade='all, delete-orphan')
    entries = db.relationship('Entry', back_populates='category',
                               cascade='all, delete-orphan')

    @property
    def freq_label(self):
        return {'monthly': 'Monthly', 'quarterly': 'Quarterly', 'annual': 'Annual'}.get(
            self.frequency, self.frequency.capitalize())

    @property
    def active_metrics(self):
        return [m for m in self.metrics if m.is_active]

    _NAV_LABELS = {
        'Quarterly Reference Stats': 'Qrtly Ref Stats',
    }

    @property
    def nav_label(self):
        return self._NAV_LABELS.get(self.name, self.name)


class Metric(db.Model):
    __tablename__ = 'metrics'
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    group_name = db.Column(db.String(100), default='')
    data_type = db.Column(db.String(20), default='integer')  # integer, decimal, text
    is_required = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)

    category = db.relationship('Category', back_populates='metrics')
    values = db.relationship('EntryValue', back_populates='metric',
                              cascade='all, delete-orphan')


class Branch(db.Model):
    __tablename__ = 'branches'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    is_desk = db.Column(db.Boolean, default=False)  # desk-level branch (e.g. Rock Hill - Circ); excluded from Branch Stats
    sort_order = db.Column(db.Integer, default=0)

    entries = db.relationship('Entry', back_populates='branch')


class Entry(db.Model):
    __tablename__ = 'entries'
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=True)    # 1–12
    quarter = db.Column(db.Integer, nullable=True)  # 1–4
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    submitted_by = db.Column(db.String(200))
    notes = db.Column(db.Text)

    category = db.relationship('Category', back_populates='entries')
    branch = db.relationship('Branch', back_populates='entries')
    values = db.relationship('EntryValue', back_populates='entry',
                              cascade='all, delete-orphan')

    _MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
               'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

    @property
    def period_label(self):
        if self.month:
            return f"{self._MONTHS[self.month - 1]} {self.year}"
        if self.quarter:
            return f"Q{self.quarter} {self.year}"
        return str(self.year)

    @property
    def branch_label(self):
        return self.branch.name if self.branch else '(System-wide)'

    def add_source(self, source):
        """Merge a contributing source into submitted_by (e.g. 'SIRSI Import + admin')
        instead of overwriting it, so an entry populated by multiple imports/forms
        shows all of them rather than just whichever wrote it first or last."""
        if not source:
            return
        parts = [p.strip() for p in (self.submitted_by or '').split('+') if p.strip()]
        if source not in parts:
            parts.append(source)
        self.submitted_by = ' + '.join(parts)


class SirsiCheckout(db.Model):
    """Granular SIRSI ILS checkout data: one row per branch/patron-type/shelving-location/month."""
    __tablename__ = 'sirsi_checkouts'
    id                = db.Column(db.Integer, primary_key=True)
    year              = db.Column(db.Integer, nullable=False)
    month             = db.Column(db.Integer, nullable=False)   # 1–12
    branch_id         = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True)
    patron_type       = db.Column(db.String(50), nullable=True)
    shelving_location = db.Column(db.String(50), nullable=True)
    checkouts         = db.Column(db.Integer, default=0)
    renewals          = db.Column(db.Integer, default=0)

    branch = db.relationship('Branch')

    __table_args__ = (
        db.Index('ix_sirsi_period_branch', 'year', 'month', 'branch_id'),
    )


class ProgramEvent(db.Model):
    """One row per individual program occurrence, imported from the library's
    events system (Communico) export. Mirrors SirsiCheckout's role: a granular
    detail table that also drives a Branch Stats rollup (ONSITE/OFFSITE/VIRTUAL
    Sessions & Attendance by age group)."""
    __tablename__ = 'program_events'
    id                     = db.Column(db.Integer, primary_key=True)
    event_url              = db.Column(db.String(500), unique=True, nullable=False)
    year                   = db.Column(db.Integer, nullable=False)
    month                  = db.Column(db.Integer, nullable=False)
    event_date             = db.Column(db.Date, nullable=True)
    title                  = db.Column(db.String(500))
    age_group_raw          = db.Column(db.String(300))
    program_type           = db.Column(db.String(200))
    internal_categories    = db.Column(db.String(500))
    branch_id              = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True)
    room                   = db.Column(db.String(200))
    attendance             = db.Column(db.Integer, default=0)
    attendance_is_estimate = db.Column(db.Boolean, default=False)  # True = fell back to Expected Attendance
    location_mode          = db.Column(db.String(20))   # ONSITE / OFFSITE / VIRTUAL
    age_bucket             = db.Column(db.String(30))   # 0-5 / 6-11 / 12-18 / 19+ / General Interest
    created_at             = db.Column(db.DateTime, default=datetime.utcnow)

    branch = db.relationship('Branch')

    __table_args__ = (
        db.Index('ix_program_events_period_branch', 'year', 'month', 'branch_id'),
    )


class AnnualSurveyMetric(db.Model):
    """Defines a metric tracked in the annual SC State Library survey report."""
    __tablename__ = 'annual_survey_metrics'
    id              = db.Column(db.Integer, primary_key=True)
    section         = db.Column(db.String(100), nullable=False)   # matches sheet name
    name            = db.Column(db.String(500), nullable=False)
    data_type       = db.Column(db.String(20), default='integer')  # integer, decimal, text
    sort_order      = db.Column(db.Integer, default=0)
    is_auto_calculated = db.Column(db.Boolean, default=False)
    auto_calc_note  = db.Column(db.String(300))  # human-readable description of the source

    values = db.relationship('AnnualSurveyValue', back_populates='metric',
                              cascade='all, delete-orphan')


class AnnualSurveyValue(db.Model):
    """One value per metric per fiscal year (report_year = FY end year)."""
    __tablename__ = 'annual_survey_values'
    id            = db.Column(db.Integer, primary_key=True)
    report_year   = db.Column(db.Integer, nullable=False)
    metric_id     = db.Column(db.Integer, db.ForeignKey('annual_survey_metrics.id'), nullable=False)
    value         = db.Column(db.Float, nullable=True)
    value_text    = db.Column(db.Text, nullable=True)
    is_adjusted   = db.Column(db.Boolean, default=False)
    adjustment_note = db.Column(db.Text)

    metric = db.relationship('AnnualSurveyMetric', back_populates='values')

    __table_args__ = (
        db.UniqueConstraint('report_year', 'metric_id', name='uq_annual_year_metric'),
    )

    @property
    def display_value(self):
        if self.metric.data_type == 'text':
            return self.value_text or '—'
        if self.value is None:
            return '—'
        if self.value == int(self.value):
            return f'{int(self.value):,}'
        return f'{self.value:,.2f}'.rstrip('0').rstrip('.')


class QuarterlyRefClosureDays(db.Model):
    """Saved closure-days configuration per year for the Quarterly Reference Stats report."""
    __tablename__ = 'quarterly_ref_closure_days'
    id         = db.Column(db.Integer, primary_key=True)
    year       = db.Column(db.Integer, nullable=False, unique=True)
    holidays   = db.Column(db.Integer, default=0, nullable=False)
    unexpected = db.Column(db.Integer, default=0, nullable=False)
    saved_by   = db.Column(db.String(200))
    saved_at   = db.Column(db.DateTime, default=datetime.utcnow)


class BranchClosure(db.Model):
    """One non-holiday closure instance for a branch: a specific date and hours closed."""
    __tablename__ = 'branch_closures'
    id           = db.Column(db.Integer, primary_key=True)
    branch_id    = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False)
    closure_date = db.Column(db.Date, nullable=False)
    hours_closed = db.Column(db.Float, nullable=False)
    submitted_by = db.Column(db.String(200))
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    branch = db.relationship('Branch')

    __table_args__ = (
        db.Index('ix_branch_closures_branch_date', 'branch_id', 'closure_date'),
    )

    @property
    def display_hours(self):
        if self.hours_closed == int(self.hours_closed):
            return str(int(self.hours_closed))
        return f'{self.hours_closed:.2f}'.rstrip('0').rstrip('.')


class HolidayClosure(db.Model):
    """One date on the official, system-wide holiday closure calendar.

    Full-day closures (is_full_day=True) cost each branch that branch's own normal
    hours for that weekday (looked up from BranchWeeklyHours) — branches with
    different Fri/Sat schedules lose different amounts of time on the same date.
    Partial closures (is_full_day=False, e.g. an early-closing day) use the flat
    hours_closed value, applied the same to every branch.
    """
    __tablename__ = 'holiday_closures'
    id           = db.Column(db.Integer, primary_key=True)
    closure_date = db.Column(db.Date, nullable=False, unique=True)
    name         = db.Column(db.String(200), nullable=False)
    is_full_day  = db.Column(db.Boolean, nullable=False, default=True)
    hours_closed = db.Column(db.Float, nullable=True)  # only used when is_full_day is False
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def display_hours(self):
        if self.is_full_day:
            return 'Full day'
        if self.hours_closed == int(self.hours_closed):
            return f'{int(self.hours_closed)} hrs (partial)'
        return f'{self.hours_closed:.2f} hrs (partial)'.rstrip('0').rstrip('.')


class BranchWeeklyHours(db.Model):
    """A branch's normal weekly service hours, one value per weekday.

    Used to compute (a) a default annual Scheduled Hours suggestion (weekly total x 52)
    and (b) the actual hours lost to each full-day HolidayClosure, since branches can
    have different Friday/Saturday hours.
    """
    __tablename__ = 'branch_weekly_hours'
    id        = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, unique=True)
    monday    = db.Column(db.Float, nullable=False, default=0)
    tuesday   = db.Column(db.Float, nullable=False, default=0)
    wednesday = db.Column(db.Float, nullable=False, default=0)
    thursday  = db.Column(db.Float, nullable=False, default=0)
    friday    = db.Column(db.Float, nullable=False, default=0)
    saturday  = db.Column(db.Float, nullable=False, default=0)
    sunday    = db.Column(db.Float, nullable=False, default=0)

    branch = db.relationship('Branch')

    _DAY_COLS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']

    def hours_for_weekday(self, weekday):
        """weekday: 0=Monday ... 6=Sunday, matching Python's date.weekday()."""
        return getattr(self, self._DAY_COLS[weekday])

    @property
    def weekly_total(self):
        return sum(getattr(self, c) for c in self._DAY_COLS)


class OutletScheduledHours(db.Model):
    """A branch's normal/baseline annual open hours for one fiscal year (Section J baseline)."""
    __tablename__ = 'outlet_scheduled_hours'
    id              = db.Column(db.Integer, primary_key=True)
    branch_id       = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False)
    fiscal_year     = db.Column(db.Integer, nullable=False)
    scheduled_hours = db.Column(db.Float, nullable=False)
    submitted_by    = db.Column(db.String(200))
    submitted_at    = db.Column(db.DateTime, default=datetime.utcnow)

    branch = db.relationship('Branch')

    __table_args__ = (
        db.UniqueConstraint('branch_id', 'fiscal_year', name='uq_outlet_hours_branch_fy'),
    )


class SectionJOutletData(db.Model):
    """Saved Section J (Hours/Weeks Open) result for one branch/fiscal year."""
    __tablename__ = 'section_j_outlet_data'
    id          = db.Column(db.Integer, primary_key=True)
    branch_id   = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False)
    fiscal_year = db.Column(db.Integer, nullable=False)
    hours_open  = db.Column(db.Float, nullable=False)
    weeks_open  = db.Column(db.Float, nullable=False, default=52)
    saved_by    = db.Column(db.String(200))
    saved_at    = db.Column(db.DateTime, default=datetime.utcnow)

    branch = db.relationship('Branch')

    __table_args__ = (
        db.UniqueConstraint('branch_id', 'fiscal_year', name='uq_section_j_branch_fy'),
    )


class ImportLog(db.Model):
    """Records each file upload so it can be undone."""
    __tablename__ = 'import_logs'
    id            = db.Column(db.Integer, primary_key=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    file_name     = db.Column(db.String(255))
    import_type   = db.Column(db.String(500))
    year          = db.Column(db.Integer, nullable=True)
    month         = db.Column(db.Integer, nullable=True)
    rows_affected = db.Column(db.Integer, default=0)
    undone_at     = db.Column(db.DateTime, nullable=True)
    changes_json  = db.Column(db.Text)

    @property
    def can_undo(self):
        return self.undone_at is None and self.changes_json is not None


class EresourceDatabase(db.Model):
    """A subscription database staff log monthly usage for (EBSCO, Hoopla, Kanopy, etc.).

    Part of Monthly eResources — see CLAUDE.md and eResources/ for how this
    differs from the Annual eResources category (Category/Metric/Entry-based,
    reported once a year). Monthly eResources has its own tables since the
    data has a different shape: one usage number per database per month.
    """
    __tablename__ = 'databases'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True, nullable=False)
    vendor = db.Column(db.String(200))
    # Which Annual eResources bucket this database's usage rolls up into —
    # see eResources/YCL-Vendor-Data-Onboarding-Plan.md §3a for the crosswalk.
    bucket = db.Column(db.String(20))  # ebook, eaudio, evideo, eserial
    is_active = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)

    usage = db.relationship('UsageMonthly', back_populates='database',
                             cascade='all, delete-orphan')


class UsageMonthly(db.Model):
    """One row per database per month: the hand-entered usage number from the vendor's site."""
    __tablename__ = 'usage_monthly'
    id = db.Column(db.Integer, primary_key=True)
    database_id = db.Column(db.Integer, db.ForeignKey('databases.id'), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)  # 1–12
    usage_count = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.Text)

    database = db.relationship('EresourceDatabase', back_populates='usage')

    __table_args__ = (
        db.UniqueConstraint('database_id', 'year', 'month', name='uq_usage_monthly_db_period'),
        db.Index('ix_usage_monthly_period', 'year', 'month'),
    )


class EntryValue(db.Model):
    __tablename__ = 'entry_values'
    id = db.Column(db.Integer, primary_key=True)
    entry_id = db.Column(db.Integer, db.ForeignKey('entries.id'), nullable=False)
    metric_id = db.Column(db.Integer, db.ForeignKey('metrics.id'), nullable=False)
    value_number = db.Column(db.Float, nullable=True)
    value_text = db.Column(db.Text, nullable=True)

    entry = db.relationship('Entry', back_populates='values')
    metric = db.relationship('Metric', back_populates='values')

    @property
    def display_value(self):
        if self.metric.data_type == 'text':
            return self.value_text or ''
        if self.value_number is None:
            return ''
        if self.value_number == int(self.value_number):
            return str(int(self.value_number))
        return f"{self.value_number:.2f}".rstrip('0').rstrip('.')
