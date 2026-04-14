from datetime import datetime

def _parse_journey_local(raw) -> dict:
    tight_summary = "One or more legs have very tight connections (<5 minutes) — increased risk of missed transfers"

    if isinstance(raw, dict):
        out = dict(raw)
        out.setdefault("has_connection_risk", out.get("has_tight_connection", False))
        expls = list(out.get("reliability_explanations") or [])
        if (out.get("has_connection_risk") or out.get("has_tight_connection")) and not any(tight_summary in e for e in expls):
            expls.append(tight_summary)
        out["reliability_explanations"] = expls
        return out

    expls = list(getattr(raw, "reliability_explanations", []) or [])
    has_risk = getattr(raw, "has_connection_risk", getattr(raw, "has_tight_connection", False))
    if has_risk and not any(tight_summary in e for e in expls):
        expls.append(tight_summary)

    return {
        "total_duration_min":      getattr(raw, "total_duration_min", None),
        "depart_time":             getattr(raw, "depart_time", None),
        "arrive_time":             getattr(raw, "arrive_time", None),
        "changes":                 getattr(raw, "changes", None),
        "reliability_score":       getattr(raw, "reliability_score", 0),
        "reliability_band":        getattr(raw, "reliability_band", "Low"),
        "reliability_explanations": expls,
        "has_connection_risk":     has_risk,
        "legs":                    [_ for _ in getattr(raw, "legs", [])],
    }


def check_object_mapping():
    class RawJourney:
        def __init__(self):
            self.total_duration_min = 30
            self.depart_time = datetime.utcnow()
            self.arrive_time = datetime.utcnow()
            self.changes = 1
            self.reliability_score = 80
            self.reliability_band = "High"
            self.reliability_explanations = []
            self.legs = []
            # domain-level flag
            self.has_tight_connection = True

    raw = RawJourney()
    parsed = _parse_journey_local(raw)
    expls = parsed.get("reliability_explanations", [])
    ok = any("very tight connections" in e for e in expls)
    print(f"Object mapping tight-connection explanation present: {ok}")
    return ok


def check_dict_mapping():
    raw = {
        "total_duration_min": 20,
        "depart_time": None,
        "arrive_time": None,
        "changes": 0,
        "reliability_score": 75,
        "reliability_band": "Medium",
        "reliability_explanations": [],
        "has_tight_connection": True,
        "legs": [],
    }
    parsed = _parse_journey_local(raw)
    expls = parsed.get("reliability_explanations", [])
    ok = any("very tight connections" in e for e in expls)
    print(f"Dict mapping tight-connection explanation present: {ok}")
    return ok


def main():
    ok1 = check_object_mapping()
    ok2 = check_dict_mapping()
    if ok1 and ok2:
        print("All mapping checks passed")
        return 0
    print("Mapping checks failed")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
