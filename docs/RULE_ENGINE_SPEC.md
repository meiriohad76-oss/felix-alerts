# Sentinel Rule Engine Spec

Purpose: define the implementation contract for Sentinel's methodology engine. This spec resolves the gaps between the Felix Methodology Playbook, the Sentinel PDD, and the current triage prototype so engineering can build deterministic rules before adding more UI.

Scope: v1 manual-enforcement MVP. Sentinel reads portfolio CSV files, inserts portfolio tickers automatically, attaches the complete applicable playbook alert set to each ticker, evaluates rules, creates explanatory alerts, and creates copy-pasteable order tickets where appropriate. It does not place or modify broker orders in v1.

## Product Contract

Sentinel is not a general trading assistant. It implements one fixed methodology:

- It evaluates only the documented methodology rules.
- It never emits alerts that are not tied to a rule ID.
- It treats exits and profit-lock raises as explicit action items.
- It allows acknowledgement for auditability, but ignored or stale required actions count against discipline.
- It uses daily end-of-day data for rule evaluation unless a rule explicitly says otherwise.
- It supports multiple portfolios per user. Each portfolio has its own CSV import history, ticker set, alert subscriptions, alerts, scorecard, and reports.
- It explains every triggered alert with: what triggered, the related playbook rule, the rule rationale, the evidence, and the recommended user action.

Required disclaimer text for every screen and email:

> Sentinel is software that follows a published methodology. It is not investment advice. You are responsible for your own trading decisions.

## Terminology

Use these names consistently in code and UI:

| Term | Definition |
|---|---|
| Exit MA | The rule-specific SMA used as the exit reference: SMA-150 for Investor positions, SMA-50 for Trader positions. |
| Profit lock | The current protective stop level. In v1 this is a tracked suggestion/order ticket, not broker state. |
| Rule trigger | A new event that fires an alert, such as today's close crossing below the exit MA. |
| Rule state | A current condition, such as a position already being below the exit MA during onboarding. |
| Violation | A condition showing the methodology was not followed or protection is missing. |
| Ticket | A copy-pasteable manual broker instruction generated from an alert. |
| Portfolio ticker | A ticker imported into a specific portfolio, with optional holding metadata such as shares and entry price. |
| Alert subscription | The dormant rule-monitoring record created for a portfolio ticker. It becomes an alert only when its rule triggers or its state is active. |
| Alert explanation | User-facing content generated from playbook rule metadata and rule evidence. |

## Portfolio CSV Intake

Sentinel supports multiple portfolios per user. A portfolio is created manually, then populated by CSV upload. The CSV can be as small as one `ticker` column, but richer files improve position-aware alerts.

Minimum CSV:

```csv
ticker
AAPL
MSFT
PLUG
```

Recommended CSV:

```csv
ticker,type,shares,entry_price,entry_date,current_profit_lock,notes
AAPL,investor,25,184.20,2025-11-03,176.50,Core account
PLUG,trader,1200,14.22,2025-08-11,,Imported from growth basket
VOO,index,40,438.10,2024-01-08,,Long horizon
```

CSV import behavior:

1. Normalize ticker symbols: trim whitespace, uppercase, remove duplicate rows within the same portfolio.
2. Validate symbols against market-data lookup.
3. Upsert portfolio tickers by `(portfolio_id, ticker)`.
4. Preserve previous ticker records not present in the newest CSV unless the user chooses "replace portfolio contents."
5. Auto-classify missing `type` values using C1.
6. Create all applicable alert subscriptions for every imported ticker.
7. Fetch/backfill market data needed by those subscriptions.
8. Run immediate evaluation and create alerts only for rules that are triggered or state-active.
9. Store an import report with accepted rows, rejected rows, warnings, created tickers, updated tickers, and subscriptions created.

Ticker-only rows are allowed. Rules that require holdings metadata should still be subscribed, but they return "needs metadata" rule-violation or setup alerts instead of silently failing.

## Playbook Rule Metadata

Every supported rule must have metadata in a database table or versioned fixture so alerts can explain the methodology without hard-coding copy in the UI.

