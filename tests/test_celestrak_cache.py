"""SPEC 14.8 — a cached CelesTrak file younger than 2 hours is never re-downloaded."""
import json
import time
from unittest import mock

import pytest

from orbitguard import config, download

CSV = b"OBJECT_NAME,OBJECT_ID,EPOCH\nISS (ZARYA),1998-067A,2026-10-09T00:00:00\n"


@pytest.fixture
def tmp_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CELESTRAK_DIR", tmp_path / "celestrak")
    monkeypatch.setattr(config, "CATALOG_SNAPSHOT_DIR", tmp_path / "snapshot")
    return tmp_path


def write_cache(group: str, age_hours: float):
    path = download.celestrak_group_path(group)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(CSV)
    ts = time.time() - age_hours * 3600
    download._meta_path(path).write_text(json.dumps({"downloaded_at_unix": ts}))
    return path


def fake_session(status=200, body=CSV):
    s = mock.Mock()
    s.get.return_value = mock.Mock(status_code=status, content=body)
    return s


def test_fresh_cache_is_not_redownloaded(tmp_dirs):
    write_cache("stations", age_hours=1.0)
    s = fake_session()
    download.fetch_celestrak_group("stations", session=s)
    s.get.assert_not_called()


def test_fresh_cache_not_redownloaded_via_requests_get(tmp_dirs):
    write_cache("stations", age_hours=1.99)
    with mock.patch("requests.get") as g:
        download.download_celestrak(["stations"])
        g.assert_not_called()


def test_stale_cache_is_redownloaded(tmp_dirs):
    write_cache("stations", age_hours=2.5)
    s = fake_session()
    download.fetch_celestrak_group("stations", session=s)
    s.get.assert_called_once()
    assert download.file_age_hours(download.celestrak_group_path("stations")) < 0.01


def test_non_200_stops_all_further_requests_and_keeps_cache(tmp_dirs):
    old = write_cache("active", age_hours=5.0)
    s = fake_session(status=403, body=b"Forbidden")
    status = download.download_celestrak(["stations", "active", "cosmos-1408-debris"], session=s)
    assert s.get.call_count == 1  # stopped right after the first 403
    assert status["stations"].startswith("error")
    assert status["active"].startswith("skipped") and status["cosmos-1408-debris"].startswith("skipped")
    assert old.read_bytes() == CSV  # cache untouched
    assert (config.CATALOG_SNAPSHOT_DIR / "active.csv").exists()  # snapshot still refreshed from cache
