"""Offline tests of the K/M/G quantities (quantities.py) and of their users in results_report."""
from decimal import Decimal

import pytest

import quantities
import results_report


@pytest.mark.parametrize("text, value", [("100K", 10**5), ("1.44G", 1_440_000_000), ("10m", 10**7), ("2.5", Decimal("2.5")),
                                         (" 4096 ", 4096), ("0", 0)])
def test_parse_quantity(text, value):
    assert quantities.parse_quantity(text) == value


@pytest.mark.parametrize("text", ["", "abc", "42 + CTAS", "10T", "10 M", "-3M", "1e6", "K"])
def test_parse_quantity_rejects(text):
    with pytest.raises(ValueError):
        quantities.parse_quantity(text)


def test_a_sign_is_accepted_only_when_asked_for():
    assert quantities.parse_quantity("-3M", signed=True) == -3_000_000
    assert quantities.parse_quantity("+1.5K", signed=True) == 1500


@pytest.mark.parametrize("value, text", [(1_440_000_000, "1.44G"), (100_000, "100K"), (10**7, "10M"), (999, "999"), (1_234_567, "1.23M")])
def test_format_quantity_rounds_to_two_decimals(value, text):
    assert quantities.format_quantity(value) == text


@pytest.mark.parametrize("value, text", [(1.44e9, "1.44G"), (100000.0, "100K"), (4096.0, "4096"), (7.5, "7.5"), (1_234_567.0, "1.23457e+06")])
def test_exact_format_never_shows_a_rounded_number(value, text):
    assert quantities.format_quantity(value, exact=True) == text


@pytest.mark.parametrize("rows", [100_000, 10**7, 1_440_000_000, 5, 1_234_567])
def test_format_rows_and_parse_rows_agree_on_round_numbers(rows):
    text = results_report.format_rows(rows)
    if rows != 1_234_567:                       # that one is rounded for the label
        assert results_report.parse_rows(text) == rows


def test_parse_rows_rejects_fractions_of_a_row_and_names_the_rows_in_the_message():
    assert results_report.parse_rows("1.44G") == 1_440_000_000
    with pytest.raises(ValueError, match="row count"):
        results_report.parse_rows("abc")
    with pytest.raises(ValueError, match="not a whole number"):
        results_report.parse_rows("1.0000005M")


@pytest.mark.parametrize("text, value", [("100K", 1e5), ("1.44G", 1.44e9), ("-2.5", -2.5), (" 4096 ", 4096.0)])
def test_parse_number_is_a_signed_float(text, value):
    assert quantities.parse_number(text) == pytest.approx(value) and isinstance(quantities.parse_number(text), float)


def test_parse_number_rejects_what_is_not_a_number():
    with pytest.raises(ValueError):
        quantities.parse_number("42 + CTAS")
