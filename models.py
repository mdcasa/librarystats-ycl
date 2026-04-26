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
