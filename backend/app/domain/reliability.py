from __future__ import annotations

from dataclasses import dataclass
from typing import List, Any


@dataclass
class ReliabilityResult:
    score: int  # 0-100
    band: str  # "High", "Medium", or "Low"
    explanations: List[str]
    has_tight_connection: bool = False


def _get_field(leg: Any, name: str, default):
    # Support both dict-like and object-like legs
    if leg is None:
        return default
    if isinstance(leg, dict):
        return leg.get(name, default)
    return getattr(leg, name, default)


def _clamp(v: float, lo: int = 0, hi: int = 100) -> int:
    v = int(round(v))
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def calculate_reliability(legs: List[Any]) -> ReliabilityResult:
    """Calculate a journey-level reliability score from leg data.

    Each leg may be a dict or an object. Expected leg fields (defaults used
    when missing):
      - historical_on_time_pct (int) -> default 75
      - connection_slack_minutes (int) -> default 15
      - live_delay_minutes (int) -> default 0
      - is_cancelled (bool) -> default False

    Scoring rules (per-leg):
      - start from historical_on_time_pct
      - deduct 20 if connection_slack_minutes < 5
      - deduct 10 if connection_slack_minutes < 10
      - deduct 30 if live_delay_minutes > 10
      - deduct 50 if is_cancelled is True
      - clamp each leg score to 0-100

    Journey score is the average of leg scores. Band mapping:
      - High: score >= 80
      - Medium: 50-79
      - Low: < 50

    Returns a ReliabilityResult with human-readable explanations.
    """
    if not legs:
        # Default conservative value when no leg data is available
        return ReliabilityResult(score=75, band="Medium", explanations=["No legs — default reliability"], has_tight_connection=False)

    leg_scores: List[int] = []
    explanations: List[str] = []

    tight_connection_found = False

    for idx, leg in enumerate(legs, start=1):
        hist = _get_field(leg, "historical_on_time_pct", 75) or 0
        try:
            hist = int(hist)
        except Exception:
            hist = 75

        slack = _get_field(leg, "connection_slack_minutes", None)
        if slack is None:
            # Some callers may not provide a slack value; use large default
            slack = 15
        try:
            slack = int(slack)
        except Exception:
            slack = 15

        live_delay = _get_field(leg, "live_delay_minutes", 0) or 0
        try:
            live_delay = int(live_delay)
        except Exception:
            live_delay = 0

        is_cancelled = _get_field(leg, "is_cancelled", False) or False

        # Start score from historical on-time percent
        score = hist

        # Connection slack penalties (mutually exclusive tiers)
        if slack < 5:
            score -= 20
            explanations.append(f"Tight {slack} min connection - risk of missing transfer")
            tight_connection_found = True
        elif slack < 10:
            score -= 10
            explanations.append(f"Tight {slack} min connection - may be tight")

        # Live delay
        if live_delay > 0:
            explanations.append(f"Current delay reported: {live_delay} minutes")
        if live_delay > 10:
            score -= 30

        # Cancellation
        if is_cancelled:
            score -= 50
            explanations.append("Service cancelled - please check alternatives")

        # Historical explanation
        explanations.append(f"Route historically on time {hist}% of days")

        # Clamp per-leg
        leg_score = _clamp(score, 0, 100)
        leg_scores.append(leg_score)

    # After inspecting all legs, add an overall explanation if any tight connection was found
    if tight_connection_found:
        explanations.append("One or more legs have very tight connections (<5 minutes) — increased risk of missed transfers")

    # Average journey score
    avg_score = int(round(sum(leg_scores) / len(leg_scores)))

    if avg_score >= 80:
        band = "High"
    elif avg_score >= 50:
        band = "Medium"
    else:
        band = "Low"

    # Deduplicate explanations while preserving order
    seen = set()
    deduped_expls: List[str] = []
    for e in explanations:
        if e not in seen:
            seen.add(e)
            deduped_expls.append(e)

    return ReliabilityResult(score=avg_score, band=band, explanations=deduped_expls, has_tight_connection=tight_connection_found)
