"""Reporting has no tables of its own beyond exchange rates.

Occupancy, revenue and the daily staff view are all aggregations over bookings.
Materialise something here only if a query proves too slow in practice - see
apps/reporting/fx.py for the one model that does live here.
"""

from apps.reporting.fx import ExchangeRate  # noqa: F401
