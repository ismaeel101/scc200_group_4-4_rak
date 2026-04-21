from app.domain.decision_support.exceptions import DecisionSupportError

class DecisionSupport:
    """Decision support orchestration.

    When `enabled` is False this acts as the lightweight stub used previously.
    When True it delegates to the reliability pipeline (`compute_reliability`).
    """
    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def annotate(self, journeys):
        if not self.enabled:
            for j in journeys:
                if "reliability_score" not in j:
                    j["reliability_score"] = 75
                if "reliability_band" not in j:
                    j["reliability_band"] = "Medium"
                if "reliability_explanation" not in j:
                    j["reliability_explanation"] = []
            return journeys, []

        try:
            from .reliability_pipeline import compute_reliability
        except Exception as e:
            raise DecisionSupportError(f"Decision support pipeline unavailable: {e}")

        annotated = []
        flags = set()

        try:
            for j in journeys:
                # compute_reliability mutates and returns (journey, flags)
                updated_journey, jflags = compute_reliability(j)
                annotated.append(updated_journey)
                for f in (jflags or []):
                    flags.add(f)
        except Exception as e:
            raise DecisionSupportError(f"Failed to annotate journeys: {e}")

        return annotated, list(flags)