```python
@dataclass(frozen=True)
class PlaybookRule:
    rule_id: str
    title: str
    pillar: Literal["classify", "protect", "take_profits", "automate"]
    short_summary: str
    rationale: str
    trigger_template: str
    recommended_action_template: str
    applies_to: tuple[str, ...]
    severity_default: str
    source_section: str

@dataclass(frozen=True)
class AlertExplanation:
    alert_id: UUID
    rule_id: str
    title: str
    what_triggered: str
    rule_rationale: str
    evidence: dict
    recommended_action: str
    source_section: str
```

Alert explanation requirements:

- `what_triggered` is generated from the rule result payload, not generic copy.
- `rule_rationale` is a concise playbook-derived explanation, not a market opinion.
- `recommended_action` must map to the rule's action verb: Sell, Investigate, Raise stop, Review/fix, Read.
- The UI must show the rule ID and title next to the explanation.
- The explanation must be generated server-side so email, push, PDF, and dashboard all agree.

## Data Contract

All rule evaluation receives a pure input object. The engine must not call market-data vendors, brokers, databases, clocks, notification systems, or LLMs.

```python
@dataclass(frozen=True)
class Bar:
    date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adj_close: Decimal
    volume: int

@dataclass(frozen=True)
class Pivot:
    date: date
    kind: Literal["high", "low"]
    price: Decimal
    strength: int

@dataclass(frozen=True)
class PortfolioTickerView:
    portfolio_id: UUID
    portfolio_ticker_id: UUID
    position_id: UUID | None       # None for ticker-only/watch rows
    user_id: UUID
    account_ids: tuple[UUID, ...]
    ticker: str
    type: Literal["investor", "trader", "index", "unknown"]
    status: Literal["active", "inactive", "closed"]
    entry_date: date | None
    entry_price: Decimal | None
    shares: Decimal | None
    current_profit_lock: Decimal | None
    user_exit_price: Decimal | None
    margin_used: bool
    bars: tuple[Bar, ...]          # trailing 250+ sessions, ascending by date
    swing_pivots: tuple[Pivot, ...]

@dataclass(frozen=True)
class AlertSubscriptionView:
    subscription_id: UUID
    portfolio_id: UUID
    ticker: str
    rule_id: str
    enabled: bool
    config: dict

@dataclass(frozen=True)
class RuleResult:
    portfolio_id: UUID
    subscription_id: UUID | None
    rule_id: str
    kind: Literal[
        "exit",
        "distribution",
        "raise_lock",
        "rule_violation",
        "gate_blocker",
        "gate_warning",
    ]
    severity: Literal["info", "warning", "critical", "blocker"]
    triggered: bool
    state_active: bool
    suggested_action: str
    payload: dict
```

## Shared Computations

Use adjusted close for moving averages and drawdown calculations unless the rule needs intraday OHLC fields.

```python
sma50[t] = mean(adj_close[t-49:t])
sma150[t] = mean(adj_close[t-149:t])
volume_sma50[t] = mean(volume[t-49:t])
drawdown_from_entry = (adj_close[t] / entry_price) - 1
```

Cross below logic:

```python
crossed_below(series, reference, t) =
    series[t - 1] >= reference[t - 1]
    and series[t] < reference[t]
```

Current below logic:

```python
below_reference(series, reference, t) =
    series[t] < reference[t]
```

Buffer policy for v1:

```python
default_stop_buffer_pct = 0.01
buffered_price(price) = price * (1 - default_stop_buffer_pct)
```

Open question for v1.1: replace the fixed 1% buffer with `1 * ATR(14)` once ATR behavior is validated against golden fixtures.

## Evaluation Order

For an open non-index position:

1. Validate enough bars exist for its exit MA.
2. Compute SMA-50, SMA-150, volume baseline, and drawdown.
3. Evaluate P1/P2 exit trigger and exit state.
4. Evaluate P7 distribution.
5. Evaluate P3/T4 profit-lock raise.
6. Evaluate T5 rule violation.
7. Generate tickets for actionable alerts.

For a ticker-only portfolio symbol:

1. Validate enough bars exist for SMA and volume rules.
2. Evaluate market-only alerts where possible, such as P7 distribution.
3. Evaluate P1/P2 state only after the ticker has a type.
4. Emit setup violations for missing type, shares, entry price, or profit lock when a subscribed rule needs that metadata.
5. Do not create sell tickets unless shares or account allocations are known.

