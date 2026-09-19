# Phase 7 QA report

Audit scope: the existing Evently workspace and existing `event_booking_system` database. No project recreation, schema change, deployment, or GitHub push.

## Files changed

- `app.py`: required secret validation, CSRF setup, useful request/database errors, security/cache headers.
- `config.py`, `database/db.py`: safe debug default, upload/request limits, connection timeout, optional verified MySQL TLS, trusted hosts, sanitized connection diagnostics.
- `routes/auth.py`: malformed/external redirect rejection and duplicate-registration race handling.
- `routes/events.py`: working upcoming filter and event-start state.
- `routes/bookings.py`: closed-event protection, bounded totals, current availability on errors, original booking-price display, unused import removal.
- `routes/admin.py`: formula-safe CSV cells and transactionally consistent capacity edits.
- `utils/event_helpers.py`: database-range validation and actual image validation.
- `static/js/script.js`, `static/css/style.css`: safe Delete confirmation, quantity handling, responsive table scrolling, mobile gutters/wrapping, print visibility.
- `templates/base.html`, `templates/login.html`, `templates/register.html`, `templates/events.html`, `templates/event-details.html`, `templates/booking.html`, `templates/booking-confirmation.html`, `templates/admin/events.html`, `templates/admin/event-form.html`: form tokens, filter submission, event-state messages, print labels, safe confirmation attributes, favicon.
- New `templates/request-error.html`.
- Six original `tests/test_{about,auth,events,bookings,dashboards,reports}.py` modules: submit real CSRF tokens; image tests use real PNG/WEBP files. Original assertions retained.
- New `tests/helpers.py`, `tests/qa_support.py`, `tests/test_existing.py`, `tests/test_final_qa.py`, `tests/browser_qa.py`, `tests/readiness_check.py`.
- `requirements.txt`, new `requirements-dev.txt`, `.gitignore`, `.env.example`, `README.md`, and this report.
- Private, ignored `.env`: replaced the known placeholder secret with a generated secret and disabled debug. Existing database credentials were retained. Previous signed sessions are invalidated by this necessary key rotation.
- Existing `.venv` setup was completed and dependencies installed. Temporary QA packages/results are excluded from Git.

`database/schema.sql`, the database initializer, and the working dashboard/analytics queries were not rewritten.

## Confirmed bugs fixed

| Finding | Resolution |
|---|---|
| Unchecking Upcoming only still showed only upcoming events | Explicit unchecked value plus correct checkbox value handling |
| Admin edits could restore seats reserved after the edit read | Lock and re-read current capacity inside the update transaction |
| Past/started events could still be booked | Check the start time under the booking lock; show a closed message |
| Old confirmations displayed a newly edited event price | Derive original unit price from stored booking total/quantity |
| Confirmation claimed money was paid although reservations collect no payment | Label changed to Booking total |
| NaN/infinite/oversized numeric values could cause errors or exceed schema limits | Validate finite prices, precision, seat/description limits, and booking totals |
| Event titles with quotes broke inline Delete JavaScript | Escaped data attribute and shared event listener |
| CSV text could execute as spreadsheet formulas | Escape formula-leading user-controlled cells in every export |
| Upload filenames/MIME could disguise non-image data | Validate format, decode integrity, size, extension, and image-bomb warnings with Pillow |
| Missing CSRF checks on modifying forms | Flask-WTF CSRF protection on all POST actions |
| Published placeholder secret and debug enabled locally | Random local secret, debug off, startup rejects unsafe secrets |
| Malformed/backslash login targets were insufficiently checked | Reject malformed and non-local targets |
| Simultaneous duplicate registrations could produce a generic 500 | Recognize duplicate-key error and return the existing duplicate-account message |
| Oversized requests/database outages lacked contextual pages | Helpful 413/503 pages without internal error details |
| Report/history tables clipped horizontally on small screens | Enable horizontal scrolling within the table container |
| Mobile About and Event Details had horizontal overflow | Reduce wide Bootstrap gutters within mobile containers |
| Confirmation action buttons remained visible in print due to Bootstrap utilities | Print hiding overrides the utility display rule |

## Testing methodology

The six original scripts are exposed as six `unittest` cases; each case still runs every original assertion. Seventeen added server-side cases cover form/security failures, all admin route methods, navigation by role, local links/images, booking isolation and totals, price edits, capacity races, simultaneous last-seat booking, reports/CSV, and empty states.

Empty-database display cases use mocked read results rather than deleting existing data. Other workflow checks use uniquely identified temporary records in the existing database, with cleanup scoped to those records. The concurrent-booking test uses two clients and an actual MySQL row lock. The capacity-edit regression simulates a booking between the initial form read and transaction read.

Browser checks use headless Microsoft Edge through Playwright and a temporary localhost server. They exercise registration, login, search/filter, booking quantity controls, confirmation, print invocation/PDF rendering, history, dashboard, logout, admin login, create/upload/edit/delete, charts, and all CSV downloads. Layout checks cover 16 role/page combinations at 1440×1000, 768×1024, and 390×844: 48 checks, including mobile menu operation, local image loading, horizontal overflow, and scrollable tables.

The first baseline suite run passed five modules and encountered one transient MySQL connection interruption; the subsequent original suite passed all six. Early new browser failures included corrected test synchronization and a Bootstrap mobile assertion; subsequent runs identified the real print and mobile gutter bugs listed above. No original test was removed or weakened.

## Security findings

Verified password hashing, parameterized user-supplied SQL values, CSRF-protected forms, user booking ownership, admin-only report/export/action routes, no credential fields in report selections, safe generated upload names, actual image validation, and formula-safe CSV exports. Session cookies are HTTP-only with SameSite=Lax. HTML/report responses are not cached, and responses include nosniff and framing headers.

