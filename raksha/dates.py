"""Shift explicit dates while retaining formatting and time components."""

from datetime import date, timedelta
import re


_DATE = re.compile(
    r"(?<!\d)(?:(\d{4})([-/])(\d{2})\2(\d{2})|"
    r"(\d{1,2})([-/])(\d{1,2})\6(\d{4}))(?!\d)"
)


def _detected_orders(values):
    return {
        int(match[7]) > 12
        for value in values for match in _DATE.finditer(value)
        if match[5] and (int(match[5]) > 12) != (int(match[7]) > 12)
    }


def infer_date_order(values) -> bool | None:
    orders = _detected_orders(values)
    return orders.pop() if len(orders) == 1 else None


def column_date_orders(header, rows):
    """Infer order per column, using other explicit date columns when they agree."""
    orders = []
    dated_columns = set()
    conflicts = set()
    for index, label in enumerate(header):
        normalized = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", label).casefold()
        words = set(re.findall(r"[a-z]+", normalized))
        if words & {"date", "dob", "admission", "discharge", "tithi"}:
            dated_columns.add(index)
        if "mm/dd" in normalized:
            orders.append(True)
        elif "dd/mm" in normalized:
            orders.append(False)
        else:
            detected = _detected_orders(row[index] for row in rows if index < len(row))
            if len(detected) > 1:
                conflicts.add(index)
            orders.append(detected.pop() if len(detected) == 1 else None)
    known = {orders[index] for index in dated_columns if orders[index] is not None}
    if len(known) == 1 and not dated_columns.intersection(conflicts):
        fallback = known.pop()
        for index in dated_columns:
            if orders[index] is None:
                orders[index] = fallback
    return orders


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
