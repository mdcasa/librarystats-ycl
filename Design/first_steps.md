# First Steps — Setting Up for a New Library

**Read this first.** This is the starting point for deploying the YCL Statistics app for a new library.
After reading this, read `Design/design.md` for full technical detail.

---

## What You Need Before Starting

Have these ready before the first session:

1. **New library's logo** — PNG format, ideally with transparent background
2. **New library's brand colors** — primary color hex codes
3. **Branch names** — the list of physical library locations (and any bookmobile/outreach)
4. **ILS name** — which Integrated Library System they use (e.g. Polaris, Koha, Symphony, Sierra). This determines what importer code needs to be written. YCL uses SIRSI — that importer is already built but is SIRSI-specific.
5. **What stats they track** — do they track the same metrics as YCL? Programming? QRS? Online stats? Any differences will require adding/removing metrics in seed data.
6. **Work email addresses** — for creating Supabase and Railway accounts under the employer

---

## Step-by-Step

### 1. Accounts — create these first

| Service | Action |
|---|---|
| **GitHub** | Create account with work email, or use existing work account |
| **Supabase** | Sign up at supabase.com with work email → create new project → copy connection string (Settings → Database → URI, `postgresql://` format) |
| **Railway** | Sign up at railway.app with work email → connect to work GitHub account |

### 2. Code — get the repo into the work GitHub account

**Option A (new library, clean start):** Fork `mdcasa/librarystats` into the work GitHub account. Rename the repo to something appropriate (e.g. `newlibrary-stats`).

**Option B (migrating YCL to work accounts):** Transfer `mdcasa/librarystats` directly — see `Design/migration_roadmap.md`.

### 3. Customise for the new library

Make these changes in a new branch before first deploy:

- **Logo:** replace `static/ycl-logo.png` with the new library's logo
- **Brand colors:** update CSS variables in `templates/base.html` (`--ycl-blue`, `--ycl-blue-dark`, `--ycl-blue-light`, `--ycl-blue-pale`)
- **App name:** find and replace `YCL Statistics` in templates with the new library name
- **Seed data:** edit `seed_data.py` — update branch names and adjust metrics if the new library tracks different stats
- **ILS importer:** if the library doesn't use SIRSI, the functions `import_sirsi_checkouts` and `import_sirsi_registrations` in `import_excel.py` need to be rewritten for their ILS export format. The metrics they write to (Total Branch Circulation, New Library Card Registrations) stay the same — only the parsing logic changes.

### 4. Deploy to Railway

1. In Railway → New project → Deploy from GitHub → select the new repo
2. Set the deployment branch
3. Add environment variables:
   - `DATABASE_URL` → Supabase connection string
   - `SECRET_KEY` → run `python3 -c "import secrets; print(secrets.token_hex(32))"` and paste the result
   - `LOGIN_PASSWORD` → initial admin password
4. Deploy — Railway builds and launches automatically

### 5. First boot (automatic)

On first launch the app will:
- Run `db.create_all()` — creates all tables in Supabase
- Run `seed_data.py` — populates categories, metrics, and branches
- Create the bootstrap admin account using `LOGIN_PASSWORD` (username defaults to `admin`)

### 6. Post-launch setup

- Log in at the Railway URL
- Go to **Admin → Branches** — verify branch names match the new library
- Go to **Admin → Categories** — verify metrics match what the library tracks
- Add additional user accounts via **Admin → Users**
- Begin uploading data files via **Upload Data**

---

## Key Differences to Watch For

- **ILS system** — the biggest variable. SIRSI importer is built; any other ILS needs a new importer written. Tell Claude which ILS the library uses at the start of the session.
- **Branch structure** — some libraries may not have locker branches or desk sub-locations. The branch taxonomy logic (locker merging in charts, is_desk filtering) can be simplified if not needed.
- **Stats tracked** — not every library tracks programming, QRS, or online stats. Adjust `seed_data.py` accordingly before first boot.
- **Quarterly Reference Stats** — the QRS form is specific to YCL's desk-tally workflow. May not be needed for other libraries.

---

## Documents to Read in This Session

Ask Claude to read these in order:

1. `Design/first_steps.md` ← this file
2. `Design/design.md` — full technical reference
3. `Design/migration_roadmap.md` — if migrating YCL to work accounts
4. `Design/roadmap.md` — current feature and data backlog (YCL-specific)
