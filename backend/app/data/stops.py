"""
StopService — stop/station autocomplete search (Person D / Kamol).

Contract with API layer (api.py):
    Class:  StopService
    Method: search_stops(query: str, limit: int) -> list
    Returns list of Stop ORM objects with attributes:
        id   : str   — AtcoCode (bus) or "RAIL:{CRS}" (rail)
        name : str
        type : str   — exactly "bus" or "rail"
        lat  : float
        lon  : float

Raises:
    StaticDataMissingError — DB has no stop data loaded
    DataUnavailableError   — DB connection failed
"""

from sqlalchemy import case, func
from sqlalchemy.exc import OperationalError

from app.data.database import SessionLocal
from app.data.models import Stop
from app.data.exceptions import StaticDataMissingError, DataUnavailableError


class StopService:
    """Provides stop autocomplete search over the NaPTAN/NPTG data."""

    def search_stops(self, query: str, limit: int) -> list:
        """
        Search stops by name. Returns results ranked:
            1. Prefix matches first (name starts with query)
            2. Then contains matches
            3. Alphabetical within each group

        Week 2 addition: uses database indexes for fast lookups.
        """
        db = SessionLocal()
        try:
            pattern = f"%{query}%"
            prefix_pattern = f"{query}%"

            results = (
                db.query(Stop)
                .filter(Stop.name.ilike(pattern))
                .order_by(
                    # Prefix matches rank higher
                    case(
                        (Stop.name.ilike(prefix_pattern), 0),
                        else_=1,
                    ),
                    # Rail stations rank higher than bus stops for same name
                    case(
                        (Stop.type == "rail", 0),
                        else_=1,
                    ),
                    Stop.name,
                )
                .limit(limit)
                .all()
            )

            if not results:
                # Distinguish "no matches" from "no data loaded"
                count = db.query(func.count(Stop.id)).scalar()
                if count == 0:
                    raise StaticDataMissingError("No stop data loaded in database")

            return results

        except OperationalError as e:
            raise DataUnavailableError(f"Database unavailable: {e}")
        finally:
            db.close()
