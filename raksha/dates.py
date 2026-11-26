"""Shift explicit dates while retaining formatting and time components."""

from datetime import date, timedelta
import re


_DATE = re.compile(
    r"(?<!\d)(?:(\d{4})([-/])(\d{2})\2(\d{2})|"
    r"(\d{1,2})([-/])(\d{1,2})\6(\d{4}))(?!\d)"
)


def infer_date_order(values) -> bool | None:
    orders = {
        int(match[7]) > 12
        for value in values for match in _DATE.finditer(value)
        if match[5] and (int(match[5]) > 12) != (int(match[7]) > 12)
    }
    return orders.pop() if len(orders) == 1 else None


def shift_dates(text: str, days: int, *, month_first: bool | None = None) -> str:
    def replace(match: re.Match) -> str:
        year, iso_sep, month, day, first, sep, second, final_year = match.groups()
        try:
            if year:
                shifted = date(int(year), int(month), int(day)) + timedelta(days=days)
                return iso_sep.join((f"{shifted.year:04d}", f"{shifted.month:02d}", f"{shifted.day:02d}"))
            if month_first is None and (int(first) > 12) == (int(second) > 12):
                return match[0]
            order = month_first if month_first is not None else int(second) > 12
            month, day = (first, second) if order else (second, first)
            shifted = date(int(final_year), int(month), int(day)) + timedelta(days=days)
            a, b = (shifted.month, shifted.day) if order else (shifted.day, shifted.month)
            return sep.join((f"{a:0{len(first)}d}", f"{b:0{len(second)}d}", f"{shifted.year:04d}"))
        except (ValueError, OverflowError):
            return match[0]

    return _DATE.sub(replace, text)
