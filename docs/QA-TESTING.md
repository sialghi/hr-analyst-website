# QA automation

Routine automated tests use synthetic data only. They do not connect to Railway,
use `backend/hr_app.db`, or send WhatsApp messages to real numbers.

## Test layers

- **Backend business and API tests:** pytest with FastAPI `TestClient` and
  SQLite in-memory. The WhatsApp Cloud API is mocked; webhook tests verify
  handshake validation, malformed payload handling, duplicate-message
  idempotency, and delivery-status events.
- **Browser smoke tests:** Playwright Test exercises HR login/dashboard,
  employee search, branch selection, dashboard contract deep-linking, linked
  PKWT/PHL history edit and delete, leave approval, the PHL form restriction,
  current-year balance view, and bonus/deduction recalculation on the attendance
  result. API responses are intercepted and supplied from synthetic fixtures,
  keeping browser tests independent of credentials or a running backend.
- **CI:** `.github/workflows/qa.yml` runs the backend suite, frontend lint/build,
  and Chromium browser tests. No production secrets are configured in the
  workflow.

## Run locally

From the repository root in PowerShell:

```powershell
Push-Location backend
.\venv\Scripts\python.exe -m pip install -r requirements-test.txt
.\venv\Scripts\python.exe -m pytest -q
Pop-Location

Push-Location frontend
npm ci
npx playwright install chromium
npm run lint:qa
npm run build
npm run test:e2e
Pop-Location
```

The backend pytest fixture creates a separate in-memory database. Playwright
starts an isolated Next.js dev server on port 3001, uses `.next-e2e` as its
output directory, and mocks its API under `/__mock_api`. It does not reuse a
server on port 3000 or modify the configured local HR database. Ensure port
3001 is available.

## Coverage map

| Area | Existing automated coverage | Current test location |
| --- | --- | --- |
| Employee contracts, imports, employee master synchronization, and net summary | Backend regression tests | `backend/tests/test_contracts.py`, `test_summary_net_total.py` |
| PHL-to-PKWT period/contract transition validation and persistence | Backend and browser regression tests | `backend/tests/test_contracts.py`, `frontend/tests/e2e/hr.spec.ts` |
| Leave quota, ledger reconciliation, reversal, and leave rules | Backend business-logic tests | `backend/tests/test_leave_logic.py` |
| Database migration and local employee rebuild safety | Backend migration tests | `backend/tests/test_database_migration.py`, `test_local_employee_rebuild.py` |
| WhatsApp login/menu/profile, automatic post-login guide and `panduan` command, authorization, deduplication, and HR linking | Bot logic and webhook/API contract tests | `backend/tests/test_contracts.py`, `test_qa_api_contracts.py` |
| Payroll slip recipient resolution by employee code, active-link revalidation, individual/bulk delivery results, and delivery history | Synthetic fixtures with mocked WhatsApp and Cloudinary | `backend/tests/test_payroll_whatsapp.py` |
| HR login/dashboard, employee code/NIK search, branch dropdown, employee/WhatsApp page tabs, dashboard-to-contract deep link, linked PKWT/PHL history editing and deletion, leave approval, PHL form restriction, PHL-to-PKWT recap, current-year balance UI, and live Total Bersih recalculation | Browser smoke tests with mocked API | `frontend/tests/e2e/hr.spec.ts` |
| Saving bonus/deduction adjustments and synchronizing the active report workbook and KPI | Backend API/workbook regression tests | `backend/tests/test_process_adjustments.py`, `test_summary_net_total.py` |
| Attendance processing/imports, rules, holidays, users, reports, remote attendance, and additional HR workflows | Existing flows need a feature-by-feature gap review and incremental tests | Backend routes and remaining UI pages |

Browser tests intentionally focus on a few high-value user journeys; business
rules and authorization belong in backend tests. A provider sandbox test is a
separate, opt-in follow-up and must use a dedicated test number and isolated
database before it is added.

The repository-wide `npm run lint` still reports ESLint violations, including
explicit `any` types and React Hooks rule findings in application pages. CI
therefore lints the QA configuration/specs directly rather than claiming the
whole frontend currently passes lint.
