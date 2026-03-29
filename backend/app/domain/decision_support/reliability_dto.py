from typing import List, Optional
from pydantic import BaseModel

class ReliabilityExplanation(BaseModel):
    code: str
    text: str

class LegLiveStatus(BaseModel):
    available: bool
    delay_minutes: Optional[int] = None
    cancelled: bool
    source: Optional[str] = None

class LegRisk(BaseModel):
    leg_risk_band: str
    risk_explanations: List[ReliabilityExplanation] = []

class JourneyReliability(BaseModel):
    reliability_score: int
    reliability_band: str
    reliability_explanations: List[ReliabilityExplanation]
    data_quality_flags: List[str]
