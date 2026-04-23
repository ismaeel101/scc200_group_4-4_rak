from datetime import datetime
from typing import List
import logging
import os
from .weather_stub import get_weather_stub
from .reliability_dto import ReliabilityExplanation
from app.cache.live_reader import get_bus_live, get_rail_live
from .historical_reader import get_historical_stats

HIGH_THRESHOLD = 80
MEDIUM_THRESHOLD = 50
NO_HISTORY_BASE_SCORE = 88
logger = logging.getLogger(__name__)


def _debug_enabled() -> bool:
    return os.environ.get("ENABLE_PLANNER_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}

def _base_score_from_history(stats):
    if not stats or stats.get("available") is False:
        return (
            NO_HISTORY_BASE_SCORE,
            [ReliabilityExplanation(code="HIST_NONE", text="No historical data available; using a conservative fallback.")],
        )

    on_time_pct = stats["on_time_pct"]
    avg_delay = stats["avg_delay"]
    missed_pct = stats["missed_pct"]

    score = int(on_time_pct)
    explanations = [
        ReliabilityExplanation(
            code="HIST_ON_TIME",
            text=f"Historically on time {on_time_pct:.0f}% of days."
        )
    ]

    if avg_delay > 0:
        score -= min(int(avg_delay), 20)
        explanations.append(
            ReliabilityExplanation(
                code="HIST_DELAY",
                text=f"Average delay {avg_delay:.1f} minutes."
            )
        )

    if missed_pct > 0:
        penalty = min(int(missed_pct / 2), 20)
        score -= penalty
        explanations.append(
            ReliabilityExplanation(
                code="HIST_MISSED",
                text=f"Missed connections about {missed_pct:.0f}% of days."
            )
        )

    return max(0, min(100, score)), explanations


def _apply_connection_penalties(score, journey, explanations):
    connection_risk = bool(journey.get("has_connection_risk") or journey.get("has_tight_connection"))
    worst_penalty = 0

    for leg in journey.get("legs", []):
        slack = leg.get("connection_slack_minutes")
        if slack is None:
            continue

        try:
            slack = float(slack)
        except Exception:
            continue

        if slack < 5:
            worst_penalty = max(worst_penalty, 20)
            explanations.append(
                ReliabilityExplanation(
                    code="CONNECTION_TIGHT",
                    text=f"Very tight {int(slack)} minute connection - risk of missing a transfer.",
                )
            )
            connection_risk = True
        elif slack < 10:
            worst_penalty = max(worst_penalty, 10)
            explanations.append(
                ReliabilityExplanation(
                    code="CONNECTION_WARN",
                    text=f"Tight {int(slack)} minute connection - may be tight.",
                )
            )
            connection_risk = True

    if connection_risk and worst_penalty == 0:
        worst_penalty = 10
        explanations.append(
            ReliabilityExplanation(
                code="CONNECTION_RISK",
                text="One or more legs have a connection risk.",
            )
        )

    if connection_risk:
        explanations.append(
            ReliabilityExplanation(
                code="CONNECTION_SUMMARY",
                text="One or more legs have very tight connections (<5 minutes) — increased risk of missed transfers",
            )
        )

    return max(0, score - worst_penalty)


def _apply_live_penalties(score, leg, explanations):
    live = leg.get("live_status")
    if not live or not live.get("available"):
        return score

    delay = live.get("delay_minutes") or 0
    disrupted = live.get("disrupted_flag") or False

    if disrupted:
        explanations.append(
            ReliabilityExplanation(
                code="LIVE_CANCELLED",
                text="This leg is currently disrupted or cancelled."
            )
        )
        return max(0, score - 40)

    if delay > 0:
        explanations.append(
            ReliabilityExplanation(
                code="LIVE_DELAY",
                text=f"Current live delay of {delay} minutes."
            )
        )
        return max(0, score - min(delay, 20))

    return score


def _apply_weather_penalty(score, explanations, journey: dict | None = None):
    # Prefer journey-level weather flag injected by the API. Fall back to stub.
    is_adverse = False
    condition_text = None

    if journey is not None:
        # API attaches 'is_adverse_weather' (bool) and optional 'weather' dict
        try:
            is_adverse = bool(journey.get("is_adverse_weather", False))
            weather_obj = journey.get("weather")
            if weather_obj and isinstance(weather_obj, dict):
                condition_text = weather_obj.get("description")
        except Exception:
            is_adverse = False

    if not is_adverse:
        weather = get_weather_stub()
        if weather.condition == "normal":
            return score
        is_adverse = True
        condition_text = getattr(weather, "condition", None)

    explanations.append(
        ReliabilityExplanation(
            code="WEATHER",
            text=f"Adverse weather: {condition_text or 'adverse'}."
        )
    )
    return max(0, score - 10)


def _band_from_score(score):
    if score >= HIGH_THRESHOLD:
        return "High"
    if score >= MEDIUM_THRESHOLD:
        return "Medium"
    return "Low"


def compute_reliability(journey: dict):
    flags = []
    explanations: List[ReliabilityExplanation] = []

    if _debug_enabled():
        logger.debug("reliability scoring entry: legs=%s depart_time=%s", len(journey.get("legs", [])), journey.get("depart_time"))

    # 1) Live data per leg
    for leg in journey["legs"]:
        mode = leg.get("mode")
        service_id = leg.get("service_id")

        live = None
        if mode == "bus" and service_id:
            live = get_bus_live(service_id)
        elif mode == "rail" and service_id:
            live = get_rail_live(service_id)

        if live is None:
            flags.append("LIVE_MISSING")
            leg["live_status"] = {
                "available": False,
                "delay_minutes": 0,
                "disrupted_flag": False,
                "source": "missing",
            }
        else:
            leg["live_status"] = {
                "available": True,
                "delay_minutes": live.delay_minutes or 0,
                "disrupted_flag": live.cancelled,
                "source": live.source or "live",
            }

    # 2) Historical base score
    first_leg = journey["legs"][0] if journey["legs"] else None
    stats = None
    if first_leg:
        stats = get_historical_stats(
            mode=first_leg.get("mode", "bus"),
            from_id=first_leg.get("from"),
            to_id=first_leg.get("to"),
            depart_time=journey["depart_time"] if isinstance(journey["depart_time"], datetime) else datetime.utcnow(),
        )
    if _debug_enabled():
        if not stats:
            logger.debug("reliability historical stats missing/empty for first_leg=%s", first_leg)
        else:
            logger.debug("reliability historical stats present keys=%s", list(stats.keys()) if isinstance(stats, dict) else type(stats))

    score, hist_expl = _base_score_from_history(stats)
    explanations.extend(hist_expl)
    if stats is None or (isinstance(stats, dict) and stats.get("available") is False):
        flags.append("HISTORICAL_MISSING")

    # 3) Live penalties
    for leg in journey["legs"]:
        score = _apply_live_penalties(score, leg, explanations)

    # 4) Connection penalties (apply even when historical data is missing)
    score = _apply_connection_penalties(score, journey, explanations)

    # 5) Weather penalty (use journey-level weather when available)
    score = _apply_weather_penalty(score, explanations, journey)

    # 6) Band
    band = _band_from_score(score)

    # 7) Attach to journey
    journey["reliability_score"] = score
    journey["reliability_band"] = band
    # Backwards-compatible key expected by tests / callers
    journey["reliability_explanation"] = [e.text for e in explanations]
    journey["reliability_explanations"] = journey["reliability_explanation"]

    if _debug_enabled():
        logger.debug(
            "reliability scoring exit: score=%s band=%s explanations=%s flags=%s",
            score,
            band,
            journey["reliability_explanation"],
            flags,
        )

    return journey, flags
