"""Cached downloads: ESA Kelvins CDMs, CelesTrak GP/OMM catalog groups, CelesTrak space weather.

CelesTrak rate limit (SPEC 5.2) is mandatory:
  * each group is cached to data/raw/celestrak/<group>.csv with a timestamp sidecar;
  * a cached file younger than 2 hours is never re-downloaded;
  * on any non-200 response we STOP hitting CelesTrak for this run and keep using the cache;
  * a copy is kept in artifacts/catalog_snapshot/ so the demo works offline.

Run: python -m orbitguard.download [--kelvins] [--celestrak] [--space-weather]  (default: all)
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

from orbitguard import config

log = logging.getLogger("orbitguard.download")

USER_AGENT = "OrbitGuard/0.1 (KLE Tech Hackfest 2026; cached, rate-limited)"


class CelesTrakBlocked(RuntimeError):
    """Raised after a non-200 from CelesTrak; callers must stop requesting."""


# --- cache helpers -----------------------------------------------------------

def _meta_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".meta.json")


def file_age_hours(path: Path) -> float | None:
    """Age of a cached download in hours (from its sidecar timestamp, else mtime); None if missing."""
    if not path.exists():
        return None
    meta = _meta_path(path)
    ts = None
    if meta.exists():
        try:
            ts = json.loads(meta.read_text())["downloaded_at_unix"]
        except (ValueError, KeyError):
            ts = None
    if ts is None:
        ts = path.stat().st_mtime
    return max(0.0, (time.time() - ts) / 3600.0)


def _write_with_meta(path: Path, content: bytes, url: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(content)
    tmp.replace(path)
    now = time.time()
    _meta_path(path).write_text(json.dumps({
        "url": url,
        "downloaded_at_unix": now,
        "downloaded_at_utc": datetime.fromtimestamp(now, timezone.utc).isoformat(),
        "bytes": len(content),
    }, indent=2))


# --- CelesTrak ---------------------------------------------------------------

def celestrak_group_path(group: str) -> Path:
    return config.CELESTRAK_DIR / f"{group}.csv"


def fetch_celestrak_group(group: str, *, session=requests, min_age_hours: float = config.CELESTRAK_MIN_AGE_HOURS) -> Path:
    """Return the cached OMM CSV for a group, downloading only if the cache is missing or stale.

    Raises CelesTrakBlocked on a non-200 response (caller must stop all further CelesTrak requests).
    """
    path = celestrak_group_path(group)
    age = file_age_hours(path)
    if age is not None and age < min_age_hours:
        log.info("celestrak %-22s cached (%.2f h old) — not re-downloading", group, age)
        return path

    url = config.CELESTRAK_GP_URL
    params = {"GROUP": group, "FORMAT": "csv"}
    resp = session.get(url, params=params, timeout=config.HTTP_TIMEOUT_S, headers={"User-Agent": USER_AGENT})
    if resp.status_code != 200:
        raise CelesTrakBlocked(f"CelesTrak returned HTTP {resp.status_code} for group '{group}'")
    body = resp.content
    # CelesTrak returns 200 with a plain-text message for unknown groups / "data has not updated".
    if not body.lstrip().startswith(b"OBJECT_NAME"):
        raise CelesTrakBlocked(f"CelesTrak returned non-CSV body for '{group}': {body[:120]!r}")
    _write_with_meta(path, body, f"{url}?GROUP={group}&FORMAT=csv")
    log.info("celestrak %-22s downloaded %d bytes", group, len(body))
    return path


def download_celestrak(groups: list[str] | None = None, *, session=requests) -> dict[str, str]:
    """Refresh every group (respecting the cache), then snapshot to artifacts/. Returns {group: status}."""
    groups = groups or config.CELESTRAK_GROUPS
    status: dict[str, str] = {}
    blocked = False
    for group in groups:
        if blocked:
            status[group] = "skipped (stopped after earlier non-200)"
            continue
        try:
            fetch_celestrak_group(group, session=session)
            status[group] = "ok"
        except CelesTrakBlocked as exc:
            log.warning("%s — stopping CelesTrak requests for this run, using cache", exc)
            status[group] = f"error: {exc}"
            blocked = True
        except requests.RequestException as exc:
            log.warning("celestrak %s network error: %s — stopping, using cache", group, exc)
            status[group] = f"network error: {exc}"
            blocked = True
    snapshot_catalog()
    return status


def snapshot_catalog() -> None:
    """Copy cached group CSVs into artifacts/catalog_snapshot/ (committed; offline demo fallback)."""
    config.CATALOG_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    for src in config.CELESTRAK_DIR.glob("*.csv"):
        shutil.copy2(src, config.CATALOG_SNAPSHOT_DIR / src.name)
        meta = _meta_path(src)
        if meta.exists():
            shutil.copy2(meta, config.CATALOG_SNAPSHOT_DIR / meta.name)


def catalog_csv_paths() -> list[Path]:
    """Best available catalog files: live cache first, else the committed snapshot."""
    paths = sorted(config.CELESTRAK_DIR.glob("*.csv"))
    return paths or sorted(config.CATALOG_SNAPSHOT_DIR.glob("*.csv"))


def catalog_age_hours() -> float | None:
    ages = [a for a in (file_age_hours(p) for p in catalog_csv_paths()) if a is not None]
    return min(ages) if ages else None


# --- Space weather -----------------------------------------------------------

def space_weather_path() -> Path:
    return config.SPACE_WEATHER_DIR / "SW-All.csv"


def download_space_weather(*, session=requests) -> str:
    path = space_weather_path()
    age = file_age_hours(path)
    if age is not None and age < config.SPACE_WEATHER_MIN_AGE_HOURS:
        log.info("space weather cached (%.1f h old) — not re-downloading", age)
        return "cached"
    try:
        resp = session.get(config.SPACE_WEATHER_URL, timeout=config.HTTP_TIMEOUT_S, headers={"User-Agent": USER_AGENT})
    except requests.RequestException as exc:
        log.warning("space weather network error: %s — using cache if any", exc)
        return f"network error: {exc}"
    if resp.status_code != 200:
        log.warning("space weather HTTP %s — using cache if any", resp.status_code)
        return f"error: HTTP {resp.status_code}"
    _write_with_meta(path, resp.content, config.SPACE_WEATHER_URL)
    # Keep a copy next to the catalog snapshot for the offline demo.
    config.CATALOG_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, config.CATALOG_SNAPSHOT_DIR / path.name)
    return "ok"


# --- ESA Kelvins -------------------------------------------------------------

KELVINS_MANUAL_MSG = f"""
Could not download the ESA Kelvins Collision Avoidance dataset automatically.
Please download it manually and place the CSVs in:  {config.KELVINS_DIR}
  * Zenodo:  https://zenodo.org/records/{config.KELVINS_ZENODO_RECORD}
             (file 'Collision Avoidance Challenge - Dataset.zip' — unzip it there)
  * Mirror:  {config.KELVINS_MIRROR_BASE}/train_data.zip  and  .../test_data.csv
