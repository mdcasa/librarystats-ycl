from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


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
