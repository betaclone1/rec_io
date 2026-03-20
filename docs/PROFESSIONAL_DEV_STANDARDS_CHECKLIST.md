# Professional dev standards checklist (small team / solo)

Research-backed checklist for bringing the repo up to industry norms. Source: best-practices-researcher subagent (2026-03).

---

## 1. Repository structure

| Item | Guidance |
|------|----------|
| **Top-level layout** | Keep `backend/`, `frontend/`, `scripts/`, `docs/`, `tests/` at repo root. Apps and scripts at top level; avoid a single catch-all `src/` unless you adopt a monorepo build. |
| **Backend layout** | Prefer `backend/<pkg>/` with a clear package boundary so backend is installable (`pip install -e .`) and tests run against the installed package; avoids import and path pitfalls. |
| **Where tests live** | **Single `tests/` at repo root** when one test suite covers backend (and optionally integration). Avoid scattering `tests/` inside backend and frontend unless you have separate CI jobs per app. |
| **Where scripts live** | Keep `scripts/` at root with subfolders by purpose (e.g. `scripts/db/`, `scripts/install_deploy/`). Run with PYTHONPATH or from repo root. |
| **Where config lives** | One root-level `config/` for app-agnostic config; app-specific in `backend/.../config/` or next to the app. Avoid duplicate config dirs. |
| **DB migrations** | Single place: e.g. `scripts/migrations/` with runner documented (e.g. `scripts/db/run_migration.py`) in README or runbook. |
| **Docs location** | Root `docs/` for runbooks, architecture, changelog; README at repo root. Avoid deep or duplicate doc trees. |

**Typical layout (aligned with current structure):**

```
repo/
├── backend/
├── frontend/
├── scripts/           # db/, install_deploy/, config/, backup/, manage/, diagnostics/
├── docs/              # Runbooks, architecture, changelog/
├── tests/             # unit/, integration/
├── .env.example
├── README.md
└── .github/workflows/
```

---

## 2. Test directory layout and CI

| Item | Guidance |
|------|----------|
| **Test layout** | One root `tests/` with subdirs: `tests/unit/`, `tests/integration/`; use `test_*.py` or `*_test.py` so pytest discovers them. |
| **Naming** | Stick to `test_*.py` and `test_*` functions; add `__init__.py` only if you need package imports or same-named modules in unit vs integration. |
| **Unit vs integration** | Use **pytest markers** (`@pytest.mark.unit`, `@pytest.mark.integration`) and declare in `pyproject.toml` or `pytest.ini`. Run fast unit on every push/PR; integration in same pipeline or on schedule if slow. |
| **conftest.py** | Shared fixtures in `tests/conftest.py`; integration-only (DB, env) in `tests/integration/conftest.py`. |
| **CI** | One workflow: install deps, run **pytest** (e.g. `pytest -m "not integration"` for PRs), **coverage** (`pytest --cov=backend`), **lint** (ruff/flake8). Optional separate job for integration. |
| **Coverage** | Use `pytest-cov` and fail CI on minimum threshold (e.g. `--cov-fail-under=70`); config in `pyproject.toml` or `.coveragerc`. |
| **Import path** | Backend installable (`pip install -e .`) or set PYTHONPATH in CI to repo root so pytest sees same modules as locally. |

---

## 3. Config and env management

| Item | Guidance |
|------|----------|
| **Single source of truth** | One **`.env.example` at repo root** listing every required/optional env var with placeholders and short comments; no secrets. |
| **Document required vars** | README or `docs/SETUP.md`: "Environment variables" section pointing to `.env.example`, required vs optional, and where used. |
| **Avoid secrets in repo** | `.env`, `.env.local`, `*.local` in `.gitignore`; allow only `.env.example` (e.g. `!.env.example`). Never commit keys, passwords, tokens. |
| **Local overrides** | Developers copy `.env.example` → `.env` and fill in; document in README. |
| **CI and production** | CI: set env via platform secrets/variables; production: use secret store or env injection, not a committed file. |

**Example `.gitignore` snippet:**

```gitignore
.env
.env.*
!.env.example
```

---

## 4. Documentation layout

| Item | Guidance |
|------|----------|
| **README at root** | What the repo is, how to run locally (clone, deps, .env, main run command), links to docs. Keep scannable; long procedures → docs/. |
| **Runbooks** | Operational runbooks in `docs/` (e.g. RUNBOOK_DEPLOY.md, RUNBOOK_DB.md) with exact commands and failure steps; link from README. |
| **Changelog** | Single changelog: root `CHANGELOG.md` or `docs/changelog/`; consistent format; update with releases. |
| **Architecture / overview** | One doc in `docs/` (e.g. ARCHITECTURE.md) describing components, data flow, backend/frontend/scripts/DB; link from README. |
| **What belongs where** | README = what and how to run; runbooks = operate and recover; changelog = what changed; architecture = how it's built. Link, don't duplicate. |

---

## 5. Logging

All **new or changed** log calls must follow the project logging standards so logs are consistent, parseable, and professional. Source of truth: `docs/LOGGING_INVENTORY.md` §5.

| Item | Guidance |
|------|----------|
| **Mechanism** | Use the `logging` module only; no `print()` for operational log messages. One formatter per process. |
| **Timestamp** | ISO 8601 with timezone. Use **EST** everywhere (Kalshi and trades use EST). e.g. `2026-03-08T14:30:00-05:00`. Single formatter. |
| **Line format** | `{timestamp} {level} [{logger}] {message}`. Optional key=value or JSON for structured fields. |
| **Errors** | Log level + short description + exception type and message. Traceback at DEBUG or at ERROR for unhandled; use `logger.exception()` where appropriate. Minimal context (e.g. endpoint, symbol); full dumps only at DEBUG. |
| **Startup / restart / heartbeat** | Consistent phrasing across scripts: one line at startup, one line for reconnects/restarts; heartbeats same format when used. |
| **Philosophy (persistent scripts)** | Quiet by default. Log errors/failures, one-line startup, optional one-line outcome per cycle, heartbeat. Routine success → DEBUG or remove. See initiative §4. |
| **Real-time visibility** | Flush after each log so supervisor-captured output appears immediately (no batching). Use a `StreamHandler` that flushes in `emit()`, or `print(..., flush=True)` for legacy print. See initiative §5.8. |
| **Single destination** | No duplication. Supervised scripts log only to stdout (supervisor captures to `logs/{program}.out.log` / `.err.log`). No FileHandler or script-owned log files unless a documented exception. See initiative §5.9. |

When adding or editing logging, adhere to these rules unless an exception is documented. See also `docs/LOGGING_INVENTORY.md` and `docs/LOGGING_INVENTORY.md` “Logging”.

---

## Summary

- **Structure:** Root-level backend, frontend, scripts, docs, tests; backend installable or on PYTHONPATH; migrations and config in predictable places.
- **Tests:** Single `tests/` with unit/ and integration/, pytest markers, conftest; CI runs pytest, coverage (threshold), lint.
- **Config/env:** One `.env.example` at root, documented in README; .env and secrets never committed.
- **Docs:** README = what + quick run; docs/ = runbooks, architecture, changelog; one changelog; link from README.
- **Logging:** All new or changed log calls follow project standards (logging module, ISO 8601 timestamps, one line format, consistent errors/startup/heartbeat, real-time flush). See initiative doc §5 (including §5.8) and 06_conventions_insights “Logging”.

References: [pytest good practices](https://docs.pytest.org/en/stable/goodpractices.html); [GitHub: Building and testing Python](https://docs.github.com/en/actions/how-tos/writing-workflows/building-and-testing/building-and-testing-python).
