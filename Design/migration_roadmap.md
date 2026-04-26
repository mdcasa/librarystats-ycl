# Migration Roadmap — Move to Work Accounts

**Goal:** Transfer the entire YCL Statistics system (code, database, hosting) from personal accounts to work email accounts so the employer can own and pay for the ongoing infrastructure.

**Services to migrate:**
- GitHub (source code)
- Supabase (PostgreSQL database + all data)
- Railway (app hosting)

---

## Step 1 — GitHub

You have two options. **Option A is recommended.**

### Option A: Transfer the repository (recommended)
Transfer ownership of `mdcasa/librarystats` to the work GitHub account. The repo URL changes but Railway can be updated to follow it.

1. In GitHub → `mdcasa/librarystats` → Settings → scroll to **Danger Zone** → **Transfer**
2. Enter the work GitHub username or organization name
3. Confirm — the repo moves instantly; the old URL redirects for a period

### Option B: Fork to work account
If you want to keep the personal repo intact (e.g. as a template for future libraries):

1. Log into work GitHub account
2. Fork `mdcasa/librarystats`
3. Use the work fork as the source for Railway

---

## Step 2 — Supabase

Create a new Supabase project under the work email and migrate all data.

### 2a. Create new Supabase project
1. Sign up at [supabase.com](https://supabase.com) with work email
2. Create a new project — note the **connection string** (Settings → Database → URI mode, `postgresql://`)

### 2b. Export data from old Supabase
Run this from your local machine (with `.env` loaded pointing at the old Supabase):
```bash
pg_dump YOUR_OLD_SUPABASE_URL > ycl_backup.sql
```
Or use Supabase dashboard → Settings → Database → Backups to download a backup file.

### 2c. Import into new Supabase
```bash
psql YOUR_NEW_SUPABASE_URL < ycl_backup.sql
```

### 2d. Verify
Open the new Supabase project's Table Editor and confirm all tables and row counts match the old project.

---

## Step 3 — Railway

Create a new Railway account under the work email and deploy from the work GitHub repo.

1. Sign up at [railway.app](https://railway.app) with work email
2. **New project → Deploy from GitHub repo** → connect work GitHub account → select the transferred/forked repo
3. Set the deployment branch to `v4` (or whatever the active branch is at migration time)
4. **Set environment variables:**

| Variable | Value |
|---|---|
| `DATABASE_URL` | New Supabase connection string (from Step 2) |
| `SECRET_KEY` | Generate a new random string: `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `LOGIN_PASSWORD` | Set a new admin password for the work instance |

5. Deploy — Railway will build and launch automatically

---

## Step 4 — Update the App URL

Railway will assign a new `.railway.app` URL. Share this with staff so they can bookmark it. If a custom domain is needed, configure it in Railway → Settings → Domains.

---

## Step 5 — Verify Everything

Before decommissioning the old accounts:

- [ ] Log in at the new Railway URL
- [ ] Check Data Status widget — all categories show correct dates
- [ ] Run a report (Monthly Summary, Trend Over Time) and confirm data matches old instance
- [ ] Check Admin → Users — confirm accounts carried over from the DB migration
- [ ] Upload a test file and confirm it imports correctly

---

## Step 6 — Decommission Old Accounts

Once verified and staff are using the new URL:

- [ ] Remove old Railway service (or let it idle — it won't affect the new one)
- [ ] Delete old Supabase project (Settings → General → Delete project) — **only after confirming the new instance is fully working**
- [ ] Optionally archive or delete the personal GitHub repo if Option A (transfer) was used

---

## Notes

- **Data is in Supabase, not Railway** — Railway is stateless. All data lives in the Supabase database. If Railway goes down or is redeployed, no data is lost.
- **SECRET_KEY change** — generating a new SECRET_KEY will invalidate any existing login sessions, which is fine since users will be logging in fresh anyway.
- **No code changes needed** — this is purely an infrastructure move. The codebase stays the same.
- **GitHub Codespaces** — if you use GitHub Codespaces for development, you may need to reconnect the Codespace to the new repo after the transfer.
