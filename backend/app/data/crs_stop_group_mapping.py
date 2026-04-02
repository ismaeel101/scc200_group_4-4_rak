"""
CRS ↔ StopGroup mapping service — Person D (Kamol), Week 3.

Provides lookup helpers that resolve a National Rail CRS code (e.g. "LNS")
to the internal stop_group_id used by the journey planner for interchange
walking transfers, and vice-versa.

Lookup strategy (DB-first, manual-file fallback):
    1. Query the ``crs_stop_group_map`` database table.
       This table is populated automatically by the NaPTAN loader and by
       the sample_loader, so it is the primary source of truth.
    2. If the DB has no row for the requested CRS code, fall back to the
       manual JSON file (``manual_crs_stop_group_map.json``).
       The JSON file guarantees the demo corridor works even before the
       full NaPTAN dataset is loaded.

Design notes:
    - All CRS input is normalised to uppercase so lookups are
      case-insensitive ("lns", "Lns", "LNS" all work).
    - Returns ``None`` when a mapping does not exist — callers decide
      whether to treat this as an error.
    - The manual JSON is loaded once on first use and cached in memory
      for the lifetime of the process (it's tiny, ~20 entries max).
    - No external dependencies beyond SQLAlchemy (already in the project).

Usage:
    from app.data.crs_stop_group_mapping import CrsStopGroupService

    svc = CrsStopGroupService()
    group_id = svc.crs_to_stop_group("LNS")       # -> "E0016403" or None
    crs      = svc.stop_group_to_crs("E0016414")   # -> "PRE"      or None
"""

import json
import logging
from pathlib import Path

from sqlalchemy.exc import OperationalError

from app.data.database import SessionLocal
from app.data.models import CrsStopGroupMapping

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Manual fallback map (loaded once, cached)
# ──────────────────────────────────────────────

_manual_map: dict | None = None

_JSON_PATH = Path(__file__).parent / "manual_crs_stop_group_map.json"


def _load_manual_map() -> dict:
    """Load the manual JSON mapping file and cache it in module state.

    Returns a dict keyed by uppercase CRS code, e.g.:
        {"LNS": {"stop_group_id": "E0016403", ...}, ...}

    Keys starting with "_" (like "_comment") are ignored.
    """
    global _manual_map
    if _manual_map is not None:
        return _manual_map

    try:
        raw = json.loads(_JSON_PATH.read_text(encoding="utf-8"))
        # Filter out metadata keys (e.g. "_comment")
        _manual_map = {
            k.upper(): v
            for k, v in raw.items()
            if not k.startswith("_")
        }
        logger.info(
            "Loaded manual CRS mapping file with %d entries.", len(_manual_map)
        )
    except FileNotFoundError:
        logger.warning("Manual CRS mapping file not found at %s", _JSON_PATH)
        _manual_map = {}
    except json.JSONDecodeError as exc:
        logger.error("Invalid JSON in manual CRS mapping file: %s", exc)
        _manual_map = {}

    return _manual_map


# ──────────────────────────────────────────────
# Service class
# ──────────────────────────────────────────────

class CrsStopGroupService:
    """Resolves CRS codes to stop_group IDs and back.

    Intended to be instantiated where needed — it holds no mutable state
    beyond the module-level JSON cache.
    """

    # ── forward: CRS → stop_group_id ──────────

    def crs_to_stop_group(self, crs_code: str) -> str | None:
        """Return the stop_group_id for a CRS code, or None if unknown.

        Checks the DB first (populated by NaPTAN loader / sample_loader),
        then falls back to the manual JSON file.
        """
        crs = crs_code.strip().upper()
        if not crs:
            return None

        # 1. Try the database
        result = self._db_lookup_by_crs(crs)
        if result is not None:
            return result

        # 2. Fall back to manual JSON
        manual = _load_manual_map()
        entry = manual.get(crs)
        if entry is not None:
            logger.debug("CRS '%s' resolved via manual mapping file.", crs)
            return entry["stop_group_id"]

        logger.debug("CRS '%s' not found in DB or manual mapping.", crs)
        return None

    # ── reverse: stop_group_id → CRS ─────────

    def stop_group_to_crs(self, stop_group_id: str) -> str | None:
        """Return the CRS code for a stop_group_id, or None if unknown.

        Useful when the planner has a stop_group but needs the rail
        station CRS for display or for querying live departure boards.
        """
        if not stop_group_id:
            return None

        # 1. Try the database
        result = self._db_reverse_lookup(stop_group_id)
        if result is not None:
            return result

        # 2. Fall back to manual JSON (linear scan — fine for small map)
        manual = _load_manual_map()
        for crs, entry in manual.items():
            if entry.get("stop_group_id") == stop_group_id:
                return crs

        return None

    # ── bulk: load all mappings ───────────────

    def get_all_mappings(self) -> dict[str, str]:
        """Return a dict of {CRS: stop_group_id} combining DB + manual.

        Manual entries are included only when the DB does not already
        contain a row for that CRS code (DB takes precedence).
        """
        combined: dict[str, str] = {}

        # Start with manual (lower priority)
        manual = _load_manual_map()
        for crs, entry in manual.items():
            combined[crs] = entry["stop_group_id"]

        # Overlay with DB rows (higher priority)
        db = SessionLocal()
        try:
            rows = db.query(CrsStopGroupMapping).all()
            for row in rows:
                combined[row.crs_code.upper()] = row.stop_group_id
        except OperationalError:
            logger.warning("DB unavailable — returning manual mappings only.")
        finally:
            db.close()

        return combined

    # ── private DB helpers ────────────────────

    def _db_lookup_by_crs(self, crs: str) -> str | None:
        """Query crs_stop_group_map by CRS code. Returns stop_group_id."""
        db = SessionLocal()
        try:
            row = (
                db.query(CrsStopGroupMapping)
                .filter(CrsStopGroupMapping.crs_code == crs)
                .first()
            )
            return row.stop_group_id if row else None
        except OperationalError:
            logger.warning("DB unavailable during CRS lookup for '%s'.", crs)
            return None
        finally:
            db.close()

    def _db_reverse_lookup(self, stop_group_id: str) -> str | None:
        """Query crs_stop_group_map by stop_group_id. Returns CRS code."""
        db = SessionLocal()
        try:
            row = (
                db.query(CrsStopGroupMapping)
                .filter(CrsStopGroupMapping.stop_group_id == stop_group_id)
                .first()
            )
            return row.crs_code.upper() if row else None
        except OperationalError:
            logger.warning(
                "DB unavailable during reverse CRS lookup for '%s'.",
                stop_group_id,
            )
            return None
        finally:
            db.close()
