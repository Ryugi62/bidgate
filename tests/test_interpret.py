from datetime import datetime, timezone
from bidgate.domain.interpret import interpret

NOW = datetime(2026, 10, 27, 15, 0, tzinfo=timezone.utc)


def test_deadline_utc_full_date():
    v = interpret("deadline", "Deadline Oct 27, 2026, 23:45 UTC", NOW)
    assert v == datetime(2026, 10, 27, 23, 45, tzinfo=timezone.utc)


def test_deadline_pacific_without_year_uses_next_occurrence():
    v = interpret("deadline", "The deadline to apply on-time is November 2 at 8pm PT; x", NOW)
    assert v == datetime(2026, 11, 3, 4, 0, tzinfo=timezone.utc)  # PST = UTC-8 after Nov 1


def test_deadline_none_for_plain_line():
    assert interpret("deadline", "Meet the judges", NOW) is None


def test_min_age():
    assert interpret("min_age", "Open worldwide to anyone aged 16 or older at the start", NOW) == 16
    assert interpret("min_age", "Participants must be at least 18 years old", NOW) == 18
    assert interpret("min_age", "Welcome everyone", NOW) is None


def test_mode():
    assert interpret("mode", "Fully online. 22-27 October 2026", NOW) == "online"
    assert interpret("mode", "The batch will take place in-person at the campus", NOW) == "onsite"
    assert interpret("mode", "Nothing about place", NOW) is None


def test_fee():
    assert interpret("fee", "Does it cost anything to enter? - No. Submission is free.", NOW) == 0.0
    assert interpret("fee", "A registration fee of $25 applies", NOW) == 25.0
    assert interpret("fee", "Hello", NOW) is None


def test_deliverables():
    v = interpret("deliverables", "A demo video of 1-4 minutes and a slide deck", NOW)
    assert v == frozenset({"video", "deck"})
    assert interpret("deliverables", "A GitHub repository with README", NOW) == frozenset({"repo"})
    assert interpret("deliverables", "Hello", NOW) is None
