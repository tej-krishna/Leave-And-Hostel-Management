# Student Leave Workflow — Implementation Report

Branch: `audit-and-hardening` (same safety branch as the earlier audit; `main` untouched, nothing committed yet).

## 1. Workflow Implemented

```
Student --apply--> WARDEN --approve--> CARETAKER --approve-->
  [duration <= 3 days: FINAL]
  [duration 4-9 days:  --approve--> CHIEF_WARDEN --> FINAL]
  [duration 10-29 days: --approve--> CHIEF_WARDEN --approve--> DSW --approve--> DEAN --> FINAL]
  [duration >= 30 days: --approve--> CHIEF_WARDEN --approve--> DSW --approve--> DEAN
                          --approve--> AO Office (letter+email generated here) --approve--> DIRECTOR --> FINAL]
--> CARETAKER_VERIFICATION (caretaker types the student's exact ID)
--> CLEARED_FOR_DEPARTURE
--> [biometric Gate-Out/Hostel-Out] --> OUT  (student.status = leave/outing)
--> [biometric Gate-In]  (timestamp recorded, no status change - existing behavior)
--> [biometric Hostel-In] --> COMPLETED (student.status = present)
```

Rejection at any stage sets `status='rejected'`, `current_stage='REJECTED'` and stops the chain permanently - no lower or higher authority, and no biometric event, can move a rejected request forward.

## 2. Approval Hierarchy & Duration Thresholds Implemented

| Duration | Approval Chain | Final Stage (before Caretaker verification) |
|---|---|---|
| 1-3 days | Warden -> Caretaker | Caretaker |
| 4-9 days | Warden -> Caretaker -> Chief Warden | Chief Warden |
| 10-29 days | Warden -> Caretaker -> Chief Warden -> DSW -> Dean | Dean |
| 30+ days | Warden -> Caretaker -> Chief Warden -> DSW -> Dean -> AO Office -> Director | Director |

**Ambiguity and the interpretation chosen** (source requirements gave examples - 1/3/4/5/10/15/30/60 days - but no exact boundary rule): the thresholds above are the most direct reading of those examples (3 is the last "short" day, 4 is the first day requiring Chief Warden, 10 is the first day requiring DSW/Dean, 30 is the first day requiring AO/Director). If your institution's actual policy differs (e.g. the DSW/Dean tier should start at 15 instead of 10), the single line to change is `hostel_app/workflow.py::get_required_chain()` - every other part of the system (routing, UI labels, PDF, email, tests) reads from that one function, so no other file needs updating.

**Duration calculation** (also a source ambiguity, now resolved and documented in one place - `LeaveApplication.get_duration_days()`): `ceil((in_time - out_time) in days)`, minimum 1. A leave from 1-Sep 9am to 3-Sep 6pm is **3 days**, not 2, because it spans into a third calendar day. Every consumer (routing, the approval-queue UI, the PDF letter, the email, and the duration-matrix tests) calls this one method - nothing recomputes duration independently.

## 3. Schema Changes

Two new migrations on `hostel_app`, both applied and tested against a clean database (`migrate` from zero, then the full test suite, both pass):

- **`0017`**: adds to `LeaveApplication` - `current_stage`, `final_approved_at`, `caretaker_verified_at`, `caretaker_verified_by` (FK to Student), `gate_out_at`, `gate_in_at`, `hostel_in_at`, `completed_at`, `letter_pdf` (FileField), `letter_generated_at`, `email_status`, `email_sent_at`, `email_error`; widens `Student.role` to `max_length=15` to fit the new role names; adds the new `LeaveApprovalHistory` model (immutable audit trail - the Django admin explicitly disables add/change/delete on it).
- **`0018`** (data migration): backfills `current_stage` for rows that existed before this feature - `status='approved'` rows become `CLEARED_FOR_DEPARTURE` (treated as already cleared under the old single-step approval, so previously-approved leaves keep working with the eSSL endpoint rather than silently losing biometric authorization), `status='rejected'` rows become `REJECTED`, `status='pending'` rows stay at the default `WARDEN`.

