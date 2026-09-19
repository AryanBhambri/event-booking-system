# Evently — Event Booking System

Evently is a Flask/MySQL capstone application for discovering events, reserving tickets, and managing event attendance. Reservations are confirmed immediately; **no payment is collected**. The application uses the existing `event_booking_system` database.

## Features

- Responsive Home, About, event discovery, search, category/city filters, and event detail pages.
- Registration, password hashing, login/logout, and separate user/admin access.
- Event creation, editing, deletion safeguards, and validated banner uploads.
- Transactional bookings with row locks, server-calculated totals, and seat availability protection.
- Personal booking history, user dashboard, and printable confirmations.
- Admin dashboard with MySQL statistics and Chart.js charts.
- Booking, event-performance, and registration reports with CSV exports and spreadsheet-formula protection.
- CSRF protection, form validation, friendly error/empty states, and automated QA coverage.

## Stack and requirements

Python 3.10+, Flask/Jinja, MySQL Server 8.0+, mysql-connector-python, Flask-WTF, Pillow, HTML/CSS/JavaScript, Bootstrap 5, and Chart.js. Waitress is included for production WSGI serving on Windows or Linux. Playwright is an optional development dependency for browser QA.

Bootstrap, Google Fonts, and Chart.js currently load from external CDNs. Browser access to those services is required for the complete visual experience and charts.

## Structure

```text
event-booking-system/
├── app.py                   Application factory, routes and error handlers
├── config.py                Environment-based configuration
├── database/
│   ├── db.py                MySQL connection helper
│   └── schema.sql           Schema for a NEW installation only
├── routes/                  Authentication, events, bookings, dashboards, admin
├── utils/                   Access control and event/image validation
├── templates/               Jinja pages, including admin reports
├── static/                  CSS, JavaScript, fallback image and uploads
├── tests/                   Original integration checks and Phase 7 regressions
├── requirements.txt         Runtime dependencies
├── requirements-dev.txt     Runtime dependencies plus browser QA
├── .env.example             Placeholder configuration
└── QA_REPORT.md              Audit results and remaining deployment work
```

## Local setup (PowerShell)

Use the existing virtual environment if it is already installed. For a fresh checkout:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

For a fresh checkout only, copy `.env.example` to `.env`. **Do not overwrite an existing `.env`.** Enter your own MySQL credentials. Generate a secret with:

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"
```

Copy the generated value into `SECRET_KEY` in your private `.env`. Never put it in source control or documentation. Startup rejects missing, short, or known placeholder secrets.

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Required, unique random secret of at least 32 characters; keep stable between restarts/workers |
| `FLASK_DEBUG` | `false` by default; keep `false` in deployment |
| `SESSION_COOKIE_SECURE` | `false` for local HTTP; `true` for HTTPS deployment |
| `MYSQL_HOST`, `MYSQL_PORT` | Existing MySQL server address and port (default 3306) |
| `MYSQL_USER`, `MYSQL_PASSWORD` | Private database account credentials |
| `MYSQL_DATABASE` | `event_booking_system` |
| `MYSQL_CONNECT_TIMEOUT` | Connection timeout in seconds (default 10) |
| `MYSQL_SSL_CA` | Optional CA certificate path; enables certificate and hostname verification for remote MySQL |
| `TRUSTED_HOSTS` | Optional comma-separated hostnames; set to deployed domains in production |

Environment variables supplied by the hosting platform take precedence over `.env`.

## MySQL setup and existing data

**For this existing workspace: do not run `schema.sql`, recreate tables, or delete data.** Verify the configured database with:

```powershell
.\.venv\Scripts\python.exe -m flask --app app check-db
```

The database contains `users`, `events`, and `bookings`. Foreign keys restrict deletion of events with bookings. Booking writes and event capacity edits lock the event row in a transaction.

For an entirely new installation on a new database server only, open `database/schema.sql` in MySQL Workbench and execute it once. Alternatively, use the MySQL client's `SOURCE` command with the schema's absolute path. Back up existing databases before administrative work. The application never initializes or migrates the schema on startup.

Use a dedicated runtime MySQL account with `SELECT`, `INSERT`, `UPDATE`, and `DELETE` privileges on this database, not a server administrator account. Keep the database private; use verified TLS when connecting across an untrusted network.

## Run locally

From the project directory:

```powershell
.\.venv\Scripts\python.exe -m flask --app app run --host 127.0.0.1 --port 5000 --no-debugger --no-reload
```

Open `http://127.0.0.1:5000`. Stop with Ctrl+C. The explicit host and port can be changed as needed. `python app.py` also starts the local development server, but a production deployment must use a WSGI server.

## User and admin roles

Registration creates normal users. Users can browse, reserve tickets, and access only their own bookings and confirmations. Admins additionally manage events, analytics, and reports. Logout is a CSRF-protected POST form.

To assign an administrator, a database administrator may update the role of one known registered account (replace the placeholder email):

```sql
UPDATE event_booking_system.users
SET role = 'admin'
WHERE email = 'replace-with-your-registered-email@example.com';
```

