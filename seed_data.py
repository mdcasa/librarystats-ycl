from models import Category, Metric, Branch


def seed(db):
    branches = [
        'Rock Hill', 'Clover', 'Fort Mill', 'Lake Wylie', 'York',
        'Bookmobile/Outreach', 'YCL (System Wide)',
        "Rock Hill - Children's", 'Rock Hill - Circulation', 'Rock Hill - Reference', 'Rock Hill - YA',
        'Outreach / BKM',
    ]
    for i, name in enumerate(branches):
        if not Branch.query.filter_by(name=name).first():
            db.session.add(Branch(name=name, sort_order=i + 1))

    # ── Category 1: Branch Stats ────────────────────────────────────────────
    c1 = Category(name='Branch Stats',
                  description='Monthly statistics collected per branch location',
                  frequency='monthly', has_branch=True, sort_order=1)
    db.session.add(c1)
    db.session.flush()

    branch_metrics = [
        # (name, group_name, data_type)
        ('New Library Card Registrations, Adult',           'Registrations',       'integer'),
        ('New Library Card Registrations, Juvenile',        'Registrations',       'integer'),
        ('New Library Card Registrations, Total',           'Registrations',       'integer'),
        ('Gate Count',                                       'Access & Usage',      'integer'),
        ('PC Reservations',                                  'Access & Usage',      'integer'),
        ('WiFi - Unique Sessions',                           'Access & Usage',      'integer'),
        ('External Party Library Room Use',                  'Access & Usage',      'integer'),
        ('Total Prints per Month',                           'Access & Usage',      'integer'),
        ('Printed Jobs',                                     'Access & Usage',      'integer'),
        ('Printed Cost',                                     'Access & Usage',      'decimal'),
        ('Total Branch Circulation',                         'Circulation',         'integer'),
        ('Hotspots Circulation',                             'Circulation',         'integer'),
        ('Curbside',                                         'Circulation',         'integer'),
        ('Locker Circulation',                               'Circulation',         'integer'),
        ('ILL - Sent (Main ONLY)',                           'ILL / ICL',           'integer'),
        ('ILL - Received (Main ONLY)',                       'ILL / ICL',           'integer'),
        ('ICLs - Sent (Main ONLY)',                          'ILL / ICL',           'integer'),
        ('ICLs - Received (Main ONLY)',                      'ILL / ICL',           'integer'),
        ('ONSITE Sessions 0-5',                              'ONSITE Programming',  'integer'),
        ('ONSITE Sessions 6-11',                             'ONSITE Programming',  'integer'),
        ('ONSITE Sessions 12-18',                            'ONSITE Programming',  'integer'),
        ('ONSITE Sessions 19+',                              'ONSITE Programming',  'integer'),
        ('ONSITE Sessions General Interest',                 'ONSITE Programming',  'integer'),
        ('ONSITE Attendance 0-5',                            'ONSITE Programming',  'integer'),
        ('ONSITE Attendance 6-11',                           'ONSITE Programming',  'integer'),
        ('ONSITE Attendance 12-18',                          'ONSITE Programming',  'integer'),
        ('ONSITE Attendance 19+',                            'ONSITE Programming',  'integer'),
        ('ONSITE Attendance General Interest',               'ONSITE Programming',  'integer'),
        ('OFFSITE Sessions 0-5',                             'OFFSITE Programming', 'integer'),
        ('OFFSITE Sessions 6-11',                            'OFFSITE Programming', 'integer'),
        ('OFFSITE Sessions 12-18',                           'OFFSITE Programming', 'integer'),
        ('OFFSITE Sessions 19+',                             'OFFSITE Programming', 'integer'),
        ('OFFSITE Sessions General Interest',                'OFFSITE Programming', 'integer'),
        ('OFFSITE Attendance 0-5',                           'OFFSITE Programming', 'integer'),
        ('OFFSITE Attendance 6-11',                          'OFFSITE Programming', 'integer'),
        ('OFFSITE Attendance 12-18',                         'OFFSITE Programming', 'integer'),
        ('OFFSITE Attendance 19+',                           'OFFSITE Programming', 'integer'),
        ('OFFSITE Attendance General Interest',              'OFFSITE Programming', 'integer'),
        ('VIRTUAL Sessions 0-5',                             'VIRTUAL Programming', 'integer'),
        ('VIRTUAL Sessions 6-11',                            'VIRTUAL Programming', 'integer'),
        ('VIRTUAL Sessions 12-18',                           'VIRTUAL Programming', 'integer'),
        ('VIRTUAL Sessions 19+',                             'VIRTUAL Programming', 'integer'),
        ('VIRTUAL Sessions General Interest',                'VIRTUAL Programming', 'integer'),
        ('VIRTUAL Attendance 0-5',                           'VIRTUAL Programming', 'integer'),
        ('VIRTUAL Attendance 6-11',                          'VIRTUAL Programming', 'integer'),
        ('VIRTUAL Attendance 12-18',                         'VIRTUAL Programming', 'integer'),
        ('VIRTUAL Attendance 19+',                           'VIRTUAL Programming', 'integer'),
        ('VIRTUAL Attendance General Interest',              'VIRTUAL Programming', 'integer'),
        ('Number of Outreach Activities Conducted',          'Outreach',            'integer'),
        ('Outreach Attendance',                              'Outreach',            'integer'),
        ('Take & Makes / Other Passive Program Participants','Outreach',            'integer'),
        ('Number of Staff Taking Training',                  'Staff Training',      'integer'),
        ('Number of Hours Staff Attended Training',          'Staff Training',      'decimal'),
        ('1-on-1 Total for Month',                           'Other',               'integer'),
    ]
    for i, (name, group, dtype) in enumerate(branch_metrics):
        db.session.add(Metric(category_id=c1.id, name=name,
                               group_name=group, data_type=dtype, sort_order=i + 1))

    # ── Category 2: Annual eResources ───────────────────────────────────────
    c2 = Category(name='Annual eResources',
                  description='Annual electronic resource circulation statistics (system-wide)',
                  frequency='monthly', has_branch=False, sort_order=2)
    db.session.add(c2)
    db.session.flush()

    for i, name in enumerate(['E-Book Circulation', 'E-Audio Circulation',
                               'E-Video Circulation', 'E-Serials Circulation']):
        db.session.add(Metric(category_id=c2.id, name=name,
                               group_name='Circulation', data_type='integer', sort_order=i + 1))

    # ── Category 3: Online Stats ────────────────────────────────────────────
    c3 = Category(name='Online Stats',
                  description='Monthly website and digital platform statistics (system-wide)',
                  frequency='monthly', has_branch=False, sort_order=3)
    db.session.add(c3)
    db.session.flush()

    online_metrics = [
        ('yclibrary.org - Web Sessions',         'Website',              'integer'),
        ('ychistory.org - Views',                 'Website',              'integer'),
        ('patchworktales.org - Views',            'Website',              'integer'),
        ('Dial A Story - Calls',                  'Dial A Story',         'integer'),
        ('Dial A Story - Views',                  'Dial A Story',         'integer'),
        ('Dial A Story Uploads',                  'Dial A Story',         'integer'),
        ('DSpace - Views',                        'Other Platforms',      'integer'),
        ('Beanstack - Sessions',                  'Other Platforms',      'integer'),
        ('LibraryCalendar - Sessions',            'Other Platforms',      'integer'),
        ('LibGuides - Sessions',                  'Other Platforms',      'integer'),
        ('LOTE4Kids - Stories Watched',           'LOTE4Kids',            'integer'),
        ('LOTE4Kids - Activities',                'LOTE4Kids',            'integer'),
        ('LOTE4Kids - Logins',                    'LOTE4Kids',            'integer'),
        ('YouTube - Subscribers',                 'Social Media',         'integer'),
        ('YouTube - Views',                       'Social Media',         'integer'),
        ('YouTube - Hours Watched',               'Social Media',         'decimal'),
        ('YouTube Uploads',                       'Social Media',         'integer'),
        ('Facebook Followers',                    'Social Media',         'integer'),
        ('Instagram - Subscribers',               'Social Media',         'integer'),
        ('YCL News - Subscribers',                'Newsletters & Apps',   'integer'),
        ('Website Messages',                      'Newsletters & Apps',   'integer'),
        ('YCL App - Users',                       'Newsletters & Apps',   'integer'),
        ('YCL App - Sessions',                    'Newsletters & Apps',   'integer'),
    ]
    for i, (name, group, dtype) in enumerate(online_metrics):
        db.session.add(Metric(category_id=c3.id, name=name,
                               group_name=group, data_type=dtype, sort_order=i + 1))

    # ── Category 4: Quarterly Reference Stats ───────────────────────────────
    c4 = Category(name='Quarterly Reference Stats',
                  description='Quarterly reference transaction counts per branch',
                  frequency='quarterly', has_branch=True, sort_order=4)
    db.session.add(c4)
    db.session.flush()

    db.session.add(Metric(category_id=c4.id, name='Total Transactions for the Week',
                           group_name='', data_type='integer', sort_order=1))

    db.session.commit()
    print("Database seeded with initial categories, metrics, and branches.")