For an index position:

- Skip P1, P2, P3/T4, and T5.
- P7 can be informational only if implemented in v1.

## Rule Matrix

### C1 Position Type Classification

| Field | Spec |
|---|---|
| Rule ID | C1 |
| Applies to | New and imported positions |
| Trigger condition | Missing `type` on an open individual equity position |
| State condition | `type not in {"investor", "trader", "index"}` |
| Alert kind | `rule_violation` for imported/open positions; `gate_blocker` for new entries |
| Severity | `blocker` |
| Action | Classify as Investor, Trader, or Index |
| Payload | `ticker`, `position_id`, candidate classifier output, classifier reason |
| Ticket | None |
| Dedupe | One open classification violation per position |

Heuristic default:

- `index` if ticker is in the approved broad-market ETF list.
- `trader` if 60-day realized volatility is greater than 35% or sector/category is high-beta growth/biotech/AI/post-IPO.
- `investor` otherwise.

User override is allowed, but stored with `override_reason`.

### P1 SMA-150 Exit

| Field | Spec |
|---|---|
| Rule ID | P1 |
| Applies to | `type == "investor"` |
| Trigger condition | `crossed_below(adj_close, sma150, asof)` |
| State condition | `adj_close[asof] < sma150[asof]` |
| Alert kind | `exit` |
| Severity | `critical` |
| Action | Sell full position |
| Payload | `ticker`, `close`, `sma150`, `previous_close`, `previous_sma150`, `asof`, `distance_pct` |
| Ticket | Market sell full quantity |
| Dedupe | One open `exit` alert per position until closed or reset |

Onboarding triage uses the state condition even if the crossing happened before Sentinel observed the account.

Ticker-only portfolios:

- If type is known and the ticker is below SMA-150, create a state-active alert explaining that the ticker is not methodology-compliant for a new Investor entry.
- Do not generate a sell ticket without shares.

### P2 SMA-50 Exit

| Field | Spec |
|---|---|
| Rule ID | P2 |
| Applies to | `type == "trader"` |
| Trigger condition | `crossed_below(adj_close, sma50, asof)` |
| State condition | `adj_close[asof] < sma50[asof]` |
| Alert kind | `exit` |
| Severity | `critical` |
| Action | Sell full position |
| Payload | `ticker`, `close`, `sma50`, `previous_close`, `previous_sma50`, `asof`, `distance_pct` |
| Ticket | Market sell full quantity |
| Dedupe | One open `exit` alert per position until closed or reset |

Ticker-only portfolios:

- If type is known and the ticker is below SMA-50, create a state-active alert explaining that the ticker is not methodology-compliant for a new Trader entry.
- Do not generate a sell ticket without shares.

### P3 Recent-Low Refinement

The playbook text contains a formula conflict. For long-only v1, use the corrected monotonic interpretation:

```python
candidate_stop = max(exit_ma[asof], latest_confirmed_swing_low.price)
candidate_stop = buffered_price(candidate_stop)
proposed_profit_lock = max(current_profit_lock or Decimal("0"), candidate_stop)
```

Do not lower an existing profit lock.

| Field | Spec |
|---|---|
| Rule ID | P3 |
| Applies to | `type in {"investor", "trader"}` |
| Trigger condition | A newly confirmed swing low produces `proposed_profit_lock > current_profit_lock` |
| State condition | `proposed_profit_lock > current_profit_lock` |
| Alert kind | `raise_lock` |
| Severity | `warning` |
| Action | Raise profit lock |
| Payload | `ticker`, `current_profit_lock`, `proposed_profit_lock`, `swing_low_date`, `swing_low_price`, `exit_ma`, `buffer` |
| Ticket | Modify stop to proposed profit lock, or place stop if missing |
| Dedupe | One open `raise_lock` per position per swing-low date |

Swing low confirmation v1 default:

- A low is confirmed when its low is lower than the two lows before it and the two lows after it.
- The pivot must be above the relevant exit MA before buffer.

### P4 New Buy Below Exit MA