Expected result: {config.KELVINS_DIR / 'train_data.csv'} and {config.KELVINS_DIR / 'test_data.csv'}
"""


def kelvins_files() -> dict[str, Path | None]:
    """Locate train/test CSVs anywhere under data/raw/kelvins/ (zip layouts vary)."""
    found: dict[str, Path | None] = {"train": None, "test": None}
    for p in config.KELVINS_DIR.rglob("*.csv"):
        name = p.name.lower()
        if "train" in name and found["train"] is None:
            found["train"] = p
        elif "test" in name and found["test"] is None:
            found["test"] = p
    return found


def _stream_to(url: str, dest: Path, session=requests) -> bool:
    log.info("downloading %s", url)
    try:
        with session.get(url, stream=True, timeout=config.HTTP_TIMEOUT_S, headers={"User-Agent": USER_AGENT}) as r:
            if r.status_code != 200:
                log.warning("HTTP %s for %s", r.status_code, url)
                return False
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(dest.suffix + ".part")
            with open(tmp, "wb") as fh:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    fh.write(chunk)
            tmp.replace(dest)
        return True
    except requests.RequestException as exc:
        log.warning("network error for %s: %s", url, exc)
        return False


def _extract_zips(directory: Path) -> None:
    for z in directory.glob("*.zip"):
        log.info("extracting %s", z.name)
        with zipfile.ZipFile(z) as zf:
            zf.extractall(directory)
    # Nested zips (the Zenodo archive wraps train_data.zip)
    for z in directory.rglob("*.zip"):
        if z.parent == directory:
            continue
        with zipfile.ZipFile(z) as zf:
            zf.extractall(z.parent)


def download_kelvins(*, session=requests) -> bool:
    """Download + extract the Kelvins dataset once. Returns True when train/test CSVs exist."""
    files = kelvins_files()
    if files["train"] and files["test"]:
        log.info("kelvins already present: %s, %s", files["train"].name, files["test"].name)
        return True
    config.KELVINS_DIR.mkdir(parents=True, exist_ok=True)

    # 1) Zenodo: ask the API for the file links.
    try:
        r = session.get(config.KELVINS_ZENODO_API, timeout=config.HTTP_TIMEOUT_S, headers={"User-Agent": USER_AGENT})
        if r.status_code == 200:
            for f in r.json().get("files", []):
                key = f.get("key", "")
                link = f.get("links", {}).get("self") or f.get("links", {}).get("download")
                if link and key.lower().endswith((".zip", ".csv")):
                    _stream_to(link, config.KELVINS_DIR / key, session)
        else:
            log.warning("Zenodo API HTTP %s", r.status_code)
    except (requests.RequestException, ValueError) as exc:
        log.warning("Zenodo API failed: %s", exc)
    _extract_zips(config.KELVINS_DIR)

    # 2) Kelvins mirror for anything still missing.
    files = kelvins_files()
    if not (files["train"] and files["test"]):
        for name in config.KELVINS_MIRROR_FILES:
            _stream_to(f"{config.KELVINS_MIRROR_BASE}/{name}", config.KELVINS_DIR / name, session)
        _extract_zips(config.KELVINS_DIR)

    files = kelvins_files()
    if files["train"] and files["test"]:
        log.info("kelvins ready: %s, %s", files["train"], files["test"])
        return True
    print(KELVINS_MANUAL_MSG)
    return False


# --- CLI ---------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="Download OrbitGuard data (cached).")
    ap.add_argument("--kelvins", action="store_true")
    ap.add_argument("--celestrak", action="store_true")
    ap.add_argument("--space-weather", action="store_true")
    args = ap.parse_args(argv)
    do_all = not (args.kelvins or args.celestrak or args.space_weather)

    ok = True
    if do_all or args.kelvins:
        ok &= download_kelvins()
    if do_all or args.celestrak:
        status = download_celestrak()
        for g, s in status.items():
            print(f"  celestrak {g:<22} {s}")
    if do_all or args.space_weather:
        print(f"  space weather          {download_space_weather()}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
