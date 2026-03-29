"""Planner exceptions — stub for Person E (Rak). Flesh out as needed."""


class PlannerError(Exception):
    """Any planning failure."""
    pass


class NoRouteFoundError(Exception):
    """Valid stops but no timetabled route connects them."""
    pass
