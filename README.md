# Sentinel

Methodology-enforced portfolio monitor.

This workspace currently contains the portfolio monitor core:

- multi-portfolio CSV import semantics
- portfolio file conversion for CSV, TSV, XLSX, and XLSM
- portfolio ticker models
- playbook rule catalog
- alert subscription creation
- indicator helpers
- pure signal engine
- alert explanation rendering
- manual order-ticket generation
- alert email template rendering
- standard-library unit tests
- executable golden fixtures

## Run Tests

```bash
PYTHONPATH=backend python3 -m unittest discover -s tests
```

The full suite includes a browser-level UX test when `node` and a
Chrome-compatible browser are available. The browser test launches headless
Chrome through the Chrome DevTools Protocol and verifies sidebar routing,
tooltip readability, and chart marker decluttering without requiring
Playwright or Selenium.

Run only the browser UX test:

```bash
PYTHONPATH=backend:. python3 -m unittest tests.test_browser_sidebar_ux
```

## Convert Uploaded Portfolio Workbook

```bash
PYTHONPATH=backend python3 scripts/convert_uploaded_portfolio.py /path/to/portfolio.xlsx --output /path/to/portfolio.csv
```

The app can load a selected local `.csv`, `.tsv`, `.xlsx`, or `.xlsm` file into
the import editor. Modern Excel files are converted from a `Holdings` sheet or
another sheet with a `Symbol` column. Legacy binary `.xls` files are rejected
with a clear message until an `.xls` parser dependency or conversion service is
chosen.

## Run Dev API Server

Foreground mode:

```bash
PYTHONPATH=backend python3 scripts/run_dev_server.py
```

The server exposes a small dependency-free development API on
`http://127.0.0.1:8765` backed by `sentinel_dev.sqlite3`.

Open `http://127.0.0.1:8765` in a browser for the local portfolio monitor.

Optional external alert delivery is configured by server environment variables
and portfolio-level settings in the app:

```bash
export SENTINEL_EMAIL_HOST="smtp.example.com"
export SENTINEL_EMAIL_PORT="587"
export SENTINEL_EMAIL_FROM="sentinel@example.com"
export SENTINEL_EMAIL_USERNAME="sentinel@example.com"
export SENTINEL_EMAIL_PASSWORD="your_smtp_password"
export SENTINEL_TELEGRAM_BOT_TOKEN="your_telegram_bot_token"
```

Email recipients and Telegram chat id are saved per portfolio in
Settings & Activity.

Background mode:

```bash
PYTHONPATH=backend python3 scripts/run_dev_server.py --daemon
PYTHONPATH=backend python3 scripts/run_dev_server.py --status
PYTHONPATH=backend python3 scripts/run_dev_server.py --stop
```

If port `8765` is already used, run another port:

```bash
PORT=8766 PYTHONPATH=backend python3 scripts/run_dev_server.py --daemon
```

## Docs

- `docs/RULE_ENGINE_SPEC.md`
- `docs/IMPLEMENTATION_PLAN.md`
- `docs/DECISION_LOG.md`
- `docs/DEPLOYMENT.md`

## Manual GitHub Upload

The repo includes `.gitignore` rules for local databases, logs, PID files,
environment files, caches, and generated artifacts. Before manual upload, run:

```bash
PYTHONPATH=backend:. python3 -m unittest discover -s tests
python3 scripts/validate_upload_package.py
```

Upload source/docs/test/deploy files only. Do not upload `sentinel_dev.sqlite3`,
logs, PID files, `.env` files, or local caches. See `docs/DEPLOYMENT.md`.
