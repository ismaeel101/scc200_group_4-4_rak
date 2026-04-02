"""Data-layer exceptions (Person D — Kamol)."""


class DataUnavailableError(Exception):
    """Database file is temporarily unreachable."""
    pass


class StaticDataMissingError(Exception):
    """NaPTAN/NPTG stop data has not been loaded (DB empty or missing)."""
    pass
