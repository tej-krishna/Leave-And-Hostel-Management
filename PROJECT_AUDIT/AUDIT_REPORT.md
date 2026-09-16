# Hostel & Leave Management System — Audit Report

Branch: `audit-and-hardening` (created from `main` at commit `6318adc`)
Environment: Windows, Python 3.13, Django 6.0.5, SQLite (dev), isolated venv at `venv/`.
Method: static code reading of every app (models/views/urls/forms/admin), `manage.py check`/`check --deploy`/`makemigrations --check`, direct reproduction of suspected bugs via `RequestFactory`/Django test client, a live `runserver` smoke test in a real browser, and a new automated test suite (17 tests, all passing).

Legend: **PASS — verified**, **FAIL — reproduced**, **BLOCKED — environment prevents verification**, **NOT TESTED — requires physical hardware or is out of scope for this pass**.

---

## 1. Executive Summary

The Django backend is structurally sound: migrations are consistent, `manage.py check` is clean, CSRF tokens are present on every form/AJAX call I found, and the three apps (`hostel_app`, `rooms_app`, `essl_app`) are cleanly separated. Test coverage was **zero** before this audit (all three `tests.py` were empty stubs) — that is now partially addressed with 17 tests targeting the workflows below.

Two functional bugs were **reproduced and fixed**:

1. A missing `Q` import in `essl_app/views.py` caused a silent `NameError` every time a student's "Hostel In" biometric punch was recorded, permanently leaving returning students marked `leave`/`outing`. This is the core documented biometric auto-status workflow, and it was broken. Confirmed broken, then confirmed fixed, by direct reproduction (see §9).
2. `rooms_app.views.allot_student_to_room` used an unguarded check-then-act sequence (`is_full()` → `student.save()`) with no transaction or row lock — a classic TOCTOU race that allows a room to be over-allocated under concurrent requests. Fixed with `transaction.atomic()` + `select_for_update()` (see §7).

The **single largest open risk** is architectural, not a bug: the `Student` model has no password field at all, and `perform_login()` authenticates purely on `(student_id, name)` — both values that are visible on ID cards, room lists, and the app's own Student Lookup feature. This means anyone who knows a staff member's name and ID can log in as that staff member with full `editor` rights (room allocation, leave approval, device configuration). This is flagged as the top finding (§4) but **not changed**, because adding real credentials is a product decision (login UX, password reset flow, migrating existing accounts) beyond a "fix", not a contained bug — see §4 for the recommendation and the decision this needs from you.

Biometric-hardware behavior (real eSSL/ZKTeco device communication) could **not** be verified — no physical device is available in this environment. All eSSL findings are code-level verification only, clearly marked below.

---

## 2. Architecture

```
HOSTEL/            Django project (settings, root urls, wsgi/asgi)
hostel_app/        Auth (session-based, no passwords), students, leave applications, dashboard, biometric-track view
rooms_app/         Hostels → Floors → Rooms → allotment, 3D/grid UI, AJAX endpoints
essl_app/          eSSL/ZKTeco ADMS ingestion (/iclock/*), device config, attendance logs
sniffer.py         Standalone raw-socket diagnostic script (not imported by Django; developer tool for confirming a device reaches the LAN host — see §11)
verify_data.py     Standalone data-sanity script, run via `manage.py shell` (see §8)
```

No REST framework, no Celery, no Redis usage despite `channels`/`channels_redis`/`redis` being in `requirements.txt` (dependency audit, §3). Authorization is entirely session-based via a hand-rolled `role_required(['viewer'|'editor'|'student'])` decorator (`hostel_app/views.py:18-36`, duplicated near-verbatim in `rooms_app/utils.py`) — there is no Django `User`/permission-framework usage outside `/admin/`.

---

## 3. Dependency Audit

`requirements.txt` is **UTF-16 encoded** (confirmed with `file`) — unusual but pip installed it without incident, so this is cosmetic, not a bug. 76 packages are pinned; a large fraction are unused by the actual codebase as far as I could trace:

