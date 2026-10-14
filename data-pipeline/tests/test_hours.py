from pipeline.hours import parse_opening_hours


def w(p, day):
    return p.windows[day]


def test_missing():
    assert parse_opening_hours(None).status == "missing"
    assert parse_opening_hours("  ").status == "missing"


def test_24_7():
    p = parse_opening_hours("24/7")
    assert p.status == "ok" and all(w(p, d) == [(0, 1440)] for d in range(7))


def test_weekday_ranges_and_override():
    p = parse_opening_hours("Mo-Fr 09:00-17:00; Sa 10:00-14:00; Su off")
    assert p.status == "ok"
    assert w(p, 0) == [(540, 1020)] and w(p, 4) == [(540, 1020)]
    assert w(p, 5) == [(600, 840)]
    assert w(p, 6) == []


def test_later_rule_overrides():
    p = parse_opening_hours("Mo-Su 10:00-18:00; We 12:00-20:00")
    assert w(p, 2) == [(720, 1200)] and w(p, 3) == [(600, 1080)]


def test_split_shifts_and_lists():
    p = parse_opening_hours("Mo,We,Fr 10:00-12:00,13:00-18:00")
    assert w(p, 0) == [(600, 720), (780, 1080)] and w(p, 1) == []


def test_no_day_selector_means_every_day():
    p = parse_opening_hours("09:00-17:00")
    assert all(w(p, d) == [(540, 1020)] for d in range(7))


def test_past_midnight_and_wrap():
    p = parse_opening_hours("Fr-Mo 18:00-02:00")
    assert w(p, 4) == [(1080, 1560)] and w(p, 0) == [(1080, 1560)] and w(p, 2) == []
    assert p.is_open(5, 60, 90)  # Saturday 1:00-1:30 covered by Friday's late window


def test_messy_spacing_and_dashes():
    p = parse_opening_hours("Mo – Fr 9.00 - 17.30")
    assert p.status == "ok" and w(p, 0) == [(540, 1050)]


def test_holiday_ignored_but_noted():
    p = parse_opening_hours("Mo-Fr 09:00-17:00; PH off")
    assert p.status == "ok" and p.notes


def test_partial_and_unparseable():
    p = parse_opening_hours("Mo-Fr 09:00-17:00; Apr-Oct Sa 10:00-16:00")
    assert p.status == "partial" and w(p, 0) == [(540, 1020)]
    assert parse_opening_hours("sunrise-sunset").status == "unparseable"
    assert parse_opening_hours("call ahead").status == "unparseable"


def test_rows_shape():
    rows = parse_opening_hours("Sa 10:00-14:00").rows()
    assert rows == [(5, 600, 840)]
