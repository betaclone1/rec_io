"""Tests for cycle_recon handoff archive packaging."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from backend.core.cycle_recon.archive import (
    _extract_archive,
    create_handoff_archive,
    list_package_files,
    select_archive_format,
)
from backend.core.cycle_recon.hashing import sha256_file


def _mini_package(tmp: Path, run_id: str = "pkg_test_run") -> Path:
    d = tmp / run_id
    d.mkdir(parents=True)
    (d / "README.md").write_text("# test\n", encoding="utf-8")
    (d / "schema.json").write_text('{"schema_version":"cycle_recon.v1"}\n', encoding="utf-8")
    (d / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "schema_version": "cycle_recon.v1",
                "generator_version": "1.0.0",
                "created_at_utc": "2026-09-06T00:00:00Z",
                "request": {
                    "tickers": ["KXBTC15M-TEST"],
                    "trade_ids": ["1"],
                    "start": "2026-09-05T14:00:00Z",
                    "end": "2026-09-05T16:00:00Z",
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (d / "summary.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "statuses": {"COMPLETE": 1},
                "row_counts": {"markets": 1, "book_events": 3},
                "unavailable_by_design": ["exchange-level BTC trades"],
                "what_you_can_answer": ["exact entry book"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (d / "quality_report.json").write_text(
        json.dumps({"markets": [{"ticker": "KXBTC15M-TEST", "status": "COMPLETE"}]}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    # Fake table payloads (not real parquet — archive treats as opaque bytes)
    (d / "markets.parquet").write_bytes(b"PAR1markets")
    (d / "book_events.parquet").write_bytes(b"PAR1events")
    (d / "debug").mkdir()
    (d / "debug" / "secret.csv").write_text("should-not-archive\n", encoding="utf-8")
    (d / ".incomplete").write_text("1", encoding="utf-8")
    return d


def test_select_archive_format_records_capability():
    fmt, how = select_archive_format()
    assert fmt in ("tar.zst", "tar.gz")
    if fmt == "tar.zst":
        assert how in ("python-zstandard", "cli-zstd")
    else:
        assert how == "gzip"


def test_deterministic_checksums_and_archive(tmp_path: Path):
    d1 = _mini_package(tmp_path / "a", "det_run")
    d2 = tmp_path / "b" / "det_run"
    shutil.copytree(d1, d2)

    r1 = create_handoff_archive(d1, force_format="tar.gz")
    r2 = create_handoff_archive(d2, force_format="tar.gz")
    assert r1.sha256 == r2.sha256
    assert r1.bytes == r2.bytes
    assert r1.format == "tar.gz"
    assert Path(r1.archive_path).is_file()
    assert not (tmp_path / "a" / "det_run.archive.partial").exists()
    assert (d1 / "analyst_index.json").is_file()
    assert (d1 / "checksums.sha256").is_file()
    # debug/secrets excluded
    files = list_package_files(d1)
    assert "debug/secret.csv" not in files
    assert ".incomplete" not in files
    assert "analyst_index.json" in files
    assert "checksums.sha256" in files


def test_extraction_round_trip_and_checksums(tmp_path: Path):
    d = _mini_package(tmp_path, "rt_run")
    result = create_handoff_archive(d, force_format="tar.gz")
    extract_to = tmp_path / "out"
    extract_to.mkdir()
    _extract_archive(Path(result.archive_path), extract_to, fmt="tar.gz")
    root = extract_to / "rt_run"
    assert (root / "README.md").read_text(encoding="utf-8") == "# test\n"
    assert (root / "markets.parquet").read_bytes() == b"PAR1markets"
    # checksums verify
    for line in (root / "checksums.sha256").read_text(encoding="utf-8").splitlines():
        digest, rel = line.split(None, 1)
        assert sha256_file(root / rel) == digest


def test_partial_archive_on_failure(tmp_path: Path, monkeypatch):
    d = _mini_package(tmp_path, "fail_run")
    from backend.core.cycle_recon import archive as arch_mod

    def boom(*a, **k):
        raise RuntimeError("forced verify failure")

    monkeypatch.setattr(arch_mod, "_verify_archive", boom)
    with pytest.raises(RuntimeError, match="forced verify failure"):
        create_handoff_archive(d, force_format="tar.gz")
    final = tmp_path / "fail_run.tar.gz"
    assert not final.exists()
    failed = tmp_path / "fail_run.archive.failed"
    assert failed.is_file()
    marker = json.loads(failed.read_text(encoding="utf-8"))
    assert "forced verify failure" in marker["error"]
    # partial may remain for inspection
    partial = tmp_path / "fail_run.archive.partial"
    assert partial.exists()


def test_corrupt_archive_fails_verify(tmp_path: Path):
    d = _mini_package(tmp_path, "corrupt_src")
    # Build a good archive then corrupt a copy and ensure verify rejects
    good = create_handoff_archive(d, force_format="tar.gz")
    bad = tmp_path / "corrupt_src.archive.partial"
    data = bytearray(Path(good.archive_path).read_bytes())
    if len(data) > 20:
        data[-10] ^= 0xFF
    bad.write_bytes(bytes(data))
    from backend.core.cycle_recon.archive import _verify_archive

    with pytest.raises(Exception):
        _verify_archive(
            bad,
            fmt="tar.gz",
            expected_files=list_package_files(d),
            run_id="corrupt_src",
            run_dir=d,
        )


@pytest.mark.parametrize("fmt", ["tar.gz", "tar.zst"])
def test_format_round_trip_when_available(tmp_path: Path, fmt: str):
    from backend.core.cycle_recon.archive import zstd_capability

    if fmt == "tar.zst":
        ok, _ = zstd_capability()
        if not ok:
            pytest.skip("zstd unavailable")
    d = _mini_package(tmp_path, f"fmt_{fmt.replace('.', '_')}")
    result = create_handoff_archive(d, force_format=fmt)
    assert result.format == fmt
    assert Path(result.archive_path).is_file()
    extract_to = tmp_path / f"ext_{fmt}"
    extract_to.mkdir()
    _extract_archive(Path(result.archive_path), extract_to, fmt=fmt)
    assert (extract_to / d.name / "analyst_index.json").is_file()


def test_representative_real_package_archive(tmp_path: Path):
    """Pack an existing acceptance package if present (workspace under system temp)."""
    root = (
        Path(__file__).resolve().parents[3]
        / "backend"
        / "data"
        / "historical_data"
        / "cycle_recon_runs"
    )
    # Prefer smaller packages for unit runtime
    candidates = [
        root / "accept_offline_cache_hit_v2",
        root / "accept_atomic_check_v2",
        root / "accept_archive_wire_v1",
        root / "accept_sep6_clean_v2",
    ]
    run_dir = next((p for p in candidates if p.is_dir()), None)
    if run_dir is None:
        pytest.skip("no local acceptance package present")

    # pytest tmp_path is OS-writable temp — never create workspaces under
    # cycle_recon_runs (may be PermissionError in some environments).
    work = tmp_path / "rep_pack"
    work.mkdir()
    dest = work / run_dir.name
    shutil.copytree(
        run_dir,
        dest,
        ignore=shutil.ignore_patterns("debug", ".incomplete"),
    )
    # Archive output also stays in writable temp (configurable output_dir)
    result = create_handoff_archive(dest, output_dir=work)
    assert result.bytes > 0
    assert result.member_count >= 8
    archive_path = Path(result.archive_path)
    assert archive_path.is_file()
    assert archive_path.parent == work

    ext = work / "extracted"
    ext.mkdir()
    _extract_archive(archive_path, ext, fmt=result.format)
    extracted_root = ext / dest.name
    assert (extracted_root / "checksums.sha256").is_file()
    assert (extracted_root / "analyst_index.json").is_file()
    for line in (extracted_root / "checksums.sha256").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        digest, rel = line.split(None, 1)
        assert sha256_file(extracted_root / rel) == digest