| Field | Spec |
|---|---|
| Rule ID | P4 |
| Applies to | New position gate |
| Trigger condition | Planned entry/current close is below relevant exit MA |
| State condition | Same |
| Alert kind | `gate_blocker` |
| Severity | `blocker` |
| Action | Reject new position |
| Payload | `ticker`, `type`, `planned_entry_price`, `exit_ma`, `distance_pct` |
| Ticket | None |
| Dedupe | N/A, synchronous validation |

### P5 Never Ignore Sell Rule

| Field | Spec |
|---|---|
| Rule ID | P5 |
| Applies to | Open exit alerts |
| Trigger condition | Exit alert is acknowledged as `ignored`, or open longer than SLA |
| State condition | Required exit remains unplaced/unacknowledged |
| Alert kind | `rule_violation` |
| Severity | `critical` |
| Action | Mark violation and escalate |
| Payload | `ticker`, `exit_alert_id`, `age_hours`, `ack_kind`, `ack_note` |
| Ticket | Existing exit ticket remains attached |
| Dedupe | One P5 violation per exit alert |

Manual-enforcement MVP SLA:

- 24 hours: escalate if unread/unacknowledged.
- 48 hours: mark deferred sell in scorecard.
- 7 days: mark missed unless position is closed.

### P6 This Time Is Never Different

| Field | Spec |
|---|---|
| Rule ID | P6 |
| Applies to | Acknowledgements and UI |
| Trigger condition | `ignored` acknowledgement or modified action with non-rule reason |
| State condition | N/A |
| Alert kind | `rule_violation` or scorecard event |
| Severity | `warning` or `critical` if attached to exit |
| Action | Require typed reason; record scorecard penalty |
| Payload | `alert_id`, `ack_kind`, `ack_note`, reason classification if available |
| Ticket | Existing ticket remains attached |
| Dedupe | One scorecard event per acknowledgement |

The UI may provide `Ignored` only as an audit action. It must never be styled as a neutral option.

### P7 Distribution Alert

| Field | Spec |
|---|---|
| Rule ID | P7 |
| Applies to | Open individual equity positions |
| Trigger condition | `volume[asof] > 5 * volume_sma50[asof] and close[asof] < open[asof]` |
| State condition | Same |
| Alert kind | `distribution` |
| Severity | `warning` |
| Action | Investigate; do not sell unless P1/P2 also fires |
| Payload | `ticker`, `volume`, `volume_sma50`, `volume_multiple`, `open`, `close`, `asof` |
| Ticket | None by default |
| Dedupe | One open `distribution` per position per ISO week |

If P7 and P1/P2 fire on the same day, show P7 as supporting evidence inside the exit alert rather than as a competing primary action.

Ticker-only portfolios:

- P7 is fully supported with only ticker and market data.
- The recommended action is "Investigate distribution; do not enter or add unless the setup still passes the methodology gate."

### T1 Sell First

| Field | Spec |
|---|---|
| Rule ID | T1 |
| Applies to | New position gate and imported open positions |
| Trigger condition | Missing `user_exit_price` or missing `current_profit_lock` |
| State condition | Same |
| Alert kind | `gate_blocker` for new positions; `rule_violation` for imported positions |
| Severity | `blocker` for new positions, `critical` for open positions |
| Action | Require exit/profit-lock price before accepting position |
| Payload | `ticker`, `position_id`, suggested exit MA |
| Ticket | Place stop ticket if position is already open |
| Dedupe | One open missing-protection alert per position |

### T3 Fundamentals Last

| Field | Spec |
|---|---|
| Rule ID | T3 |
| Applies to | New position gate |
| Trigger condition | Fundamentals score below threshold |
| State condition | Same |
| Alert kind | `gate_warning` |
| Severity | `warning` |
| Action | Warn only; fundamentals never block exits |
| Payload | `ticker`, scorecard fields, threshold |
| Ticket | None |
| Dedupe | N/A, synchronous validation |

### T4 Profit Locks

T4 is the user-facing action generated from P3. The underlying computation is P3; the alert and ticket are `raise_lock`.

Additional invariant:

```python
new_profit_lock >= current_profit_lock
```

If the latest computation would lower the stop, return no alert and persist no suggestion.

### T5 One-to-One Recovery Zone

