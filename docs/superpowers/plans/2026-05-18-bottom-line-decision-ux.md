# Bottom-Line Decision UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make stock rows and stock detail pages explain the decision bottom line before showing rule mechanics.

**Architecture:** Keep existing backend rule data unchanged. Add frontend-only helpers in `frontend/index.html` that classify active, setup, near, and watching rows into a decision summary, then use that summary in the urgency list, methodology center, and focused alert cards. Guard the UX with static regression tests in `tests/test_frontend_static.py`.

**Tech Stack:** Python `unittest` static checks, monolithic HTML/CSS/JS frontend, existing Python stdlib server.

---

### Task 1: Static Regression Tests

**Files:**
- Modify: `tests/test_frontend_static.py`

- [ ] **Step 1: Add static tests**

Add tests asserting these strings/functions exist:

```python
def test_bottom_line_decision_ux_is_present(self):
    html = Path("frontend/index.html").read_text()
    self.assertIn("renderDecisionBottomLine", html)
    self.assertIn("decisionSummaryForRows", html)
    self.assertIn("Bottom Line", html)
    self.assertIn("Primary reason", html)
    self.assertIn("Action required", html)
    self.assertIn("Exit signal", html)
    self.assertIn("Not triggered", html)
    self.assertIn("Setup is secondary", html)
    self.assertIn("triggered-rule-grid", html)
    self.assertIn("passive-watch-list", html)
    self.assertNotIn("Breach active", html)
    self.assertNotIn("Triggered now", html)
```

- [ ] **Step 2: Run static tests and verify RED**

Run:

```bash
PYTHONPATH=backend python3 -m unittest tests.test_frontend_static
```

Expected: fail because the bottom-line helpers and labels do not exist.

### Task 2: Decision Summary Helpers

**Files:**
- Modify: `frontend/index.html`

- [ ] **Step 1: Add helper functions near existing alert monitor helpers**

Add:

```javascript
function activeDecisionRows(rows) {
  return rows.filter((row) => ["triggered", "active", "triggered_before"].includes(row.status.status));
}

function marketDecisionRows(rows) {
  return activeDecisionRows(rows).filter((row) => !SETUP_RULE_IDS.has(row.subscription.rule_id));
}

function setupDecisionRows(rows) {
  return rows.filter((row) => SETUP_RULE_IDS.has(row.subscription.rule_id) && isSetupIssueStatus(row.status.status));
}

function decisionSummaryForRows(ticker, rows) {
  const marketRows = marketDecisionRows(rows);
  const setupRows = setupDecisionRows(rows);
  const nearRows = rows.filter((row) => row.status.status === "near");
  const ruleNames = marketRows.map((row) => ruleDisplayLabel(row.subscription.rule_id));
  const primaryReason = ruleNames.length ? ruleNames.join(" + ") : nearRows.length ? `${ruleDisplayLabel(nearRows[0].subscription.rule_id)} is close` : setupRows.length ? "Setup data missing" : "No active trigger";
  const action = marketRows.length ? marketRows[0].action : setupRows.length ? "Complete setup data before treating this holding as fully monitored." : "No action needed right now.";
  const tone = marketRows.length ? "action" : nearRows.length ? "near" : setupRows.length ? "setup" : "clear";
  return { ticker, marketRows, setupRows, nearRows, primaryReason, action, tone };
}
```

- [ ] **Step 2: Update labels**

Change trigger labels:

```javascript
triggered -> Exit signal
active -> Action required
watching -> Not triggered
```

### Task 3: Portfolio Row Bottom Line

**Files:**
- Modify: `frontend/index.html`

- [ ] **Step 1: Add row summary helper**

Add helper that uses `ticker.trigger_summary` and `state.alerts` to output:

```text
Primary reason: Trend exit + loss-limit
Setup is secondary: stop/profit-lock missing
```

- [ ] **Step 2: Render helper in compact rows**

Replace generic row text `Price/risk alert needs review` with the helper output.

### Task 4: Stock Detail Bottom-Line Panel

**Files:**
- Modify: `frontend/index.html`

- [ ] **Step 1: Add `renderDecisionBottomLine(detail, rows)`**

Render a top panel with:

```text
Bottom Line
Action required
Primary reason
Recommended action
Setup is secondary
```

- [ ] **Step 2: Insert before detailed rule cards**

Place the panel immediately after methodology header and before `renderMethodologyActionPanel(...)`.

### Task 5: Simplify Rule Cards

**Files:**
- Modify: `frontend/index.html`

- [ ] **Step 1: Show active rows first**

Change visible rule cards to include only active market rows and near rows. If none exist, show the closest primary watch.

- [ ] **Step 2: Collapse passive watches**

Render watching primary rows inside a collapsed details block with class `passive-watch-list`.

- [ ] **Step 3: Keep raw evidence collapsed**

No raw evidence should be expanded by default.

### Task 6: Verification

**Files:**
- Modify: none

- [ ] **Step 1: Run targeted tests**

```bash
PYTHONPATH=backend python3 -m unittest tests.test_frontend_static
```

- [ ] **Step 2: Run JS syntax check**

```bash
python3 - <<'PY'
from pathlib import Path
html=Path('frontend/index.html').read_text()
start=html.index('<script>')+len('<script>')
end=html.rindex('</script>')
Path('/tmp/felix-index-script.js').write_text(html[start:end])
PY
node --check /tmp/felix-index-script.js
```

- [ ] **Step 3: Run full suite**

```bash
PYTHONPATH=backend python3 -m unittest discover -s tests
```

- [ ] **Step 4: Restart server**

```bash
PYTHONPATH=backend python3 scripts/run_dev_server.py --stop
PYTHONPATH=backend python3 scripts/run_dev_server.py --daemon
```