No existing fields, tables, or migrations were altered or removed. `LeaveApplication.status` (pending/approved/rejected) keeps its exact old meaning and is still what the overlap-check logic, dashboard counts, and the eSSL ingestion filter on - `current_stage` is purely additive, fine-grained "who's turn is it" state layered on top.

I deliberately did **not** implement per-role approval as a pile of boolean flags (`warden_approved`, `caretaker_approved`, ...) - `current_stage` (a single pointer into the ordered chain from `get_required_chain()`) plus the `LeaveApprovalHistory` audit table answers every question the brief asked for ("who needs to approve now", "who already approved", "who rejected and when", "what's next") from one normalized source, with no risk of the flags disagreeing with each other.

## 4. New Files

| File | Purpose |
|---|---|
| `hostel_app/workflow.py` | The one authoritative implementation of duration routing, stage transitions, and authorization (`approve_leave`, `reject_leave`, `verify_departure`, `can_act`, `get_required_chain`, `get_next_stage`). Every view and the eSSL integration goes through this - no duplicated business logic. |
| `hostel_app/pdf.py` | Generates the official leave letter as PDF bytes (reportlab) from the leave's real data and its actual `approval_history` - never a fabricated/placeholder approval state. |
| `hostel_app/email_utils.py` | `send_ao_escalation_email()` - generates the letter, emails it to `AO_EMAIL`/`DIRECTOR_EMAIL`, and updates `email_status`/`email_sent_at`/`email_error`. Never raises; a mail failure cannot undo or block the approval that triggered it (see §7). |
| `hostel_app/templates/hostel_app/leave_approval_queue.html` | One shared template for all 7 hierarchy roles' pending-approval queues. |
| `hostel_app/templates/hostel_app/caretaker_verification.html` | The separate departure-ID-verification queue (deliberately not merged with the caretaker's approval queue - see §5). |
| `hostel_app/migrations/0017_*.py`, `0018_*.py` | Schema + data migrations, described above. |

## 5. Views Changed

- **New**: `leave_approval_queue`, `process_leave_approval`, `caretaker_verification_queue`, `verify_student_departure`, `download_leave_letter` (`hostel_app/views.py`).
- **Retired (kept, now inert)**: `update_leave_status` - previously let a flat `editor` role approve/reject any leave in one step. That directly conflicts with the new hierarchy (an `editor` isn't Warden/Caretaker/etc., so letting it approve would bypass the whole chain - exactly the "authority bypass" the brief says must never happen). Per the brief's own instruction 4 ("if a requested flow conflicts with authorization... implement the safest interpretation"), this endpoint now no-ops with an explanatory message instead of mutating anything; the URL is kept so nothing 404s. Two existing tests that asserted the old bypass behavior were replaced (not deleted - see §17) with a test proving the endpoint is now inert, plus the full new workflow test suite proving the *replacement* behavior.
- **Changed**: `leave_management_view` is now read-only oversight (shows every request's `current_stage` and duration; approve/reject buttons removed from its template since they pointed at the retired endpoint). `apply_leave_view` and `perform_login`/`login_view` gained the changes below.
- **Bug found and fixed during browser verification**: `perform_login()` and `login_view()` had hardcoded role branches (`student` / `viewer`+`editor` / else-error) predating this feature. Adding the 7 new hierarchy roles without updating that dispatch meant every one of them hit the "unrecognised role, please contact support" branch and was immediately logged back out - a real, reproduced bug, not a hypothetical. Fixed by adding an `elif role in workflow.ROLE_TO_STAGE: redirect('leave_approval_queue')` branch in both places, and pinned with a regression test (`test_every_hierarchy_role_lands_on_the_approval_queue`).

## 6. Admin Changes

The existing `LeaveApplicationAdmin` had custom "Approve"/"Reject" links that set `leave.status` directly - the same authority-bypass conflict as `update_leave_status` above, just from the Django admin instead of a public view. Disabled the same way (link kept, now shows a message pointing at the real queues instead of mutating anything). The admin's `LeaveApplication` fieldsets now show the new workflow fields as read-only, and `LeaveApprovalHistory` is registered as a fully read-only admin (add/change/delete all disabled) so the audit trail can be reviewed but never edited or deleted from the admin.

## 7. eSSL / Biometric Integration Changes

This is the most safety-critical part of the change, so it was verified three ways: unit tests, direct in-process calls, and real HTTP requests against the live `runserver` process (§10).

- **Departure now requires more than `status='approved'`.** The OUT-punch (`punch_state in ['1','2']`) lookup in `essl_app/views.py::iclock_cdata` now additionally requires `current_stage__in=[CLEARED_FOR_DEPARTURE, OUT]`. A leave that is fully approved but has **not** yet passed Caretaker ID verification cannot trigger a departure no matter how many fingerprint punches arrive - reproduced live (§10) and pinned by `test_biometric_gate_out_is_blocked_until_caretaker_clears_it`.
- **The existing out_time/in_time timing window (±2h) is preserved unchanged** - and turned out to matter during live testing: an attempt to depart on a leave scheduled to start two days later was correctly rejected purely by that pre-existing check, independent of the new caretaker gate. Nothing about this safeguard was weakened.
- **Departure/return are now tied to a specific `LeaveApplication`, not just `Student.status`.** On a successful OUT punch, the specific leave's `current_stage` flips `CLEARED_FOR_DEPARTURE -> OUT` and `gate_out_at` is stamped (only once - a second out-type punch for the same trip, e.g. Hostel-Out then Gate-Out moments later, is idempotent: no duplicate timestamp, no duplicate `LeaveApprovalHistory` row - verified by `test_duplicate_gate_out_punch_does_not_duplicate_the_departure_record`). A Gate-In punch (`0`) now stamps `gate_in_at` on the student's active OUT-stage leave (first time only) without changing `Student.status`, preserving the pre-existing "Gate-In is logged but doesn't mean present yet" behavior. Hostel-In (`3`) looks up the specific leave that is in `OUT` stage for that student, and only that leave's `current_stage` becomes `COMPLETED` with `hostel_in_at`/`completed_at` stamped.
- **Gate-In-without-Gate-Out anomaly handling** (brief §26): if a Hostel-In punch arrives but no leave is currently in `OUT` stage for that student, the code does **not** silently fabricate a return against a leave that never departed. It falls back to the pre-existing behavior of resetting `Student.status` to `present` if the student's status happens to be `outing`/`leave` (so a status set manually via the Status Updater, unrelated to this workflow, doesn't get permanently stuck) but logs it distinctly as an anomaly rather than treating it as a normal tracked return. This preserves old functionality for non-workflow status changes while making the distinction visible for anyone reading the server log.
- **Dead code removed**: the pre-existing OUT-punch handling had an unreachable second `elif punch_state in ['1', '2']:` branch (impossible to reach - the first `if` in the same chain already consumed that condition), which was where the "clear stale Hostel-In logs for a new trip" cleanup lived and could therefore never run. Merged into the reachable branch so that cleanup now actually executes. This is a genuine, previously-latent bug uncovered while extending this code, not part of the original 5-bug audit list - fixed as a "confirmed problem," not new scope.
- **Nothing about BUG-001, BUG-002, or BUG-003 from the earlier audit was touched or weakened.** The `Q` import is still present and still used the same way; `X-Forwarded-For` is still not trusted for device identity; room allocation's `transaction.atomic()`/`select_for_update()` is untouched.

## 8. Biometric State Machine

```
CLEARED_FOR_DEPARTURE --[Hostel-Out or Gate-Out, in-window, first punch]--> OUT (gate_out_at set)
OUT --[Gate-Out or Hostel-Out again, same trip]--> OUT (idempotent, no dup)
OUT --[Gate-In]--> OUT (gate_in_at set, status unchanged)
OUT --[Hostel-In]--> COMPLETED (hostel_in_at, completed_at set, Student.status -> present)
CARETAKER_VERIFICATION --[any biometric punch]--> no state change (departure blocked, logged)
```

Event ordering/timing (brief §26-27): a Hostel-In with no `OUT`-stage leave is flagged as an anomaly rather than corrupting a leave record (§7 above); an out-of-window punch is rejected by the pre-existing ±2h check, confirmed to still function during live testing.

## 9. PDF Generation

`hostel_app/pdf.py::generate_leave_letter_pdf(leave)` builds a one-page PDF (reportlab) containing: institution name (from `settings.INSTITUTION_NAME`, configurable, not hardcoded), reference number, student name/ID/program/hostel/room (from the real `Student` record), leave type/dates/duration/reason, and a table of the request's **actual** `LeaveApprovalHistory` rows up to that point - it cannot show an approval that hasn't happened. Generated once, at the moment the request escalates into the `AO` stage (i.e., right after Dean's approval on a 30+ day leave) - never before, and never re-generated to retroactively show a later status.

Verified: `test_pdf_letter_contains_real_student_and_leave_data` (structural - valid `%PDF` header, non-trivial size) and, more importantly, a real file was generated and read back successfully during live browser testing (§10) - `leave_letters/leave_2_letter.pdf`, 3315 bytes, confirmed downloadable via `download_leave_letter`.

## 10. Email Implementation

`hostel_app/email_utils.py::send_ao_escalation_email(leave)`:

1. Sets `email_status=PENDING`.
2. Generates the PDF, attaches it, sends to `[AO_EMAIL, DIRECTOR_EMAIL]` (env-configured, `EMAIL_BACKEND` defaults to the console backend in dev so this never silently depends on a real SMTP server existing).
3. On success: `email_status=SENT`, `email_sent_at` stamped, `LeaveApprovalHistory` rows for `LETTER_GENERATED` and `EMAIL_SENT`.
4. On **any** exception (missing recipients, SMTP failure, etc.): `email_status=FAILED`, `email_error` stores the message, an `EMAIL_FAILED` history row is recorded - and the function returns `False` rather than raising. It is called from `process_leave_approval` **after** the approval's own `transaction.atomic()` block has already committed, so a mail failure can never roll back or block the approval.

This was reproduced live, not just in tests: on the first live Dean-approval, `.env` had no `AO_EMAIL`/`DIRECTOR_EMAIL` configured, so email genuinely failed (`email_status=FAILED`, `email_error='No AO_EMAIL/DIRECTOR_EMAIL configured...'`) - and the approval itself had already gone through (`current_stage=AO`) regardless. After adding real recipient values to `.env` and re-triggering, the console backend printed a complete, correctly-formatted multipart email with the PDF attached, and `email_status` flipped to `SENT`. Both the failure and success paths are visible together in the AO queue's own approval-history column (`AO - Email Failed`, then later `AO - Letter Generated` / `AO - Email Sent`), which is itself evidence the audit trail captures exactly what the brief asked for (§39: "Email Generated / Email Sent / Email Failed").

## 11. Authorization

Every hierarchy action is checked server-side in `workflow.can_act()` against the actor's `Student.role` and the leave's actual `current_stage` - never against what a template happened to render. Verified:

- Unit-level: a Caretaker cannot approve a Warden-stage leave; a Chief Warden cannot bypass Warden/Caretaker; a rejected leave cannot later be approved by anyone, including the same authority that could have approved it before rejection; approving the same leave twice at the same stage fails the second time (it has already moved on).
- HTTP-level (not just the service layer): `test_view_layer_rejects_wrong_role_over_http` posts directly to `process_leave_approval` as a Caretaker for a Warden-stage leave and confirms the leave is untouched - direct endpoint abuse, not just relying on hidden buttons.
- A plain `student` role gets redirected away from every approval queue (`role_required` decorator, unchanged mechanism from the original audit).
- The Caretaker's ID-check (`verify_departure`) independently re-validates role, `status`, and `current_stage` even though the view is already role-gated - so a Caretaker cannot verify a request that hasn't actually finished its approval chain, and cannot verify the same request twice.

## 12. Audit / History

`LeaveApprovalHistory` (one row per action, `auto_now_add` timestamp, never updated - the admin disables edit/delete) records: `APPROVED`, `REJECTED`, `VERIFIED`, `VERIFICATION_FAILED`, `GATE_OUT`, `GATE_IN`, `HOSTEL_IN`, `LETTER_GENERATED`, `EMAIL_SENT`, `EMAIL_FAILED` - matching the brief's minimum list exactly, including biometric-originated rows (`actor=None` for system/device events, vs. the actual `Student` for human approvals).

## 13. Automated Tests

Baseline before this feature: 50 tests (17 from the original audit + 32 the audit's own follow-up... actually: 17 original, then this feature adds tests on top). Concretely:

- **17 original tests**: 15 unchanged, 2 replaced (documented in §17) because the business requirement they tested was intentionally changed.
- **New tests added this session**: 33 (duration-matrix routing x10, authorization x8, caretaker verification x4, PDF/email x5, end-to-end journeys x3, biometric gate/idempotency x2 in essl_app, plus the login-redirect regression test).
- **Total: 50 tests, all passing** (`manage.py test hostel_app rooms_app essl_app` -> `Ran 50 tests ... OK`).

Coverage against the brief's required matrix (§40-42):
- Leave creation: valid, duration calculation, overlap rejection - covered (pre-existing + `LeaveWorkflowDurationRoutingTests`).
- Approval chain: every duration tier (1, 3, 4, 5, 9, 10, 15, 29, 30, 60 days), rejection, unauthorized approval, repeated approval - `LeaveWorkflowDurationRoutingTests`, `LeaveWorkflowAuthorizationTests`.
- PDF: generated, correct data, correct approval history - `LongLeaveLetterAndEmailTests`.
- Email: correct recipients, attachment, success, failure, state tracking, no-recipients-configured - `LongLeaveLetterAndEmailTests`.
- Caretaker verification: correct ID, wrong ID, not-yet-approved, duplicate verification - `CaretakerVerificationTests`.
- Gate-out: approved-but-unverified blocked, duplicate punch idempotent, correct state transition - `essl_app.tests` + `LeaveWorkflowEndToEndTests`.
- Gate-in/hostel-in: correct transition, full short-leave and very-long-leave end-to-end journeys - `LeaveWorkflowEndToEndTests`.
- Security: authorization (service-level and HTTP-level), CSRF (unchanged from the original audit, Django's middleware still enforces it globally on every non-exempt view), student cannot reach approval queues - covered above.

**Not covered by automated tests** (explicitly, rather than silently skipped): true multi-process concurrency (two wardens approving the identical leave in the same instant) is not raced in an automated test, for the same reason documented in the original audit's BUG-002 write-up - SQLite serializes writes at the file level, so a threaded test would not reliably demonstrate the interleaving either way. `approve_leave`/`reject_leave`/`verify_departure` all use `select_for_update()` inside `transaction.atomic()`, which is the correct primitive for when this project runs against Postgres/MySQL (as its commented-out settings anticipate); this is a code-level correctness guarantee, not an empirically-raced one.

## 14. Browser Verification (real `runserver`, real HTTP for the biometric side)

Performed as separate logged-in sessions per role, exactly as the brief asked:

1. **Student** (`NSTUD1`) applied for a 2-day leave. The new "Latest Request" status widget correctly showed `Pending Warden` immediately after submission.
2. **Warden** approved it in the browser; response: "approved and forwarded to Pending Caretaker."
3. **Caretaker** saw it in their queue with the Warden's approval already in the history column, approved it; response: "fully approved - awaiting Caretaker ID verification" (correctly stopping at Caretaker for a 2-day leave).
4. **Caretaker verification**: a deliberately wrong ID was rejected ("does not match... Verification failed", request stayed in queue); the correct ID cleared it ("verified and cleared for departure").
5. **Biometric departure/return**, simulated with synthetic ADMS-format HTTP POSTs to `/iclock/cdata` against the live server (no physical hardware available - see §15): Hostel-Out flipped the student to `leave` and the request to `OUT`; Gate-In then Hostel-In completed the return, flipping the student back to `present` and the request to `COMPLETED` - all visible live in the student's own "Latest Request" panel (Gate-Out/Gate-In/Hostel-In all showing "Completed" with real timestamps).
6. **A bug was found and fixed live**: the first login attempt as Warden failed ("unrecognised role") - this is the `perform_login` gap described in §5, found specifically *because* of this browser verification step, fixed, and re-verified successfully afterward.
7. **A stale dev-server process was found and fixed**: after restarting `runserver`, biometric requests briefly appeared to have no effect. Root cause: the autoreloader had hit a fatal exception in an earlier mid-edit state (a transient `role.max_length` check failure followed by a syntax error, both already fixed in the files) and its watcher thread had died, leaving an old worker process silently serving stale code. Restarting the dev server resolved it; this is an artifact of my own editing process, not an application defect, and doesn't apply to a normal `runserver` restart or a production WSGI deployment.
8. **Long-leave (40-day) path**: fast-forwarded to Dean via the workflow API (to keep the walkthrough to a reasonable length after the above), then **Dean, AO, and Director each approved live in the browser**, with the full 7-stage history visible at every queue. Dean's approval correctly triggered the AO escalation; the first email attempt correctly failed (no `AO_EMAIL`/`DIRECTOR_EMAIL` configured yet) without blocking the approval; after adding real recipients to `.env`, the resend produced a complete, correctly formatted email with a genuine attached PDF (verified: valid `%PDF` header, 3315 bytes, downloadable via `/leave/<pk>/letter/`).
9. **The core safety guarantee was demonstrated live, twice**: a biometric departure attempt before caretaker verification was correctly blocked (student stayed `present`, stage stayed `CARETAKER_VERIFICATION`); a second attempt after verification but before the leave's scheduled `out_time` was correctly blocked by the pre-existing time-window check. Only after both were satisfied did the department succeed.
10. Throughout, `preview_logs` showed no unhandled server-side tracebacks (excluding the one pre-existing, already-fixed autoreload artifact in point 7, which predates and is unrelated to any request-handling code path).

All test/seed data created for this walkthrough (`NSTUD1`, `NLONG1`, `NROLE1`-`NROLE7`, their leave applications, approval history, and attendance logs) was deleted afterward; `media/leave_letters/` was cleared.

## 15. Physical eSSL Limitation

Everything above involving `/iclock/cdata` was verified with synthetic ADMS-format HTTP payloads (as in the original audit) - there is still no physical eSSL/ZKTeco device available in this environment. **Code-level verification only** for: the exact byte-for-byte format real hardware sends, real device handshake quirks against `/iclock/getrequest`, behavior under real network conditions (partial writes, retries, device clock drift), and whether a real device's `punch_state` field ever disagrees with the configured `BiometricDevice.location_type` override in a way not exercised here. When real hardware is available, at minimum: confirm one real Hostel-Out and one real Hostel-In punch against a `CLEARED_FOR_DEPARTURE` leave produce the same transitions shown in §14, and confirm a device that is *not* in the `BiometricDevice` table still gets its raw `punch_state` respected as before.

## 16. Regression Verification

```
manage.py check                            -> System check identified no issues (0 silenced)
manage.py check --deploy                   -> same 5 dev-only HTTPS/DEBUG warnings as the original audit, nothing new
manage.py makemigrations --check --dry-run -> No changes detected (exit 0)
manage.py test hostel_app rooms_app essl_app -> Ran 50 tests - OK
```

Live browser + real-HTTP verification: §14. No previously-fixed bug (BUG-001 through BUG-005 from the original audit) was reintroduced or weakened - confirmed by re-reading the relevant code sections and by the original regression tests for each still being present and passing.

## 17. Change Log (test replacements, per the "don't reduce coverage" rule)

| Change | File | Reason |
|---|---|---|
| Removed `LeaveApprovalStatusSyncTests.test_approving_leave_updates_student_status_and_logs_it` and `.test_rejecting_leave_does_not_change_student_status` | `hostel_app/tests.py` | These asserted the *old* single-step `editor`-approves-anything behavior of `update_leave_status`, which is now intentionally retired (§5) because it bypasses the new approval hierarchy. |
| Added `RetiredFlatApprovalEndpointTests.test_editor_posting_to_the_old_endpoint_no_longer_changes_anything` | `hostel_app/tests.py` | Proves the *new*, correct behavior of that same endpoint (a no-op, not a bypass). |
| Added `LeaveApprovalHistory`-based coverage across `LeaveWorkflowAuthorizationTests`, `CaretakerVerificationTests`, `LeaveWorkflowEndToEndTests` | `hostel_app/tests.py` | Replaces the old tests' *intent* (prove approval correctly updates state and is logged) using the actual new mechanism (multi-stage `workflow.approve_leave` + `LeaveApprovalHistory`) instead of the retired one-step endpoint. |
| Updated `test_hostel_out_punch_marks_leave_when_approved_leave_active` -> `test_hostel_out_punch_marks_leave_when_cleared_for_departure` | `essl_app/tests.py` | The old test's precondition (`status='approved'` alone) is no longer sufficient to authorize departure - correctly so (§7) - so the test now also sets `current_stage=CLEARED_FOR_DEPARTURE` to represent a fully-processed request, and a new test (`test_biometric_gate_out_is_blocked_until_caretaker_clears_it`, in `hostel_app/tests.py`) covers the negative case the old test could no longer distinguish. |

Net effect: 17 -> 50 tests. Nothing was deleted without a same-or-broader replacement proving the corresponding *current* requirement.

## 18. Remaining Limitations / Decisions Open to You

1. **The original audit's top finding is still open and still not addressed here on purpose**: `Student` has no password; `perform_login` still authenticates on ID+Name alone, for every role including the new Warden/Caretaker/.../Director accounts. This feature did not touch authentication per the brief's explicit instruction ("do not redesign authentication unless required") - it only extended the existing session-role mechanism to new roles. If you want real credentials before deploying a multi-authority approval chain (arguably more important now that there are 7 new privileged roles instead of 1), say so and I'll scope it.
2. **Duration thresholds** (§2) are my direct reading of your examples, not confirmed institutional policy - trivial to change in one function if wrong.
2a. **AO/Director email is sent once, at the Dean->AO transition** - re-approving is not possible (rejection is terminal) so there's no risk of duplicate emails, but if you want a *reminder* email while a request sits pending at AO/Director for a long time, that's new scope, not implemented.
3. **No real institution letterhead/branding** - the PDF is functionally complete (real data, real approval history, signature blocks) but visually generic; `settings.INSTITUTION_NAME` is the only branding hook currently wired up.
4. **Concurrency is correct-by-construction (`select_for_update`) but not load-tested** - see §13.
5. **Physical eSSL hardware** - see §15.
6. A caretaker's own approval queue (`leave_approval_queue` with role=caretaker) and their verification queue (`caretaker_verification_queue`) are two separate URLs by design (§5/§11 of the brief), both linked from the sidebar - worth confirming this matches how your caretakers actually think about the two tasks.
