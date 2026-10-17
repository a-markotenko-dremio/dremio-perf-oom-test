"""Quantities with a decimal K (kilo), M (mega) or G (giga) suffix: 100K, 10M, 1.44G."""
import math
import re
from decimal import Decimal

UNITS = (("G", 10**9), ("M", 10**6), ("K", 10**3))
_FACTOR = dict(UNITS + (("", 1),))


def parse_quantity(text, signed=False):
    """'100K' -> Decimal(100000), '1.44G' -> Decimal(1440000000), '2.5' -> Decimal('2.5'); ValueError for anything else.
    A sign is accepted only with `signed`."""
    m = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)([KMG]?)" if signed else r"(\d+(?:\.\d+)?)([KMG]?)", str(text).strip().upper())
    if not m:
        raise ValueError(f"not a number with an optional K/M/G suffix: {text!r}")
    return Decimal(m.group(1)) * _FACTOR[m.group(2)]


def parse_number(text):
    """Like parse_quantity, a signed value as a float: '100K' -> 100000.0, '-2.5' -> -2.5."""
    return float(parse_quantity(text, signed=True))


def format_quantity(value, exact=False):
    """The inverse of parse_quantity: 1440000000 -> '1.44G', 100000 -> '100K', 999 -> '999'.

    A value that is not a multiple of a unit gets two decimals ('1.23M' for 1234567); with `exact` it is written
    without a suffix instead (as '%g'), so that the label of an axis never shows a rounded number."""
    for unit, size in UNITS:
        if abs(value) >= size and (not exact or math.isclose(round(value / size, 2) * size, value, rel_tol=1e-9)):
            return f"{value / size:.2f}".rstrip("0").rstrip(".") + unit
    return f"{value:g}" if exact else str(value)