| Field | Spec |
|---|---|
| Rule ID | T5 |
| Applies to | Open individual equity positions |
| Trigger condition | `drawdown_from_entry <= -0.15` and no P1/P2 exit fired today and no existing open exit alert |
| State condition | Same |
| Alert kind | `rule_violation` |
| Severity | `critical` |
| Action | Review missing or misplaced protection |
| Payload | `ticker`, `entry_price`, `close`, `drawdown_pct`, `exit_ma`, `current_profit_lock` |
| Ticket | If no stop/profit lock exists, create place-stop ticket |
| Dedupe | One open T5 violation per position until resolved |

If the position is below its exit MA, prefer the P1/P2 exit alert as primary and include T5 as context.

### T6 Do Not Sell The Top

No independent computation. Enforced by absence:

- No target-price alerts.
- No AI top-calling.
- No sell suggestion without P1/P2/P3/T4/T5/P7 context.

### A1 Broker-Placed Stops

v1 manual-enforcement interpretation:

| Field | Spec |
|---|---|
| Rule ID | A1 |
| Applies to | All open individual positions |
| Trigger condition | Missing tracked profit-lock/stop ticket |
| State condition | `current_profit_lock is None` |
| Alert kind | `rule_violation` |
| Severity | `critical` |
| Action | Place protective stop manually |
| Payload | `ticker`, `suggested_stop`, `basis_rule`, `shares` |
| Ticket | Place stop order ticket |
| Dedupe | One open missing-protection alert per position |

Do not claim broker execution in v1 UI.

### A2 Sunday Cadence

No market signal. It governs scheduling and UX:

- Nightly rule engine runs after US close.
- Sunday report renders after Friday data is final.
- Weekday dashboard defaults to alert inbox, not exploratory trading tools.
- Strategic reviews and watch-list changes happen in Sunday report flow.

### A3 Weekly Watch List

Out of v1 native rule engine unless imported watch-list data is available. If implemented:

- Treat imported watch-list items as data records, not AI picks.
- Validate P4/T1/A5 before allowing a planned entry.

### A4 Six Alert Channels

Allowed alert kinds:

| Kind | Rules | Primary action |
|---|---|---|
| `exit` | P1, P2 | Sell |
| `distribution` | P7 | Investigate |
| `raise_lock` | P3, T4 | Raise stop |
| `rule_violation` | C1, P5, P6, T1, T5, A1, A5, A6 | Review/fix |
| `watchlist` | A3 | Read/review |
| `news` | A4 | Read only |

No other alert kinds are allowed in v1.

### A5 Sizing And Diversification

New position gate:

```python
portfolio_risk_budget = portfolio_value * Decimal("0.01")
position_risk = max(entry_price - exit_price, 0) * qty
position_notional = entry_price * qty

block_if position_notional > portfolio_value * Decimal("0.05")
block_if position_risk > portfolio_value * Decimal("0.015")
warn_if open_individual_positions < 15
warn_if open_individual_positions > 30
```

The playbook target is roughly 1% risk; the PDD allows a hard cap at 1.5% risk. Use 1.5% as the gate blocker and show a warning above 1.0%.

### A6 No Margin

| Field | Spec |
|---|---|
| Rule ID | A6 |
| Applies to | New position gate and account sync |
| Trigger condition | Margin required or detected |
| State condition | `margin_used is true` |
| Alert kind | `gate_blocker` for new trades; `rule_violation` for account state |
| Severity | `blocker` or `critical` |
| Action | Reject sizing requiring margin; warn account is using margin |
| Payload | `account_id`, `ticker`, `cash_available`, `notional`, `margin_used` |
| Ticket | None |
| Dedupe | One account-level margin violation until resolved |

### A7 Broad Index Exemption

| Field | Spec |
|---|---|
| Rule ID | A7 |
| Applies to | `type == "index"` |
| Behavior | Exclude from P1/P2/P3/T4/T5 |
| Payload | Store exemption reason and horizon acknowledgement |

Default broad-market ETF allowlist:

```text
VOO, IVV, VTI, VT, VXUS, ITOT, SCHB, DIA
```

The user can manually classify an ETF as index, but must confirm 10-20 year horizon.

### A8 Tax Is Downstream

No sell rule may use taxes as an input.

Allowed:

- Display informational tax-lot estimate after the alert fires.
- Include account label in ticket.

Forbidden:

