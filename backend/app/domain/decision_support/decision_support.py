from app.domain.decision_support.exceptions import DecisionSupportError

class DecisionSupport:
    def annotate(self, journeys):
        for j in journeys:
            if "reliability_score" not in j:
                j["reliability_score"] = 75
            if "reliability_band" not in j:
                j["reliability_band"] = "Medium"
            if "reliability_explanation" not in j:
                j["reliability_explanation"] = []
        return journeys, []