Roles are held in signed sessions; database role changes require sign-out/sign-in. Login throttling, broader abuse protection, monitoring, and managed backups remain deployment tasks. CSV reports intentionally contain account names/emails and should be kept private. No payment or email service is implemented.

## GitHub readiness

The folder is not a Git repository. There is no commit history here to inspect, so historical credential exposure cannot be certified. The ignore rules cover `.env` variants, virtual environments, bytecode, keys/secrets, uploads, logs, temporary QA packages, and test evidence. `.env.example` contains placeholders only. Inspect the staged diff and any imported history before committing. Nothing was pushed, and no repository was initialized.

## Deployment readiness and remaining work

Runtime dependencies are declared, debug defaults off, unsafe secrets fail startup, and Waitress is available. The application is prepared for a deployment configuration review; it has not been deployed or certified under production load.

Required deployment configuration:

1. Configure a stable, unique secret through the platform secret store; `FLASK_DEBUG=false`, `SESSION_COOKIE_SECURE=true`, and public `TRUSTED_HOSTS`.
2. Use a private MySQL service and least-privilege account. Set `MYSQL_SSL_CA` for verified remote TLS. Test the target connection; do not recreate the current schema/data.
3. Provide persistent writable `static/uploads/` storage and database/image backups. Multiple instances require shared upload storage.
4. Run Waitress behind HTTPS on the platform's required host/port; align proxy upload limits with the 6 MB application request limit.
5. Ensure access to external Bootstrap/fonts/Chart.js assets, or vendor them for a deployment requiring independent asset hosting.
6. Add deployment-specific login abuse controls, monitoring, dependency vulnerability scanning, backup recovery checks, and an HTTPS smoke test.

Local development command (from the project directory):

```powershell
.\.venv\Scripts\python.exe -m flask --app app run --host 127.0.0.1 --port 5000 --no-debugger --no-reload
```

Production WSGI command example, behind an HTTPS proxy:

```powershell
.\.venv\Scripts\waitress-serve.exe --host=127.0.0.1 --port=8000 app:app
```

See [README.md](README.md) for setup, roles, environment variables, MySQL, tests, reports, and official deployment references.

## Final verification results

Closeout date: 20 September 2026. The current database was checked before any new integration-test writes. Application code, schema, and tests were not changed during this closeout.

| Verification | Actual recorded result |
|---|---|
| Complete discovered server suite | Latest completed run: 23 passed, 0 failed/errors, 0 skipped (six original integration modules plus 17 regressions). The requested post-documentation rerun is recorded separately in `final-server-tests.txt` and `final-server-results.json`. |
| Current database readiness | Passed the existing `tests/readiness_check.py`, exit code 0. |
| Database preservation | All rows match the original pre-audit SHA-256 hashes exactly: 3 users, 1 event, 4 bookings. No leftover QA records; no cleanup required. |
| Browser user/admin workflows | Corrected run passed; `workflow-results.json` records both workflows passed and an empty JavaScript-error list. This successful workflow rerun supersedes the earlier selector failure. |
| Responsive UI | `responsive-results.json` records 48 passed checks: 16 each at 1440px, 768px, and 390px. Retained evidence; no new visual audit required. |
| Print confirmation | Browser print invocation and print visibility assertions passed; generated `confirmation.pdf` is retained. This verifies browser PDF output, not a physical printer. |
| Security | Current readiness verifies password-hash formats, valid secret configuration, debug disabled, HTTP-only/SameSite cookies, and syntax. Existing regression evidence covers CSRF, route authorization, booking ownership, uploads, redirects, and CSV formula protection. No new production penetration test or dependency vulnerability scan is claimed. |

Complete output from the current pre-test readiness run:

```text
PASS: Original database rows match the pre-audit hashes exactly.
PASS: Three tables, columns, InnoDB, foreign keys, seat totals, password hashing, and uploaded images.
PASS: Unique local secret configured, debug disabled, HTTP-only/SameSite cookies.
PASS: Python and JavaScript syntax.
Git repository present: False
Local startup: .\.venv\Scripts\python.exe -m flask --app app run --host 127.0.0.1 --port 5000 --no-debugger --no-reload
```

Evidence retained under the ignored `.qa-artifacts/` directory:

- `database-before.json`: unchanged original pre-audit row counts and hashes.
- `closeout-before.json`: current counts established before any closeout test writes.
- `readiness-closeout-before.txt`: complete output quoted above.
- `readiness-results.json`: output generated by the existing readiness script; the post-test invocation refreshes it after test cleanup.
- `readiness-closeout-after.txt`: post-test readiness output, to confirm test cleanup preserved all original rows.
- `server-tests.txt`: previous successful 23-case server run.
- `final-server-tests.txt` and `final-server-results.json`: authoritative post-documentation server rerun evidence.
- `browser-tests.txt`: historical intermediate run; responsive checks passed but the workflow selector matched both a metadata tag and the form description field.
- `workflow-results.json`: later corrected successful user/admin workflow result, with no recorded JavaScript errors.
- `responsive-results.json`, screenshots, and `confirmation.pdf`: successful responsive and print evidence.
- `README.md`: artifact chronology and interpretation.

The post-documentation suite and subsequent database readiness check provide the final closeout evidence in the result artifacts above. Historical failures remain available and are not presented as final failures.

GitHub preparation can proceed with a staged-file/secret review; no repository has been created. Deployment preparation can proceed using the documented configuration steps, but HTTPS/proxy configuration, production database permissions/TLS, persistent uploads, backups, monitoring, and abuse controls remain deployment responsibilities. No deployment or push occurred.
