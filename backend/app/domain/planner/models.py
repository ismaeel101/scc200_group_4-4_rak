from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class Mode(str, Enum):
    BUS = "bus"
    RAIL = "rail"
    WALK = "walk"


class TimeType(str, Enum):
    DEPART_AT = "depart_at"
    ARRIVE_BY = "arrive_by"


@dataclass(frozen=True)
class PlaceId:
    """
    Internal identifier wrapper.

    Examples:
      - PlaceId(kind="BUS", value="3400XYZ123")  # AtcoCode
      - PlaceId(kind="RAIL", value="LAN")        # CRS
    """
    kind: str  # "BUS" or "RAIL"
    value: str


@dataclass(frozen=True)
class PlanRequest:
    origin: PlaceId
    destination: PlaceId
    time_type: TimeType
    time: datetime
    modes: tuple[Mode, ...] = (Mode.BUS, Mode.RAIL)
    max_options: int = 5


@dataclass(frozen=True)
class Leg:
    mode: Mode
    from_id: PlaceId
    to_id: PlaceId
    depart_time: datetime
    arrive_time: datetime
    operator: Optional[str] = None
    service_id: Optional[str] = None

    @property
    def from_loc(self) -> PlaceId:
        return self.from_id

    @property
    def to_loc(self) -> PlaceId:
        return self.to_id

    @property
    def depart(self) -> datetime:
        return self.depart_time

    @property
    def arrive(self) -> datetime:
        return self.arrive_time


@dataclass(frozen=True)
class Journey:
    legs: tuple[Leg, ...]
    depart_time: datetime
    arrive_time: datetime
    changes: int  # number of vehicle legs minus 1; walk legs don't count as a "change"

    @property
    def total_duration_min(self) -> int:
        return int((self.arrive_time - self.depart_time).total_seconds() // 60)