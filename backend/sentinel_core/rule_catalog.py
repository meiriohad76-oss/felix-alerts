from __future__ import annotations

from typing import Dict, Iterable

from .models import PlaybookRule


RULES = (
    PlaybookRule(
        "C1",
        "Position Type Classification",
        "classify",
        "Every ticker must be classified as Investor, Trader, or Index before the correct exit rule can apply.",
        "The methodology uses different exit speeds for slower investor positions and faster trader positions. Without classification, Sentinel cannot choose the correct kill line.",
        "{ticker} is missing a methodology classification.",
        "Classify the ticker as Investor, Trader, or Index.",
        ("portfolio_ticker",),
        "blocker",
        "Rule C1",
    ),
    PlaybookRule(
        "P1",
        "150-day Simple Moving Average Exit",
        "protect",
        "Investor positions exit when the daily close crosses below SMA-150.",
        "The SMA-150 is the investor-position support line. Losing it means the position no longer aligns with the methodology's trend-following discipline.",
        "{ticker} closed below its SMA-150.",
        "Sell the full investor position.",
        ("investor",),
        "critical",
        "Rule P1",
    ),
    PlaybookRule(
        "P2",
        "50-day Simple Moving Average Exit",
        "protect",
        "Trader positions exit when the daily close crosses below SMA-50.",
        "Trader positions move faster. The methodology uses SMA-50 as the support line for high-beta names so losses do not grow while waiting for a slower signal.",
        "{ticker} closed below its SMA-50.",
        "Sell the full trader position.",
        ("trader",),
        "critical",
        "Rule P2",
    ),
    PlaybookRule(
        "P7",
        "Volume Confirmation Of Institutional Outflow",
        "protect",
        "A 5x volume spike on a down day signals potential institutional distribution.",
        "Large institutions reveal themselves through abnormal volume. Heavy volume on a down day means sellers are in control and the move deserves attention.",
        "{ticker} traded above 5x normal volume on a down day.",
        "Investigate distribution; do not add unless the setup still passes the methodology gate.",
        ("portfolio_ticker",),
        "warning",
        "Rule P7",
    ),
    PlaybookRule(
        "T1",
        "Sell First",
        "take_profits",
        "No position is complete until its exit/profit-lock level is known.",
        "Pre-committing the exit keeps trading mechanical. Missing exit metadata means the methodology cannot protect the position.",
        "{ticker} is missing entry or exit/profit-lock metadata.",
        "Enter the missing setup data before treating this ticker as fully monitored.",
        ("portfolio_ticker",),
        "critical",
        "Rule T1",
    ),
    PlaybookRule(
        "T4",
        "Profit Locks",
        "take_profits",
        "Raise stops as the trend forms higher swing lows; never lower them.",
        "Profit locks convert paper gains into protected capital without trying to guess the top. The stop only moves upward.",
        "{ticker} formed a higher swing low that supports raising the profit lock.",
        "Copy the stop update ticket into your broker, then mark it as placed.",
        ("investor", "trader"),
        "warning",
        "Rule T4",
    ),
    PlaybookRule(
        "T5",
        "One-to-One Recovery Zone",
        "take_profits",
        "A position down more than 15% without an exit is a rule violation.",
        "Small losses are recoverable. Once losses grow, the required recovery gain expands nonlinearly and capital gets trapped.",
        "{ticker} is down more than 15% without a primary exit alert.",
        "Review missing or misplaced protection immediately.",
        ("investor", "trader"),
        "critical",
        "Rule T5",
    ),
    PlaybookRule(
        "A1",
        "Broker-Placed Stops",
        "automate",
        "Every active holding needs a protective profit-lock/stop level.",
        "The methodology assumes humans freeze under pressure. In v1 Sentinel creates manual stop tickets rather than placing broker orders.",
        "{ticker} has holding metadata but no current profit lock.",
        "Place or record the protective stop for this holding.",
        ("investor", "trader"),
        "critical",
        "Rule A1",
    ),
    PlaybookRule(
        "A5",
        "Sizing And Diversification",
        "automate",
        "Position risk and notional size must stay within portfolio limits.",
        "Sizing by risk prevents one position from damaging the whole portfolio.",
        "{ticker} needs sizing validation.",
        "Review position sizing against the portfolio risk limits.",
        ("portfolio_ticker",),
        "warning",
        "Rule A5",
    ),
    PlaybookRule(
        "A6",
        "No Margin",
        "automate",
        "Margin is disallowed by the methodology.",
        "Leverage can force liquidation at the worst possible moment, turning a recoverable drawdown into a realized loss.",
        "{ticker} or its account indicates margin use.",
        "Remove margin exposure before treating the portfolio as methodology-compliant.",
        ("portfolio_ticker",),
        "critical",
        "Rule A6",
    ),
    PlaybookRule(
        "A7",
        "Broad Index Exemption",
        "automate",
        "Broad index ETFs can be exempt from individual-stock exit rules.",
        "Diversified indices replace failing constituents over time, so they are not treated like individual stocks when the user has a long horizon.",
        "{ticker} is classified as an index exemption.",
        "No individual-stock exit action is required.",
        ("index",),
        "info",
        "Rule A7",
    ),
    PlaybookRule(
        "A8",
        "Tax Is Downstream",
        "automate",
        "Tax impact never suppresses a sell signal.",
        "The methodology treats tax as informational after the rule fires, not as a reason to delay discipline.",
        "{ticker} may have tax context, but tax does not change the rule.",
        "Use tax information only after following the methodology action.",
        ("portfolio_ticker",),
        "info",
        "Rule A8",
    ),
)


def rule_catalog() -> Dict[str, PlaybookRule]:
    return {rule.rule_id: rule for rule in RULES}


def get_rule(rule_id: str) -> PlaybookRule:
    try:
        return rule_catalog()[rule_id]
    except KeyError as exc:
        raise KeyError("Unknown playbook rule: %s" % rule_id) from exc


def list_rules() -> Iterable[PlaybookRule]:
    return RULES

