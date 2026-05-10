"""Eastern and UTC helpers (explicit zones; not host-local wall clock)."""

from datetime import date, datetime, timezone


def test_now_est_is_america_new_york():
    from backend.core.time_eastern import EST, now_est, today_est

    a = now_est()
    assert a.tzinfo == EST
    assert today_est() == a.date()


def test_fixed_utc_instant_maps_to_expected_ny_date():
    from backend.core.time_eastern import EST

    utc_ref = datetime(2026, 7, 15, 4, 30, tzinfo=timezone.utc)
    ny = utc_ref.astimezone(EST)
    assert ny.date() == date(2026, 7, 15)


def test_utc_now_iso_z_ends_with_z():
    from backend.core.time_eastern import utc_now_iso_z

    s = utc_now_iso_z()
    assert s.endswith("Z")
    assert "T" in s


def test_merge_psycopg2_connect_kwargs():
    from backend.core.time_eastern import merge_psycopg2_connect_kwargs, PG_SESSION_TIMEZONE_OPTIONS

    out = merge_psycopg2_connect_kwargs({"host": "localhost", "database": "x"})
    assert out["options"] == PG_SESSION_TIMEZONE_OPTIONS
    again = merge_psycopg2_connect_kwargs(out)
    assert again["options"].count("timezone=America/New_York") == 1


def test_timestamptz_bind_utc_naive_is_eastern_wall():
    from backend.core.time_eastern import EST, timestamptz_bind_utc

    naive_ny = datetime(2026, 5, 9, 14, 30, 0)
    utc = timestamptz_bind_utc(naive_ny)
    assert utc.tzinfo == timezone.utc
    assert utc.astimezone(EST).replace(tzinfo=None) == naive_ny


def test_timestamptz_bind_utc_preserves_instant_for_aware_input():
    from backend.core.time_eastern import EST, timestamptz_bind_utc

    utc_in = datetime(2026, 5, 9, 18, 30, tzinfo=timezone.utc)
    bound = timestamptz_bind_utc(utc_in.astimezone(EST))
    assert bound == utc_in


def test_timestamptz_wire_iso_et_uses_eastern_offset():
    from backend.core.time_eastern import timestamptz_wire_iso_et

    # 2026-05-09 is EDT (UTC-4); 18:30Z → 14:30 Eastern.
    utc_in = datetime(2026, 5, 9, 18, 30, tzinfo=timezone.utc)
    s = timestamptz_wire_iso_et(utc_in)
    assert s is not None
    assert "-04:00" in s
    assert "14:30" in s
    assert timestamptz_wire_iso_et(None) is None