| Package | Evidence of use | Verdict |
|---|---|---|
| Django, django-import-export, mysql-connector-python, psycopg2-binary, python-dotenv, Pillow, qrcode, requests | Used (dotenv in settings.py; requests in `pinger.py`; Pillow/qrcode implied by unused QR migration fields — see §8) | Keep |
| channels, channels_redis, daphne, autobahn, twisted, txaio | **No `ASGI_APPLICATION`, no consumers, no routing found anywhere.** `HOSTEL/settings.py` only defines `WSGI_APPLICATION`. `HOSTEL/asgi.py` exists but is the default Django scaffold. | Appears unused — dead weight, not a bug. Do not remove blindly without confirming no planned real-time feature depends on it (I did not invent removal per instructions). |
| ollama, nltk, opencv-python, pymongo, platformio, pyserial, pyelftools | **No imports found anywhere in the three apps or the top-level scripts.** | Appears unused. |
| webauthn | `WEBAUTHN_RP_ID`/`WEBAUTHN_ORIGIN` settings exist (`HOSTEL/settings.py:157-159`) but no view imports `webauthn` or references these settings. Looks like an abandoned feature. | Unused, settings are dead config. |

**Verdict:** I did not remove any dependency — pruning `requirements.txt` changes what a fresh `pip install` pulls in and is a judgment call about intent, not a bug fix. Flagging for your decision.

---

## 4. Authentication & Authorization — TOP FINDING (needs your decision, not fixed)

**File:** `hostel_app/models.py` (Student model, no password/credential field of any kind) and `hostel_app/views.py:326-363` (`perform_login`).

```python
student = Student.objects.get(student_id__iexact=student_id, name__iexact=name)
request.session['user_role'] = student.role   # 'student' | 'viewer' | 'editor'
```

**Reproduced live** (test `hostel_app.tests.LoginAuthenticationTests.test_correct_id_and_name_logs_in_without_any_password`, and manually in the browser with `NSTAFF1` / `Staff One` — screenshot taken, editor dashboard reached instantly).

**Why it matters:** Student ID + name is not a secret. It's printed on ID cards, visible in room lists staff can browse, and directly discoverable through the app's own `student_lookup` feature (`hostel_app/views.py:250-300`), which lets any logged-in student search by name. There is no rate limiting, no lockout, no audit trail on failed attempts. Anyone who knows (or looks up) an `editor`-role student's name can impersonate them and gain full staff privileges: approve/reject leave, allocate/unallocate rooms, reconfigure biometric devices.

**Authorization itself is enforced correctly everywhere I checked** — every sensitive view in `hostel_app`, `rooms_app`, and `essl_app` is wrapped in `role_required([...])`, checked server-side against `request.session['user_role']`, not just hidden in the UI (verified by reading every `@role_required` call site — 20 of them across the three apps). The gap is entirely in *authentication* (proving who you are), not authorization (what a role can do).

One secondary, minor consequence of the session-role design: if an `editor` is demoted to `student` in the DB, their existing browser session keeps `editor` privileges until they log out and back in (role is cached in session at login time, never re-checked against the DB). Low severity given the primary finding above, and changing it would add a DB query to every request — flagged, not changed.

**Recommendation:** decide whether this hostel/leave system intentionally trades authentication strength for low-friction login (plausible for a trusted LAN-only deployment with physical access control), or whether staff accounts need real passwords. If the latter, I'd suggest: add a `password` field (Django's `set_password`/`check_password` hashing) to `Student` for `editor`/`viewer` roles only, keep the current ID+name flow for `student` role (low-privilege, self-service), and gate `perform_login` accordingly. I did not implement this because it's a scope decision, not a confirmed bug fix — happy to build it if you want it.

---

## 5. Bugs Found, Reproduced, and Fixed

