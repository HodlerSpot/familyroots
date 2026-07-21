"""Birthday date math, shared across features (time capsules, predictions).

Extracted verbatim from ``routers/capsules.py`` so the age/birthday rules live
in exactly one place. UTC calendar dates throughout — matching capsule
``release_date`` semantics. Feb-29 births fall back to Mar 1 in non-leap years
(the convention banks/passports use), and the fallback rides along unchanged.
"""

from datetime import date


def age_on(birthdate: date, on: date) -> int:
    """The child's integer age on the date ``on`` (ex ``_age_on``)."""
    return on.year - birthdate.year - ((on.month, on.day) < (birthdate.month, birthdate.day))


def birthday_at_age(birthdate: date, age: int) -> date:
    """The date the child turns ``age``. Feb-29 births fall back to Mar 1
    (ex ``_birthday_at_age``)."""
    try:
        return birthdate.replace(year=birthdate.year + age)
    except ValueError:
        return date(birthdate.year + age, 3, 1)


def next_birthday(birthdate: date, today: date) -> date:
    """The first birthday strictly AFTER ``today``. A round opened ON the
    birthday seals next year — today's seal moment has already passed."""
    return birthday_at_age(birthdate, age_on(birthdate, today) + 1)