Sign out and back in after a role change because roles are stored in the signed session. There are no seeded/default admin credentials.

## Testing

Install development dependencies if browser tests are needed:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Run all six original integration scripts and the Phase 7 regression cases together:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
```

The original individual commands still work, for example:

```powershell
.\.venv\Scripts\python.exe -m tests.test_bookings
```

Integration tests connect to the configured database. They create uniquely named temporary users/events/bookings and remove only their own records and files. They do not recreate the database or schema. Use a separate test database for routine CI; the Phase 7 closeout readiness check on 20 September 2026 verified all original rows against the saved pre-audit SHA-256 hashes: 3 users, 1 event, and 4 bookings. No leftover QA records were found and no cleanup was needed. See `QA_REPORT.md` and `.qa-artifacts/readiness-results.json` for evidence. Do not interrupt a running integration test unnecessarily; abrupt process termination can prevent cleanup. Test inserts advance auto-increment counters even after cleanup.

Browser checks use installed Microsoft Edge by default and start a temporary localhost server:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.browser_qa -v
```

Set `QA_BROWSER_CHANNEL=chrome` to use installed Chrome instead. The checks cover registration through logout, admin event management, uploads, reports/downloads, charts, print output, and pages at 1440px, 768px, and 390px. Screenshots and the print PDF go to ignored `.qa-artifacts/`. Keep test evidence private because reports can contain account information. Browser tests are separate so server-side tests do not require a browser.

## Reports and CSV exports

Admin-only routes:

- `/admin/reports/bookings`: filter by event, status, and booking date.
- `/admin/reports/events`: event capacity, ticket counts, and reservation totals.
- `/admin/reports/users`: registration summary.

Each has a `/export` endpoint. Booking export respects the current filters. Reports select no password hashes or credentials. Potential spreadsheet formulas in text fields are prefixed with an apostrophe. CSV files still contain personal information such as names/emails and should be handled accordingly.

Booking confirmations at `/bookings/<booking_code>` support browser printing and browser Save as PDF. They display the original booked unit price, calculated from the stored total and quantity, even after an administrator changes the event's price. Revenue statistics represent reservation totals, not collected payments.

## Uploads and static assets

Banners accept PNG, JPEG, GIF, or WEBP up to 5 MB. Pillow validates the actual image contents and extension; filenames are generated, and invalid/decompression-bomb images are rejected. Requests allow 6 MB including multipart overhead. Uploaded images are public assets in `static/uploads/`; never upload confidential documents. The folder must be writable and persistent, with backups. For multiple application instances, mount shared storage at that path or adapt image serving before scaling. Missing banners use the bundled default SVG when no image is assigned.

## Deployment preparation — not deployed

1. Install `requirements.txt` into an isolated runtime environment.
2. Set a unique deployment `SECRET_KEY`, `FLASK_DEBUG=false`, `SESSION_COOKIE_SECURE=true`, and `TRUSTED_HOSTS` to the public domains. Use the platform's secret store; never publish `.env`.
3. Configure the existing/target MySQL database and a least-privilege runtime user. Set `MYSQL_SSL_CA` for verified remote TLS. Verify connectivity with `check-db`; do not rerun schema setup over existing data.
4. Mount persistent writable storage for `static/uploads/` and back up both the database and images.
5. Serve through Waitress behind an HTTPS reverse proxy. For example, on Windows:

   ```powershell
   .\.venv\Scripts\waitress-serve.exe --host=127.0.0.1 --port=8000 app:app
   ```

   On Linux, the equivalent executable is `waitress-serve`. Use the host/port assigned by your platform; expose `0.0.0.0` only when required by its networking model. Keep the backend private behind the proxy. Do not enable proxy-header trust unless configured for the actual trusted proxy.

6. Configure the proxy to allow the 6 MB request limit, serve static assets, and terminate HTTPS. Verify cookies, login/logout, CSRF forms, uploads, and print pages over the final domain. Configure CDN access or self-host the external Bootstrap/fonts/Chart.js dependencies if required.
7. Add platform-specific logging, monitoring, backups, login abuse/rate limiting, and dependency vulnerability checks before public launch. No email delivery or payment gateway is implemented.

Official references: [Flask deployment](https://flask.palletsprojects.com/en/stable/deploying/), [Waitress with Flask](https://flask.palletsprojects.com/en/stable/deploying/waitress/), [Flask security](https://flask.palletsprojects.com/en/stable/web-security/), and [Pillow image security](https://pillow.readthedocs.io/en/stable/handbook/security.html).

## GitHub preparation

`.gitignore` excludes `.env` variants, virtual environments, bytecode, private key files, secrets, uploads, logs, QA artifacts, and temporary QA packages. `.env.example` contains placeholders only. Keep `static/uploads/.gitkeep` so the upload directory exists in fresh checkouts.

Before the first commit, inspect `git status` and the staged diff for secrets and private artifacts. Ignore rules do not remove files already committed: inspect history if importing this project into an existing repository. This audit does not initialize Git, push a repository, or deploy the site.