### BUG-001 (P1 — confirmed, fixed) — Biometric "return from leave" silently never happens
- **File:** `essl_app/views.py`, function `iclock_cdata`
- **Root cause:** `Q(user_id__icontains=...)` was used inside the Hostel-In (`punch_state == '3'`) branch without `from django.db.models import Q` anywhere in module scope.
- **Reproduction:** created a student with `status='leave'`, POSTed a synthetic ADMS `ATTLOG` line with `punch_state='3'` directly at `iclock_cdata` via `RequestFactory`. Server printed `Error parsing log line '...': name 'Q' is not defined`; endpoint still returned `HTTP 200 "OK\n"` to the device (so the physical device believes sync succeeded); student status remained `leave` instead of `present`.
- **Impact:** every real-world "student badges back into the hostel" event silently failed to update status, with **zero visible error** anywhere except the server's stdout. This is the core promise of the biometric integration per the README.
- **Fix:** added the missing import; also collapsed a second, unreachable `elif punch_state in ['1', '2']:` branch (dead code — the first `if punch_state in ['1', '2']:` above it already consumed that condition in the same `if/elif` chain) into the live branch, so the "clear stale Hostel-In logs when a new trip starts" cleanup — which previously could never execute — now runs.
- **Verification:** re-ran the exact same reproduction after the fix — status now correctly flips to `present`, no exception. Also captured as a permanent regression test: `essl_app.tests.IclockCdataTests.test_hostel_in_punch_resets_status_to_present`.
- **Status:** FIXED, verified.

### BUG-002 (P1 — confirmed by code inspection, fixed) — Room over-allocation race condition
- **File:** `rooms_app/views.py`, function `allot_student_to_room`
- **Root cause:** classic check-then-act: `room.is_full()` was evaluated, then (after further checks) `student.room = room; student.save()` — with no transaction and no row lock in between. Two concurrent requests for the last free bed can both read `is_full() == False` before either writes, both then save, and the room ends up over capacity.
- **Why not reproduced with a live thread race:** SQLite (the current dev DB) serializes writes at the file level, which would mask the interleaving in a simple concurrency test and give a false sense of safety. The settings file has a commented-out PostgreSQL config (`HOSTEL/settings.py:83-92`), which is where this race is actually exploitable, so I fixed it as a code-correctness issue rather than trying to force a flaky reproduction against SQLite.
- **Fix:** wrapped the check-then-act sequence in `transaction.atomic()` and added `select_for_update()` to both the `Room` and `Student` queries, so the capacity/duplicate-allotment checks and the save happen atomically under a row lock once a real multi-connection database (Postgres/MySQL) is used. This is a no-op on SQLite (documented Django limitation) but correct and inert there — no behavior change for the current dev setup, verified by the full test suite still passing.
- **Status:** FIXED (code-level; DB-level race confirmed absent under Postgres/MySQL semantics, not empirically raced against SQLite for the reason above).

