from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import asin, cos, radians, sin, sqrt
from typing import Protocol

from .models import PlaceId


@dataclass(frozen=True)
class TimetableRow:
    from_id: PlaceId
    to_id: PlaceId
    depart_time: datetime
    arrive_time: datetime
    operator: str
    service_id: str


@dataclass(frozen=True)
class StopInfo:
    place_id: PlaceId
    lat: float
    lon: float
    stop_group_id: str | None = None


class TimetableProvider(Protocol):
    def get_direct_rows(
        self,
        origin: PlaceId,
        destination: PlaceId,
        depart_at: datetime,
        *,
        max_results: int = 50,
    ) -> list[TimetableRow]:
        ...

    def get_rows_from(
        self,
        origin: PlaceId,
        depart_at: datetime,
    ) -> list[TimetableRow]:
        ...

    def get_stop_info(self, place_id: PlaceId) -> StopInfo | None:
        ...

    def get_walkable_stops(
        self,
        origin: PlaceId,
        *,
        max_distance_m: float,
    ) -> list[StopInfo]:
        ...


class FakeTimetableProvider:
    def __init__(
        self,
        rows: list[TimetableRow],
        stops: list[StopInfo] | None = None,
    ):
        self._rows = list(rows)
        self._stops = {s.place_id: s for s in (stops or [])}

    def get_direct_rows(
        self,
        origin: PlaceId,
        destination: PlaceId,
        depart_at: datetime,
        *,
        max_results: int = 50,
    ) -> list[TimetableRow]:
        matches = [
            r
            for r in self._rows
            if r.from_id == origin
            and r.to_id == destination
            and r.depart_time >= depart_at
        ]
        matches.sort(key=lambda r: (r.arrive_time, r.depart_time, r.service_id))
        return matches[:max_results]

    def get_rows_from(
        self,
        origin: PlaceId,
        depart_at: datetime,
    ) -> list[TimetableRow]:
        matches = [
            r
            for r in self._rows
            if r.from_id == origin
            and r.depart_time >= depart_at
        ]
        matches.sort(key=lambda r: (r.depart_time, r.arrive_time, r.service_id))
        return matches

    def get_stop_info(self, place_id: PlaceId) -> StopInfo | None:
        return self._stops.get(place_id)

    def get_walkable_stops(
        self,
        origin: PlaceId,
        *,
        max_distance_m: float,
    ) -> list[StopInfo]:
        origin_info = self.get_stop_info(origin)
        if origin_info is None:
            return []

        walkable: list[StopInfo] = []
        for stop in self._stops.values():
            if stop.place_id == origin:
                continue

            same_group = (
                origin_info.stop_group_id is not None
                and stop.stop_group_id is not None
                and origin_info.stop_group_id == stop.stop_group_id
            )

            if same_group:
                walkable.append(stop)
                continue

            distance = _haversine_m(
                origin_info.lat,
                origin_info.lon,
                stop.lat,
                stop.lon,
            )
            if distance <= max_distance_m:
                walkable.append(stop)

        walkable.sort(key=lambda s: (s.place_id.kind, s.place_id.value))
        return walkable


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    )
    c = 2 * asin(sqrt(a))
    return r * c