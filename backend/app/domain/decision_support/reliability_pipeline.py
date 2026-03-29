from datetime import datetime
from typing import List
from .weather_stub import get_weather_stub
from .reliability_dto import ReliabilityExplanation
from app.cache.live_reader import get_bus_live, get_rail_live
from .historical_reader import get_historical_stats

HIGH_THRESHOLD = 80
MEDIUM_THRESHOLD = 50

def _base_score_from_history(stats):
    if not stats:
        return 70, [ReliabilityExplanation(code="HIST_NONE", text="No historical data available.")]

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


def _apply_weather_penalty(score, explanations):
    weather = get_weather_stub()
    if weather.condition == "normal":
        return score

    explanations.append(
        ReliabilityExplanation(
            code="WEATHER",
            text=f"Adverse weather: {weather.condition}."
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

    score, hist_expl = _base_score_from_history(stats)
    explanations.extend(hist_expl)
    if stats is None:
        flags.append("HISTORICAL_MISSING")

    # 3) Live penalties
    for leg in journey["legs"]:
        score = _apply_live_penalties(score, leg, explanations)

    # 4) Weather penalty
    score = _apply_weather_penalty(score, explanations)

    # 5) Band
    band = _band_from_score(score)

    # 6) Attach to journey
    journey["reliability_score"] = score
    journey["reliability_band"] = band
    journey["reliability_explanation"] = [e.text for e in explanations]

    return journey, flags