### BUG-003 (P1/P2 — confirmed by code inspection, fixed) — Biometric device identity spoofable via `X-Forwarded-For`
- **File:** `essl_app/views.py`, function `iclock_cdata`
- **Root cause:** the endpoint is (necessarily) `@csrf_exempt` and has no device secret/token — it identifies a "trusted" device purely by source IP, looked up as `BiometricDevice.objects.filter(ip_address=client_ip)`. The old code computed `client_ip` by trusting a client-supplied `X-Forwarded-For` header *whenever present*, with no proxy configured in Django settings (no `SECURE_PROXY_SSL_HEADER`, no trusted-proxy allowlist). Any caller who can reach the endpoint could set `X-Forwarded-For: 192.168.137.70` (a configured device's IP) and have their forged attendance line applied with that device's `location_type`, silently changing an arbitrary student's status.
- **Reproduction:** `essl_app.tests.IclockCdataTests.test_spoofed_x_forwarded_for_does_not_impersonate_a_configured_device` — sends a request with `REMOTE_ADDR='10.0.0.9'` and a forged `X-Forwarded-For: 192.168.137.70` header (a configured "Hostel Out" device). Before the fix this test fails (the log gets attributed to the trusted device and its `location_type`); after the fix it passes.
- **Fix:** stopped trusting `X-Forwarded-For`; the endpoint now uses `REMOTE_ADDR` only, which is the actual TCP peer and cannot be spoofed by request headers.
- **Caveat, stated plainly:** this closes the *header-spoofing* vector but does **not** add real device authentication. If `/iclock/cdata` is reachable from the open internet (the `pyngrok` dependency suggests it might be tunneled for remote device access), anyone who can reach it directly (not just via a forged header) can still post fake attendance data for any student ID with no credential at all. A durable fix needs a per-device shared secret/token validated in `iclock_cdata`, or restricting the endpoint to a known IP range at the network/firewall layer. Not implemented — this is a bigger protocol change and the physical deployment topology (is this endpoint internet-facing or LAN-only?) determines how urgent it is; flagging for your decision rather than guessing at your network setup.
- **Status:** FIXED (spoofing vector), residual risk documented above.

### BUG-004 (P2 — confirmed, fixed) — `verify_data.py` crashes on any empty batch/gender group
- **File:** `verify_data.py:14`
- **Root cause:** `Student.objects.filter(year=b, gender=g).first().room` — `.first()` returns `None` when no student matches that year/gender combination, and `.room` on `None` raises `AttributeError`.
- **Reproduction:** ran the script's logic against the (empty) dev database via `manage.py shell -c "exec(open('verify_data.py').read())"` — confirmed it crashes on the very first `E1 M` group before the fix, runs clean after.
- **Fix:** null-check the `.first()` result before accessing `.room`.
- **Status:** FIXED, verified.

### BUG-005 (P3 — confirmed, fixed) — spurious `staticfiles.W004` warning on every management command
- **File:** `HOSTEL/settings.py:143-145` references `BASE_DIR / 'static'`, which didn't exist in the repo.
- **Fix:** created `static/` (with a `.gitkeep`) so the directory exists. Cosmetic only — `manage.py check` now reports zero issues instead of one warning.
- **Status:** FIXED, verified (`manage.py check` output went from 1 warning to "no issues").

---

## 6. Findings Documented But Not Changed (judgment calls, not "bugs" in the strict sense)

| # | Severity | File | Finding |
|---|---|---|---|
| F1 | P2 | `hostel_app/forms.py:121-137` | Group-leave "companion" validation checks that the companion has *some* pending/approved leave on the same date, but never checks that the companion's own application names this student back. Two unrelated students could each list a third, uninvolved student as their companion as long as that third student separately applied for leave on the same date. Business-rule gap, not a crash; needs a product decision on whether companion links should be mutual/enforced, so I didn't invent a fix. |
| F2 | P2 | `essl_app/models.py` `AttendanceLog` | No DB-level uniqueness constraint on `(user_id, timestamp, punch_state)`. Duplicate-punch protection is entirely application-level (a ±60s window check in `iclock_cdata`, verified working — `test_duplicate_punch_within_60_seconds_is_not_double_logged` passes). This is adequate for the single-writer ADMS ingestion path today, but doesn't protect against out-of-band inserts (e.g. via `manage.py shell` or a future second ingestion path). Adding a real constraint would need a design decision on the exact dedup key (device also matters, e.g. two different gate devices firing near-simultaneously), so flagged rather than changed. |
| F3 | P3 | `essl_app/urls.py:14` | A catch-all `re_path(r'^(?P<path>.*)$', views.debug_log_all)` under `/iclock/` prints every unmatched request's path/method/IP to stdout, unauthenticated, unbounded. Not a data leak (no secrets logged) but will grow log noise indefinitely in production and has no rate limit. Left alone — looks like an intentional debugging aid for eSSL protocol discovery, per its name. |
| F4 | P4 | `hostel_app/views.py:18` / `rooms_app/utils.py:5` | `role_required` is duplicated near-verbatim in two apps instead of shared from one place. Cosmetic/maintainability only. |
| F5 | P4 | `requirements.txt` | Likely-unused packages (`channels*`, `ollama`, `nltk`, `opencv-python`, `pymongo`, `platformio`, `pyserial`, `pyelftools`, `webauthn`) — see §3. Not removed without confirming intent. |

---

## 7. Room / Capacity Logic — Verified

`Room.is_full()` / `get_occupied_beds_count()` / `get_available_beds_count()` (`rooms_app/models.py:29-41`) are the single source of truth for occupancy — used consistently by `allot_student_to_room`, `get_room_details_ajax`, and `room_detail_view`. No duplicated/divergent occupancy calculation was found in templates or JS (they consume the same numbers the view passes them). Tested and **PASS — verified**:

- Allotment fills a 1-capacity room and `is_full()`/`get_available_beds_count()` immediately reflect it.
- A full room rejects a second allotment (`400`, JSON error, no DB change).
- A disabled room rejects allotment regardless of capacity.
- A student already allotted elsewhere cannot be allotted again (no double-booking).
- Unallotting frees the room (`is_full()` flips back to `False`).

(5 tests in `rooms_app/tests.py`, all passing.) Concurrent-request race condition: fixed per BUG-002 above, not empirically raced (SQLite limitation explained there).

---

## 8. Leave Workflow — Verified

Overlap detection (`hostel_app/views.py:404-451`) correctly blocks a new application whose window intersects an existing `pending` or `approved` one for the same student — **PASS — verified** (`LeaveApplicationOverlapTests`). Approval (`update_leave_status`, `hostel_app/views.py:492-528`) correctly flips the student's status (`outing`/`leave`) and writes a `StudentStatusLog` row; rejection correctly leaves the student's status untouched — **PASS — verified** (`LeaveApprovalStatusSyncTests`).

Not independently re-tested but read and found correct: the form-level safety rule restricting P1–E2 female students to leaves with either a parent or a validated companion (`hostel_app/forms.py:113-119`), and the male-student `parent_coming` lockout (`forms.py:63-66`, `108-111`).

Legacy/unused fields found in migrations (QR-code fields added in `0008`/`0009`, never referenced by any current view or template — `qr_code`, `qr_generated`, `LeaveQRCode` model) suggest a QR-based leave-pass feature was started and abandoned. Not a bug (migrations are consistent, `makemigrations --check` is clean), just dead schema — flagged for awareness, not removed (removing a model needs a migration and confirmation nothing external reads it).

---

## 9. eSSL / Biometric Integration

```
Device (ADMS protocol)
   → HTTP POST /iclock/cdata?table=ATTLOG   (essl_app/urls.py, csrf_exempt)
   → iclock_cdata(): parse tab-separated lines, dedupe within ±60s,
     write AttendanceLog, look up Student by student_id__endswith(user_id),
     update Student.status + write StudentStatusLog
   → GET /iclock/getrequest  → tells device "Registry=1", i.e. keep syncing
   → GET /iclock/devicecmd   → always "OK" (no command queue implemented —
     the dashboard's "Test Connection" button (essl_app/views.py:263-294)
     does a raw TCP connect to the device's IP, it does not go through this
     command channel)
```

- Duplicate-punch idempotency: **PASS — verified** (identical replayed ADMS line within 60s produces exactly one `AttendanceLog` row).
- Hostel-In → status reset to `present`: **PASS — verified after fix** (BUG-001).
- Hostel-Out → status set to `leave`/`outing` when an approved leave window covers the punch: **PASS — verified**.
- IP-spoofing via forged header: **FAIL before fix, PASS after fix** (BUG-003).
- Malformed lines (wrong field count, bad timestamp format): caught by the existing `try/except Exception as e: print(...)` around the per-line parse (`essl_app/views.py`) — device still gets `OK`, no crash, no traceback exposed. **PASS — verified by code inspection** (the broad except is intentionally defensive here, appropriately scoped to a single line so one bad line doesn't drop the rest of the batch).
- Unknown `user_id` (no matching student): caught by `except Student.DoesNotExist`, logged to stdout, no crash. **PASS — verified by code inspection**.
- **Physical device behavior (real ZKTeco hardware, actual ADMS handshake quirks, `getrequest` command-queue semantics beyond the stub `Registry=1` response): NOT TESTED — no physical device available in this environment.** Everything above is code-level verification against synthetic ADMS-shaped payloads, not a live device.

`sniffer.py` (top-level script): a standalone raw-socket listener bound to a hardcoded LAN IP (`192.168.137.1`, the default Windows Mobile Hotspot gateway address), not imported by Django, not run automatically. Purpose, per its own comments, is a developer diagnostic to confirm a biometric device is actually sending TCP traffic to the host at all, independent of Django/HTTP parsing. It duplicates none of the ADMS parsing logic (it just prints raw bytes). Left in place — it's inert unless someone runs it directly, and removing a working diagnostic tool without being asked isn't warranted.

---

## 10. Environment / Secrets

- `.env` is listed in `.gitignore` — confirmed (`.gitignore` present, `.env.example` contains only placeholders, no real secrets). No secrets found committed in the two existing commits (`git log` shows only "Initial commit" and a README update).
- `SECRET_KEY` falls back to a hardcoded `'django-insecure-default-key-replace-me'` (`HOSTEL/settings.py:19`) if the environment variable is unset — acceptable as a documented dev fallback since `.env.example` prompts for a real one, but worth knowing this string would ship if someone deploys without setting `.env`.
- `manage.py check --deploy` (run against the current dev `.env`, `DEBUG=True`): reports exactly the warnings expected for a dev/HTTP-only setup (`SECURE_HSTS_SECONDS`, `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `DEBUG=True`) — all standard "you're not HTTPS yet" warnings, not code bugs. These need to be revisited (set `DEBUG=False` and the four secure-cookie/HSTS settings) at actual production deploy time, once real HTTPS termination exists.

---

## 11. Test Coverage Added

Before this audit: **0 tests** (all three `tests.py` were the default Django stub). After: **17 tests, all passing**, covering:

- `hostel_app/tests.py` (8 tests): anonymous/role-based access control on staff views, the no-password login behavior (documenting BUG-004... i.e. the top finding in §4, not a numbered bug since it's not "fixed"), leave overlap rejection, leave approval/rejection status sync.
- `rooms_app/tests.py` (5 tests): capacity enforcement, disabled-room rejection, duplicate-allotment rejection, unallotment.
- `essl_app/tests.py` (4 tests): Hostel-In status reset (BUG-001 regression guard), Hostel-Out status-to-leave, duplicate-punch dedup, X-Forwarded-For spoofing rejection (BUG-003 regression guard).

This is real but **partial** coverage — not attempted (out of scope for the time available): student CRUD/edit form validation, the dashboard aggregation queries, the 3D/AJAX room-selection frontend, admin-panel custom approve/reject URLs, and performance/N+1-query testing at scale (section 27 of your brief) — I did not fabricate benchmark numbers for 1k/10k students; that would need an actual seeded dataset and profiling run, which wasn't done here. `hostel_app/biometric_track_view` (`hostel_app/views.py:531-669`) does an unbounded `Student.objects.all()` Python-side loop to build an ID-lookup map on every request (`views.py:621-625`) — likely fine at current scale, would need profiling to say more, flagged as a probable N+1/scaling concern at high student counts rather than a benchmarked fact.

---

## 12. Regression Verification (after all fixes)

```
manage.py check                        → System check identified no issues (0 silenced)
manage.py makemigrations --check --dry-run → No changes detected (exit 0)
manage.py test hostel_app rooms_app essl_app → Ran 17 tests — OK
```

Manual browser smoke test (real `runserver`, Chromium): login (ID+name, editor role) → dashboard → 3D hostel view → room selection grid → floor/room drill-down → leave management → biometric tracking. All pages returned `200`, rendered their expected content, and produced **zero new browser-console errors or server-side tracebacks** (checked via `preview_logs` after the full walkthrough). Test/seed data created for this walkthrough was deleted afterward.

---

## 13. Bug Table

| ID | Severity | Module | File | Issue | Impact | Fix | Verified |
|---|---|---|---|---|---|---|---|
| BUG-001 | P1 | essl_app | `essl_app/views.py` (`iclock_cdata`) | Missing `Q` import → `NameError` on Hostel-In punch | Students never auto-return to `present` via biometric | Added import, removed unreachable dead branch | Yes — reproduced, fixed, regression test added |
| BUG-002 | P1 | rooms_app | `rooms_app/views.py` (`allot_student_to_room`) | Check-then-act allotment with no lock | Room capacity can be exceeded under concurrent allotment (real DB, not SQLite) | `transaction.atomic()` + `select_for_update()` | Yes — code-level fix, full suite still green |
| BUG-003 | P1/P2 | essl_app | `essl_app/views.py` (`iclock_cdata`) | Trusts client-supplied `X-Forwarded-For` for device identity | Arbitrary student status forgeable by spoofing a trusted device's IP in a header | Use `REMOTE_ADDR` only | Yes — reproduced, fixed, regression test added |
| BUG-004 | P2 | scripts | `verify_data.py` | `.first().room` on possible `None` | Script crashes on any empty batch/gender group | Null-check before attribute access | Yes — reproduced, fixed |
| BUG-005 | P3 | project | `HOSTEL/settings.py` / missing `static/` dir | Spurious `staticfiles.W004` warning | Noise on every management command | Created `static/` | Yes — warning gone |
| TOP-FINDING | P0 (architectural) | hostel_app | `hostel_app/models.py`, `views.py` (`perform_login`) | No password field; login is ID+name only | Full account takeover (incl. editor/staff) by anyone who knows a name+ID | Not fixed — needs your decision, see §4 | Reproduced, documented, not remediated |

---

## 14. Production-Readiness Verdict

**Not production-ready as-is**, primarily because of the authentication gap in §4 — that's a blocking issue for any deployment where the ID+name pair isn't already effectively public/low-value information within a trusted environment. Everything else audited (migrations, CSRF, role-based authorization, room-capacity integrity, the two biometric bugs) is now either verified-correct or fixed-and-verified. Remaining known gaps, all explicitly NOT fixed and NOT fabricated as tested:

- No device-secret authentication on `/iclock/*` (only the header-spoofing vector was closed, §5 BUG-003 caveat).
- No load/performance testing at scale.
- No physical eSSL hardware verification.
- Companion-leave mutuality (F1) and `AttendanceLog` DB-level uniqueness (F2) are business-rule judgment calls, not implemented.
- Frontend deep-interaction testing (3D building click targets, mobile viewport, full AJAX modal flows) was only smoke-tested, not exhaustively covered.

## 15. Files Changed This Session

```
essl_app/views.py     — BUG-001, BUG-003 fixes
essl_app/tests.py     — new tests (was empty stub)
rooms_app/views.py    — BUG-002 fix
rooms_app/tests.py    — new tests (was empty stub)
hostel_app/tests.py   — new tests (was empty stub)
verify_data.py        — BUG-004 fix
static/.gitkeep       — new (BUG-005 fix)
.claude/launch.json   — new (dev-server preview config, not app code)
```

No models, migrations, URLs, or templates were changed. No dependencies were upgraded or removed. All changes are on the `audit-and-hardening` branch; `main` is untouched. Nothing has been committed yet — let me know if you'd like these committed/merged, or if you want the authentication decision (§4) resolved first.
