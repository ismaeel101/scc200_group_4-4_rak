"""
SQLAlchemy ORM models for the data layer (Person D / Kamol).

Tables:
    stop_groups          — NPTG locality-based interchange clusters
    stops                — Bus stops (NaPTAN AtcoCode) and rail stations (CRS)
    crs_stop_group_map   — Maps rail CRS codes to stop groups (for interchange)
    bus_timetable        — Bus departure/arrival times per trip per stop
    rail_schedule        — Rail departure/arrival times per trip per stop

Indexes are tuned for:
    - Stop name search (prefix + contains)
    - Timetable lookups by stop_id + departure_time window
    - Trip sequence lookups (for following a trip through stops)

All times stored as "HH:MM:SS" strings to handle service days past midnight
(e.g., "25:10:00" for 01:10 the next day, following GTFS convention).
"""

from sqlalchemy import (
    Column, String, Float, Integer, Boolean, Index, ForeignKey, Text,
)
from sqlalchemy.orm import relationship

from app.data.database import Base


# ──────────────────────────────────────────────
# Stop Groups (NPTG interchange clusters)
# ──────────────────────────────────────────────


# ──────────────────────────────────────────────
# Stops (bus + rail unified table)
# ──────────────────────────────────────────────

class Stop(Base):
    __tablename__ = "stops"

    # AtcoCode for bus; "RAIL:{CRS}" for rail (see assumption 6)
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)        # Exactly "bus" or "rail"
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)

    stop_group_id = Column(String, ForeignKey("stop_groups.id"), nullable=True)
    atco_code = Column(String, nullable=True)    # Original NaPTAN code (bus)
    crs_code = Column(String, nullable=True)     # CRS code (rail only)
    nptg_locality_code = Column(String, nullable=True)
    street = Column(String, nullable=True)
    bearing = Column(String, nullable=True)
    stop_type = Column(String, nullable=True)    # NaPTAN StopType (BCT, RLY, etc.)

    stop_group = relationship("StopGroup", back_populates="stops")

    __table_args__ = (
        # Week 2: index for stop name search (prefix + contains queries)
        Index("ix_stops_name", "name"),
        # Index for type filtering
        Index("ix_stops_type", "type"),
        # Index for stop group lookups (walking transfers)
        Index("ix_stops_stop_group", "stop_group_id"),
    )

    def __repr__(self):
        return f"<Stop {self.id} '{self.name}' ({self.type})>"


# ──────────────────────────────────────────────
# CRS → StopGroup mapping (rail interchange)
# ──────────────────────────────────────────────

class CrsStopGroupMapping(Base):
    __tablename__ = "crs_stop_group_map"

    crs_code = Column(String, primary_key=True)
    stop_group_id = Column(String, ForeignKey("stop_groups.id"), nullable=False)
    representative_stop_id = Column(String, ForeignKey("stops.id"), nullable=True)

    def __repr__(self):
        return f"<CrsMapping {self.crs_code} -> {self.stop_group_id}>"


# ──────────────────────────────────────────────
# Bus Timetable (GTFS-style stop_times)
# ──────────────────────────────────────────────

class BusTimetableEntry(Base):
    __tablename__ = "bus_timetable"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trip_id = Column(String, nullable=False)
    service_id = Column(String, nullable=False)  # Route number (e.g. "40")
    operator = Column(String, nullable=True)
    stop_id = Column(String, ForeignKey("stops.id"), nullable=False)
    stop_sequence = Column(Integer, nullable=False)
    arrival_time = Column(String, nullable=True)    # "HH:MM:SS" (GTFS style)
    departure_time = Column(String, nullable=True)  # "HH:MM:SS"

    # Days of operation
    monday = Column(Boolean, default=False)
    tuesday = Column(Boolean, default=False)
    wednesday = Column(Boolean, default=False)
    thursday = Column(Boolean, default=False)
    friday = Column(Boolean, default=False)
    saturday = Column(Boolean, default=False)
    sunday = Column(Boolean, default=False)

    __table_args__ = (
        # Week 2: index for timetable lookups by stop + departure time
        Index("ix_bus_tt_stop_depart", "stop_id", "departure_time"),
        # Index for following a trip through its stops
        Index("ix_bus_tt_trip_seq", "trip_id", "stop_sequence"),
        # Index for service lookups
        Index("ix_bus_tt_service", "service_id"),
    )

    def __repr__(self):
        return f"<BusTT trip={self.trip_id} stop={self.stop_id} dep={self.departure_time}>"


# ──────────────────────────────────────────────
# Rail Schedule (same structure as bus, separate table)
# ──────────────────────────────────────────────

class RailScheduleEntry(Base):
    __tablename__ = "rail_schedule"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trip_id = Column(String, nullable=False)
    service_id = Column(String, nullable=False)  # Train ID (e.g. "1P42")
    operator = Column(String, nullable=True)
    stop_id = Column(String, ForeignKey("stops.id"), nullable=False)
    stop_sequence = Column(Integer, nullable=False)
    arrival_time = Column(String, nullable=True)    # "HH:MM:SS"
    departure_time = Column(String, nullable=True)  # "HH:MM:SS"

    # Days of operation
    monday = Column(Boolean, default=False)
    tuesday = Column(Boolean, default=False)
    wednesday = Column(Boolean, default=False)
    thursday = Column(Boolean, default=False)
    friday = Column(Boolean, default=False)
    saturday = Column(Boolean, default=False)
    sunday = Column(Boolean, default=False)

    __table_args__ = (
        # Week 2: index for timetable lookups by stop + departure time
        Index("ix_rail_sched_stop_depart", "stop_id", "departure_time"),
        # Index for following a trip through its stops
        Index("ix_rail_sched_trip_seq", "trip_id", "stop_sequence"),
        # Index for service lookups
        Index("ix_rail_sched_service", "service_id"),
    )

    def __repr__(self):
        return f"<RailSched trip={self.trip_id} stop={self.stop_id} dep={self.departure_time}>"
