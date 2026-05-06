from dotenv import load_dotenv
load_dotenv()
from app import app, db
from models import User

with app.app_context():
    with app.test_client() as c:
        u = User.query.first()
        with c.session_transaction() as sess:
            sess['_user_id'] = str(u.id)
            sess['_fresh'] = True
        r = c.get('/reports/monthlystats?month=4&year=2026')
        print('Status:', r.status_code)
        if r.status_code == 200:
            import re
            html = r.data.decode()
            titles = re.findall(r'(ONSITE Program \w+|OFFSITE Program \w+|VIRTUAL Program|Circulation|Social Media|Technology|New Library)', html)
            from collections import Counter
            print('Sections found:', Counter(titles))
        else:
            print(r.data[:800].decode())
