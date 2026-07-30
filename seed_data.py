from models import Category, Metric, Branch, EresourceDatabase


def seed(db):
    branches = [
        'Rock Hill', 'Clover', 'Fort Mill', 'Lake Wylie', 'York',
        'Bookmobile/Outreach', 'YCL (System Wide)',
        'Rock Hill - Circulation', 'Rock Hill - Reference', 'Rock Hill - YA',
        'Outreach / BKM',
    ]
    for i, name in enumerate(branches):
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
        ('Gate Count',                                       'Access & Usage',      'integer'),
        ('PC Reservations',                                  'Access & Usage',      'integer'),
        ('WiFi - Unique Sessions',                           'Access & Usage',      'integer'),
        ('External Party Library Room Use',                  'Access & Usage',      'integer'),
        ('Total Prints per Month',                           'Access & Usage',      'integer'),
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

    # ── Category 2: eResources ──────────────────────────────────────────────
    c2 = Category(name='eResources',
                  description='Monthly electronic resource circulation statistics (system-wide)',
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
        ('DigitalLearn.org - Sessions',           'DigitalLearn',         'integer'),
        ('DigitalLearn.org - Completed Courses',  'DigitalLearn',         'integer'),
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


def seed_eresource_databases(db):
    """Monthly eResources: one row per vendor/metric combination we track from the
    monthly usage spreadsheet. `bucket` marks which of the four Annual eResources
    totals (ebook, eaudio, evideo, eserial) this metric rolls up into, per the
    workbook's own 'eResource Type Breakdown' sheet — None means not counted for
    the state report, tracked for internal reference only.

    Decided with the library director walking through each vendor tab in
    'Monthly Stats 2025-2026.xlsx' (2026-07-30). Source sheet/column for each
    entry is recorded here as a comment for the eventual import script.
    """
    entries = [
        # (name, vendor, bucket)
        # ABC Mouse — sheet 'ABC Mouse'
        ('ABC Mouse - Learning Activities', 'ABC Mouse', 'evideo'),      # col: Learning Activities
        ('ABC Mouse - Visits',              'ABC Mouse', None),         # col: Visits

        # Ask a Librarian — sheet 'Ask a Librarian'
        ('Ask a Librarian - Questions', 'Ask a Librarian', None),       # col: Questions

        # BiblioBoard — sheet 'BiblioBoard'
        ('BiblioBoard - Successful Requests', 'BiblioBoard', 'ebook'),  # col: Successful Requests
        ('BiblioBoard - Sessions',            'BiblioBoard', None),     # col: Sessions

        # Brainfuse — sheet 'Brainfuse'
        ('Brainfuse - Skill Surfer Usage', 'Brainfuse', 'evideo'),      # col: Skill Surfer Usage
        ('Brainfuse - Sessions',           'Brainfuse', None),          # col: Sessions
        ('Brainfuse - Tutoring Sessions',  'Brainfuse', None),          # col: Tutoring Sessions

        # Data Axle / Reference USA — sheet 'Data AxleReference USA'
        ('Data Axle/Reference USA - Downloads',         'Data Axle/Reference USA', 'ebook'),  # col: Downloads
        ('Data Axle/Reference USA - Sessions (Logins)', 'Data Axle/Reference USA', None),      # col: Sessions (Logins)
        ('Data Axle/Reference USA - Searches',          'Data Axle/Reference USA', None),      # col: Searches

        # DigitalLearn — sheet 'DigitalLearn'
        ('DigitalLearn - Sessions',           'DigitalLearn', None),    # col: Sessions
        ('DigitalLearn - Completed Courses',  'DigitalLearn', None),    # col: Completed Courses

        # EBSCO Flipster — sheet 'EBSCO Flipster'
        ('EBSCO Flipster - Online Views', 'EBSCO Flipster', 'eserial'), # col: Online Views
        ('EBSCO Flipster - Searches',     'EBSCO Flipster', None),      # col: Searches
        ('EBSCO Flipster - Downloads',    'EBSCO Flipster', None),      # col: Downloads

        # Gale eBooks — sheet 'Gale Ebooks' (not counted for state report)
        ('Gale eBooks - Sessions',    'Gale eBooks', None),             # col: Sessions
        ('Gale eBooks - Searches',    'Gale eBooks', None),             # col: Searches
        ('Gale eBooks - Retrievals',  'Gale eBooks', None),             # col: Retrievals

        # Gale Presents Udemy — sheet 'Gale Presents Udemy'
        ('Gale Presents Udemy - Courses Started',   'Gale Presents Udemy', 'evideo'),  # col: Courses Started
        ('Gale Presents Udemy - Active Users',      'Gale Presents Udemy', None),      # col: Active Users
        ('Gale Presents Udemy - Courses Enrolled',  'Gale Presents Udemy', None),      # col: Courses Enrolled
        ('Gale Presents Udemy - Courses Completed', 'Gale Presents Udemy', None),      # col: Courses Completed

        # Infobase: The Mailbox — sheet 'Infobase The Mailbox'
        ('Infobase: The Mailbox - Printable Downloads', 'Infobase: The Mailbox', 'eserial'),  # col: Printable Downloads
        ('Infobase: The Mailbox - Sessions',            'Infobase: The Mailbox', None),       # col: Sessions
        ('Infobase: The Mailbox - Searches',            'Infobase: The Mailbox', None),       # col: Searches

        # Kanopy — sheet 'Kanopy'
        ('Kanopy - Plays',          'Kanopy', 'evideo'),  # col: Plays
        ('Kanopy - Visits/Sessions', 'Kanopy', None),      # col: Visits/Sessions

        # LibraryAware Newsletters — sheet 'LibraryAware Newsletters'
        ('LibraryAware Newsletters - Unique Opens',        'LibraryAware Newsletters', None),  # col: Unique Opens
        ('LibraryAware Newsletters - Current Subscribers', 'LibraryAware Newsletters', None),  # col: Current Subscribers

        # Lote4Kids — sheet 'Lote4Kids'
        ('Lote4Kids - Stories Watched', 'Lote4Kids', 'evideo'),  # col: Stories Watched
        ('Lote4Kids - Activities',      'Lote4Kids', None),      # col: Activities
        ('Lote4Kids - Logins',          'Lote4Kids', None),      # col: Logins

        # Mango — sheet 'Mango'
        ('Mango - Total Uses',      'Mango', 'evideo'),  # col: Total Uses
        ('Mango - Sessions',        'Mango', None),       # col: Sessions
        ('Mango - Little Pim Uses', 'Mango', None),        # col: Little Pim Uses

        # Newsbank — sheet 'Newsbank'
        ('Newsbank - Documents Viewed', 'Newsbank', 'eserial'),  # col: Documents Viewed
        ('Newsbank - Logins',           'Newsbank', None),       # col: Logins
        ('Newsbank - Searches',         'Newsbank', None),       # col: Searches

        # Salem Press — sheet 'Salem Press' (not counted for state report)
        ('Salem Press - Regular Search', 'Salem Press', None),  # col: Regular Search
        ('Salem Press - Result Click',   'Salem Press', None),  # col: Result Click

        # Tutor.com — sheet 'Tutor.com' (not counted for state report)
        ('Tutor.com - Sessions',            'Tutor.com', None),  # col: Sessions
        ('Tutor.com - Past Session Views',  'Tutor.com', None),  # col: Past Session Views

        # Value Line — sheet 'Value Line'
        ('Value Line - Downloads', 'Value Line', 'eserial'),  # col: Downloads
        ('Value Line - Logins',    'Value Line', None),       # col: Logins

        # Weiss Financial Services — sheet 'Weiss Financial Services' (not counted for state report)
        ('Weiss Financial Services - Sessions', 'Weiss Financial Services', None),  # col: Sessions
        ('Weiss Financial Services - Searches', 'Weiss Financial Services', None),  # col: Searches
        ('Weiss Financial Services - Users',    'Weiss Financial Services', None),  # col: Users

        # Proquest: Ancestry Library Edition — sheet 'Proquest Ancestry Library Editi' (not counted)
        ('Proquest: Ancestry Library Edition - Sessions', 'Proquest: Ancestry Library Edition', None),  # col: Sessions
        ('Proquest: Ancestry Library Edition - Searches', 'Proquest: Ancestry Library Edition', None),  # col: Searches

        # Proquest: Fold3 — sheet 'Proquest Fold3' (not counted)
        ('Proquest: Fold3 - Searches',       'Proquest: Fold3', None),  # col: Searches
        ('Proquest: Fold3 - Item Requests',  'Proquest: Fold3', None),  # col: Item Requests

        # Proquest: HeritageQuest — sheet 'Proquest HeritageQuest' (not counted)
        ('Proquest: HeritageQuest - Sessions', 'Proquest: HeritageQuest', None),  # col: Sessions

        # Hoopla — sheet 'Midwest Tapehoopla'; one row per content type so bucket
        # roll-ups stay accurate (one vendor tab feeds all four state buckets)
        ('Hoopla - eBooks Instant', 'Hoopla', 'ebook'),   # col: Ebook Instant
        ('Hoopla - eBooks Flex',    'Hoopla', 'ebook'),   # col: Ebook Flex (2.0)
        ('Hoopla - Comics',        'Hoopla', 'ebook'),    # col: Comics
        ('Hoopla - eAudio Instant', 'Hoopla', 'eaudio'),  # col: Audio Instant
        ('Hoopla - eAudio Flex',    'Hoopla', 'eaudio'),  # col: Audio Flex (2.0)
        ('Hoopla - Music',          'Hoopla', 'eaudio'),  # col: Music
        ('Hoopla - TV',             'Hoopla', 'evideo'),  # col: TV
        ('Hoopla - Movies',         'Hoopla', 'evideo'),  # col: Movies
        # BingePasses' annual state total is split 4 ways by hand from a separate
        # Hoopla report; the monthly tab only has one combined column, so no
        # bucket is set here — the annual split stays a once-a-year manual entry.
        ('Hoopla - BingePasses', 'Hoopla', None),  # col: BingePasses

        # Overdrive/Libby — sheet 'OverdriveLibby', Libby side
        ('Overdrive/Libby - eBooks',     'Overdrive/Libby', 'ebook'),    # col: E-Book (Libby)
        ('Overdrive/Libby - eAudio',     'Overdrive/Libby', 'eaudio'),   # col: E-Audio (Libby)
        ('Overdrive/Libby - Streaming',  'Overdrive/Libby', 'evideo'),  # col: Streaming (Libby)
        ('Overdrive/Libby - Magazines',  'Overdrive/Libby', 'eserial'),  # col: Magazines (Libby)
        # Sora side — same vendor, separate app; not counted for the state report
        ('Sora - Total', 'Overdrive/Libby', None),  # col: Total (Sora)

        # DISCUS — sheet 'DISCUS'; 19 state-provided databases, currently blank
        # in the workbook. Seeded inactive until staff start entering data.
        # Planned metric once populated: Views / Hits.
    ]

    discus_databases = [
        'Britannica', 'CultureGrams', 'EBSCO (DISCUS)', 'Candid: Foundation Directory',
        'Gale: Biography in Context', 'Gale: Chilton Library', 'Gale: Elementary',
        'Gale: Opposing Viewpoints Resource Center', 'Infobase: African American History',
        "Infobase: Bloom's Literature", 'Infobase: Credo Reference',
        "Infobase: Ferguson's Career Guidance Center", 'Infobase: World Almanac for Kids',
        'Infobase: World Almanac for Kids Elementary', 'Infobase: Writers Reference Center',
        'LearningExpress 3.0', 'PebbleGO', 'TeachingBooks', 'Tumblebooks',
    ]

    for i, (name, vendor, bucket) in enumerate(entries):
        db.session.add(EresourceDatabase(name=name, vendor=vendor, bucket=bucket,
                                          is_active=True, sort_order=i + 1))

    offset = len(entries)
    for i, name in enumerate(discus_databases):
        db.session.add(EresourceDatabase(name=f'DISCUS - {name}', vendor='DISCUS', bucket=None,
                                          is_active=False, sort_order=offset + i + 1))

    db.session.commit()
    print(f"Seeded {len(entries) + len(discus_databases)} eResource databases "
          f"({len(discus_databases)} DISCUS entries inactive, pending data).")
