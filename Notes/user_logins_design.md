# User Accounts — Design Notes

## Overview

YCL Statistics uses individual user accounts (implemented in v4). Each staff member has their own login. There is no self-registration — an admin creates all accounts through the Admin → Users interface.

Prior to v4, the app used a single shared username/password stored in environment variables. The transition is seamless: on first boot with v4, the `users` table is empty and the system automatically creates a default admin account from the existing `LOGIN_USERNAME` / `LOGIN_PASSWORD` environment variables. Staff log in with the same credentials as before; the admin then creates individual accounts and retires the shared login.

---

## Dependencies

| Package | Purpose |
|---|---|
| `Flask-Login` ≥ 0.6.3 | Session management, `current_user` proxy, `login_required` |
| `werkzeug.security` | Password hashing (`generate_password_hash`, `check_password_hash`) — included with Flask, no extra install |

Added to `requirements.txt`: `Flask-Login>=0.6.3`

---

## Data Model

### `users` table

| Field | Type | Notes |
|---|---|---|
| `id` | integer | PK |
| `username` | string(80) | Unique, required |
| `email` | string(200) | Optional, unique |
| `password_hash` | string(256) | Werkzeug PBKDF2 hash — never store plaintext |
| `is_active` | boolean | False = cannot log in |
| `is_admin` | boolean | True = access to Admin menu (user mgmt, categories, branches, import/export) |
| `created_at` | datetime | UTC timestamp |

`User` inherits from `flask_login.UserMixin` which provides the `is_authenticated`, `is_anonymous`, and `get_id()` methods Flask-Login needs.

Password methods on the model:
```python
user.set_password('plaintext')       # hashes and stores
user.check_password('plaintext')     # returns True/False
```

---

## Flask-Login Setup

In `app.py`:

```python
from flask_login import LoginManager, login_user, logout_user, current_user

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
```

All routes are protected by a `before_request` hook that checks `current_user.is_authenticated`. Unauthenticated requests are redirected to `/login?next=<original_path>` and forwarded after a successful login.

---

## Roles

Two roles — no fine-grained permissions:

| Role | `is_admin` | Can do |
|---|---|---|
| Staff | False | Data entry, file uploads, all reports and dashboards |
| Admin | True | Everything above + user management, categories/metrics, branches, import/export |

The `admin_required` decorator in `app.py` enforces this on admin routes:
```python
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            flash('Admin access required.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated
```

The Admin nav dropdown only shows its contents when `current_user.is_admin` is true.

---

## Bootstrap / First-Deploy Behaviour

On startup, if the `users` table is empty the app automatically creates one admin user:

```python
if User.query.count() == 0:
    _admin = User(username=LOGIN_USERNAME, is_admin=True, is_active=True)
    _admin.set_password(LOGIN_PASSWORD)
    db.session.add(_admin)
    db.session.commit()
```

This means the `LOGIN_USERNAME` and `LOGIN_PASSWORD` environment variables must still be set in Railway for the first boot to succeed. After individual accounts are created through the UI, those env vars can remain or be removed — the app no longer reads them at login time.

---

## Routes

| Route | Function | Access | Description |
|---|---|---|---|
| `/login` | `login` | Public | Username + password form |
| `/logout` | `logout` | Any user | Clears Flask-Login session |
| `/admin/users` | `admin_users` | Admin | List all users |
| `/admin/users/new` | `admin_user_new` | Admin | Create a new user |
| `/admin/users/<id>/edit` | `admin_user_edit` | Admin | Edit username, email, role, active status; reset password |
| `/admin/users/<id>/toggle` | `admin_user_toggle` | Admin | Activate / deactivate a user (POST) |

---

## User Management UI

Accessible via **Admin → Users** in the nav (admin only).

- **List page** — shows all users with username, email, role badge (Admin/Staff), status badge (Active/Inactive), created date. The logged-in user's row is tagged "you". Activate/Deactivate toggle button on each row (except your own).
- **Add User form** — username (required), email (optional), password (required), Admin checkbox.
- **Edit User form** — same fields as add, plus Active toggle. Separate "Reset Password" card below the main form.
- **Self-protection** — you cannot deactivate your own account or remove your own admin status, even if you submit the form with those values unchecked.

---

## Submitted By

`Entry.submitted_by` (a string field on the entries table) is now auto-filled from `current_user.username` server-side whenever an entry is created or edited. The manual text input for "Submitted by" has been removed from all entry forms (manual entry, ILL/ICL forms, generic entry form). The field still exists in the database and is displayed in the entry detail view and browse list.

---

## Security Notes

- Passwords are hashed with Werkzeug's `generate_password_hash` (PBKDF2-SHA256 by default) — never stored in plaintext.
- Login comparison uses the hash check, not `hmac.compare_digest` (the old shared-login approach). The ORM lookup by username is not timing-safe at the DB level, but is acceptable for an internal tool.
- Flask-Login uses a signed session cookie (protected by `SECRET_KEY`). The `remember=True` flag in `login_user()` sets a persistent cookie so users stay logged in across browser sessions.
- There is no password reset email flow — admins reset passwords manually through the UI.
- No account lockout after failed attempts — acceptable for an internal tool on a non-public network.

---

## Transition from v3 (Shared Login)

1. Deploy v4 to Railway (Railway auto-deploys on push to v4 branch)
2. `db.create_all()` creates the `users` table on first boot
3. A default admin is created from `LOGIN_USERNAME` / `LOGIN_PASSWORD` env vars
4. Log in with the existing shared credentials — everything works as before
5. Go to **Admin → Users → Add User** and create individual accounts for each staff member
6. Share individual credentials with each person
7. The shared login env vars can stay set (they're only used if the users table is ever emptied) or be updated to something secure

---

## Key Differences from v3

| Aspect | v3 (shared login) | v4 (user accounts) |
|---|---|---|
| Credentials | One username/password in env vars | Individual accounts in DB |
| Submitted by | Manual text field on each form | Auto-filled from logged-in username |
| Admin access | Anyone logged in | Only `is_admin=True` users |
| Password storage | Environment variable (plaintext) | PBKDF2 hash in DB |
| Account management | Change env vars + redeploy | Admin UI, no redeploy needed |
