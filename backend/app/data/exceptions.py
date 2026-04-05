"""
Domain exceptions for the data layer (Person D / Kamol).

These are caught by the API layer (api.py) and mapped to HTTP responses:
    StaticDataMissingError -> 503 "Static data unavailable"
    DataUnavailableError   -> 503 "Stop data temporarily unavailable"

Any other exception propagates uncaught — intentional for early bug detection.
"""


class StaticDataMissingError(Exception):
    """NaPTAN/NPTG data has not been loaded into the database."""
    pass


class DataUnavailableError(Exception):
    """Database is temporarily unreachable."""
    pass