- Suppressing or delaying an exit because of taxes.
- Re-ranking exits by tax impact.

## Order Ticket Contract

```python
@dataclass(frozen=True)
class OrderTicket:
    alert_id: UUID
    ticker: str
    account_allocations: tuple[AccountAllocation, ...]
    action: Literal["sell", "place_stop", "modify_stop"]
    qty: Decimal
    order_type: Literal["market", "stop", "stop_limit"]
    stop_price: Decimal | None
    limit_price: Decimal | None
    time_in_force: Literal["day", "gtc"]
    rationale_rule_ids: tuple[str, ...]
    copy_text: str
```

Default ticket generation:

| Alert kind | Ticket |
|---|---|
| `exit` | `sell`, full quantity, market order |
| `raise_lock` | `modify_stop`, full quantity, stop price = proposed profit lock |
| `rule_violation` missing protection | `place_stop`, full quantity, stop price = suggested profit lock |
| `distribution` | No ticket |
| `watchlist` | No direct ticket until gate validates planned entry |
| `news` | No ticket |

Multi-account rule:

- Signal evaluation can aggregate same-ticker positions across accounts.
- Tickets must split by account because orders are placed per broker account.
- Portfolio-level watch/ticker-only alerts must not generate order tickets until the user supplies shares/account context or creates a planned trade through the gate.

## Alert Subscription Contract

CSV import creates alert subscriptions for each portfolio ticker. Subscriptions are the monitoring plan; alerts are the events.

```python
@dataclass(frozen=True)
class AlertSubscription:
    id: UUID
    user_id: UUID
    portfolio_id: UUID
    ticker: str
    rule_id: str
    enabled: bool
    config: dict
    created_from_import_id: UUID
```

Default subscription creation:

| Portfolio ticker state | Subscriptions |
|---|---|
| `type == investor` with holdings | C1, P1, P3/T4, P7, T1, T5, A1, A5, A6, A8 |
| `type == trader` with holdings | C1, P2, P3/T4, P7, T1, T5, A1, A5, A6, A8 |
| `type == index` | C1, A7, informational P7 if enabled |
| ticker-only or blank type | Defaults to investor for portfolio imports; C1, P1, P3/T4, P7, T1, T5, A1, A5, A6, A8 |
| explicit `type == unknown` | C1, P7, setup checks for classification/watchlist rows |
| ticker-only, investor | C1, P1 state monitor, P7, P4 gate monitor |
| ticker-only, trader | C1, P2 state monitor, P7, P4 gate monitor |

Subscriptions must be idempotent. Re-uploading the same CSV cannot duplicate subscriptions or duplicate active alerts.

## Alert Lifecycle

```text
new -> sent -> acknowledged -> resolved
              \-> expired
              \-> missed
```

Allowed acknowledgement kinds:

| Ack kind | Requires note | Scorecard impact |
|---|---:|---|
| `placed` | No | Positive/neutral |
| `placed_with_modification` | Yes | Review |
| `ignored` | Yes | Violation |

Exit alerts:

- Cannot be dismissed without acknowledgement.
- If ignored, create P5/P6 discipline event.
- If open past 48 hours, count as deferred sell.
- If open past 7 days and position remains open, count as missed.

## UI Evidence Requirements

Every alert or triage card must show the computation evidence, not only a verdict.

Exit card minimum:

- Rule ID and name.
- Trigger date.
- Position type.
- Close price.
- Relevant SMA value.
- Distance past exit.
- Shares and account allocation.
- Suggested ticket.
- Current acknowledgement state.
- Playbook explanation: what triggered, rule rationale, and recommended action.

Raise-lock card minimum:

- Rule ID and name.
- Current profit lock.
- Proposed profit lock.
- Swing-low date and price.
- Buffer used.
- Ticket text.

Rule-violation card minimum:

- Rule ID and name.
- Why it is a violation.
- Age since first detected.
- Exact corrective action.

Portfolio/ticker setup card minimum:

- Portfolio name.
- Ticker.
- Missing metadata.
- Subscribed rules that cannot fully evaluate yet.
- Exact data needed to activate full playbook monitoring.

Forbidden v1 UI copy:

- "Execute All Exits"
- "Queue Exit Order"
- "Sentinel sold..."
- "Auto-trade"
- Any wording implying broker order placement

