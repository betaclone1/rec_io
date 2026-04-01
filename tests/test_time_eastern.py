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