Preferred v1 UI copy:

- "Copy Sell Ticket"
- "Mark Ticket as Placed"
- "Review Exit Ticket"
- "Copy Stop Update"
- "Manual Broker Action Required"

## Golden Fixtures

Build these fixtures before UI work:

| Fixture | Position type | Scenario | Expected result |
|---|---|---|---|
| `p1_cross_below_sma150` | investor | Previous close above SMA-150, current close below | One P1 `exit` alert with market-sell ticket |
| `p1_already_below_onboarding` | investor | Imported position already below SMA-150 | Triage state active and exit ticket |
| `p2_cross_below_sma50` | trader | Previous close above SMA-50, current close below | One P2 `exit` alert |
| `p7_distribution_only` | investor | 5.2x volume, down day, above exit MA | One P7 `distribution`, no ticket |
| `p7_with_exit` | investor | SMA exit and 5x down-volume same day | One primary `exit`; P7 evidence in payload |
| `t4_raise_lock` | trader | Confirmed higher swing low above current lock | One `raise_lock` with modify-stop ticket |
| `t4_no_lowering` | trader | New computed stop below current lock | No alert |
| `t5_drawdown_no_exit` | investor | Down 16%, still above SMA-150, no exit alert | One T5 `rule_violation` |
| `index_exemption` | index | Broad ETF below SMA-150 | No P1/P2/T5 alert |
| `missing_type` | open equity | Imported position with no classification | C1 blocker/violation |
| `missing_profit_lock` | open equity | No current stop/profit lock | A1/T1 violation and place-stop ticket |
| `gate_buy_below_ma` | new trader | Planned entry below SMA-50 | P4 gate blocker |
| `gate_size_too_large` | new equity | Notional above 5% or risk above 1.5% | A5 gate blocker |
| `gate_margin_required` | new equity | Notional requires margin | A6 gate blocker |
| `csv_ticker_only_import` | investor | CSV contains only tickers | Portfolio tickers are created with full default investor subscriptions; no duplicate rows |
| `csv_explicit_unknown_import` | unknown | CSV explicitly sets `type=unknown` | Portfolio tickers are created; C1/setup subscriptions created; no duplicate rows |
| `csv_rich_import_with_holdings` | mixed | CSV contains type, shares, entry, lock | Portfolio tickers and full applicable subscriptions are created |
| `csv_reupload_idempotent` | mixed | Same file uploaded twice | No duplicate tickers, subscriptions, or open alerts |
| `alert_explanation_p1` | investor | P1 alert fires | Explanation contains trigger evidence, rule ID/title, rationale, and sell action |

Each fixture should include:

- Input bars as CSV.
- Position metadata as JSON.
- Expected `RuleResult` JSON.
- Expected ticket JSON if applicable.

## Implementation Sequence

1. Create the pure `signals` package and data classes.
2. Implement shared SMA, volume baseline, cross-below, drawdown, and pivot helpers.
3. Implement P1/P2 with golden fixtures.
4. Implement P7.
5. Implement P3/T4 with monotonic profit-lock invariant.
6. Implement T5.
7. Implement gate validators for C1/P4/T1/A5/A6/A7.
8. Implement alert dedupe and lifecycle.
9. Implement portfolio CSV import and idempotent subscription creation.
10. Implement alert explanation generation from rule metadata.
11. Implement order-ticket generation.
12. Build onboarding/import triage UI from rule state, not only fresh triggers.
13. Build alert detail UI with evidence requirements.
14. Build Sunday report.

## Open Decisions

Resolve before private beta:

1. Confirm the P3 buffer: fixed 1%, ATR(14), or per-position volatility band.
2. Confirm trader/investor classifier threshold and allowed user override UX.
3. Confirm approved broad-index ETF allowlist.
4. Confirm whether ignored exit alerts are counted as rule violations immediately or after 48 hours.
5. Confirm legal review of user-specific order-ticket language.
6. Confirm whether v1 stores user-entered evidence that a broker ticket was actually placed.
7. Confirm required CSV columns for private beta. Recommended: accept ticker-only, but strongly encourage type/shares/entry fields.
8. Confirm whether ticker-only portfolios represent watch lists, holdings, or both in the product language.
