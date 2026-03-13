#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import html
import json
import logging
import math
import os
import re
import socket
import subprocess
import threading
import time
from datetime import datetime, timezone
from email.utils import formatdate
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from skyfield.api import EarthSatellite, load, wgs84

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
CACHE_DIR = BASE_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

GPSD_HOST = os.environ.get("GPSD_HOST", "127.0.0.1")
GPSD_PORT = int(os.environ.get("GPSD_PORT", "2947"))
TLE_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=gps-ops&FORMAT=tle"
GROUP_TABLE_URL = "https://celestrak.org/NORAD/elements/table.php?GROUP=gps-ops"
QZSS_GPS_SATELLITES_URL = "https://qzss.go.jp/en/technical/satellites/"
TLE_CACHE_PATH = CACHE_DIR / "gps-ops.tle"
SATELLITE_METADATA_CACHE_PATH = CACHE_DIR / "gps-ops-metadata.json"
PRN_RE = re.compile(r"PRN\s+0*(\d+)")
TABLE_ROW_RE = re.compile(
    r"<td class=small>(?P<intl>\d{4}-\d{3}[A-Z]?) .*?</td>\s*<td class=small>(?P<norad>\d+)</td>\s*<td class=small>(?P<name>[^<]+)",
    re.S,
)
QZSS_GPS_ROW_RE = re.compile(
    r"<td[^>]*>\s*(?P<prn>\d+)\s*</td>\s*<td[^>]*>\s*\d+\s*</td>\s*<td[^>]*>[^<]+</td>\s*<td[^>]*>\s*(?P<launch>\d{4}/\d{1,2}/\d{1,2})\s*</td>",
    re.S,
)
GPS_LOCAL_TZ_OFFSET_MINUTES = -180
GPS_LOCAL_TZ_NAME = "UTC-3"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def iso_to_epoch(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def fetch_text(url: str) -> str:
    return subprocess.run(
        [
            "curl",
            "-4",
            "-fsSL",
            "--connect-timeout",
            "10",
            "--max-time",
            "20",
            url,
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


class GpsdReader:
    def __init__(self, host: str = GPSD_HOST, port: int = GPSD_PORT) -> None:
        self.host = host
        self.port = port
        self._lock = threading.Lock()
        self._device: dict[str, Any] | None = None
        self._tpv: dict[str, Any] | None = None
        self._sky: dict[str, Any] | None = None
        self._error: str | None = None
        self._last_message_at: float | None = None
        self._thread = threading.Thread(target=self._run, daemon=True, name="gpsd-reader")

    def start(self) -> None:
        self._thread.start()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "device": copy.deepcopy(self._device),
                "tpv": copy.deepcopy(self._tpv),
                "sky": copy.deepcopy(self._sky),
                "error": self._error,
                "last_message_at": self._last_message_at,
            }

    def _run(self) -> None:
        while True:
            try:
                logging.info("Connecting to gpsd at %s:%s", self.host, self.port)
                with socket.create_connection((self.host, self.port), timeout=10) as sock:
                    sock.settimeout(20)
                    sock.sendall(b'?WATCH={"enable":true,"json":true}\n')
                    with sock.makefile("r", encoding="utf-8", errors="replace") as stream:
                        for raw_line in stream:
                            line = raw_line.strip()
                            if not line:
                                continue
                            try:
                                payload = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            self._handle_payload(payload)
            except Exception as exc:
                with self._lock:
                    self._error = str(exc)
                logging.warning("gpsd connection failed: %s", exc)
                time.sleep(2)

    def _handle_payload(self, payload: dict[str, Any]) -> None:
        msg_class = payload.get("class")
        with self._lock:
            self._last_message_at = time.time()
            self._error = None
            if msg_class == "DEVICE":
                self._device = payload
            elif msg_class == "DEVICES":
                devices = payload.get("devices") or []
                if devices:
                    self._device = devices[0]
            elif msg_class == "TPV" and payload.get("mode", 0) >= 2:
                self._tpv = payload
            elif msg_class == "SKY" and payload.get("satellites") is not None:
                self._sky = payload


class GpsOpsCatalog:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._timescale = load.timescale()
        self._satellites_by_prn: dict[int, dict[str, Any]] = {}
        self._launch_metadata: dict[str, dict[str, Any]] = {}
        self._qzss_launch_dates_by_prn: dict[int, str] = {}
        self._last_fetch_at: float | None = None
        self._last_error: str | None = None
        self._thread = threading.Thread(target=self._run, daemon=True, name="gps-ops-catalog")

    def start(self) -> None:
        self._load_metadata_cache()
        self._refresh_qzss_launch_dates()
        self._load_cache()
        self._thread.start()

    def snapshot_meta(self) -> dict[str, Any]:
        with self._lock:
            return {
                "count": len(self._satellites_by_prn),
                "last_fetch_at": self._last_fetch_at,
                "last_fetch_iso": (
                    datetime.fromtimestamp(self._last_fetch_at, tz=timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z")
                    if self._last_fetch_at
                    else None
                ),
                "last_error": self._last_error,
            }

    def positions_for_prns(self, prns: list[int]) -> dict[int, dict[str, Any]]:
        with self._lock:
            catalog = {prn: self._satellites_by_prn.get(prn) for prn in prns}

        positions: dict[int, dict[str, Any]] = {}
        now = self._timescale.now()
        for prn, entry in catalog.items():
            if not entry:
                continue
            sat: EarthSatellite = entry["satellite"]
            geocentric = sat.at(now)
            subpoint = wgs84.subpoint(geocentric)
            altitude_km = float(subpoint.elevation.km)
            velocity = geocentric.velocity.km_per_s
            speed_km_s = math.sqrt(sum(float(component) ** 2 for component in velocity))
            orbital_period_minutes = self._orbital_period_minutes(sat)
            positions[prn] = {
                "prn": prn,
                "name": entry["name"],
                "norad_id": entry["norad_id"],
                "intl_designator": entry.get("intl_designator"),
                "image_url": entry.get("image_url"),
                "block": entry.get("block"),
                "launch": entry.get("launch"),
                "orbit": {
                    "speed_kmh": round(speed_km_s * 3600, 1),
                    "period_minutes": round(orbital_period_minutes, 1) if orbital_period_minutes else None,
                },
                "subpoint": {
                    "lat": round(float(subpoint.latitude.degrees), 6),
                    "lon": round(float(subpoint.longitude.degrees), 6),
                    "altitude_km": round(altitude_km, 2),
                    "display_altitude": round(self._display_altitude(altitude_km), 4),
                },
            }
        return positions

    def _run(self) -> None:
        while True:
            try:
                self._refresh_catalog()
            except Exception as exc:
                with self._lock:
                    self._last_error = str(exc)
                logging.warning("TLE refresh failed: %s", exc)
            time.sleep(3600)

    def _refresh_catalog(self) -> None:
        raw_tle = fetch_text(TLE_URL)
        raw_tle = raw_tle.strip()
        if not raw_tle:
            raise RuntimeError("empty TLE response")

        group_metadata = self._fetch_group_metadata()
        self._refresh_qzss_launch_dates()
        TLE_CACHE_PATH.write_text(raw_tle + "\n", encoding="utf-8")
        parsed = self._parse_tle_block(raw_tle, group_metadata)
        self._save_metadata_cache()
        with self._lock:
            self._satellites_by_prn = parsed
            self._last_fetch_at = time.time()
            self._last_error = None
        logging.info("Loaded %s GPS operational TLEs", len(parsed))

    def _load_cache(self) -> None:
        if not TLE_CACHE_PATH.exists():
            return
        try:
            group_metadata: dict[int, dict[str, Any]] = {}
            try:
                group_metadata = self._fetch_group_metadata()
            except Exception as exc:
                logging.warning("Unable to enrich cached TLEs with group metadata: %s", exc)
            parsed = self._parse_tle_block(TLE_CACHE_PATH.read_text(encoding="utf-8"), group_metadata)
            with self._lock:
                self._satellites_by_prn = parsed
                self._last_error = None
            logging.info("Loaded %s cached GPS TLEs", len(parsed))
        except Exception as exc:
            logging.warning("Unable to load cached TLEs: %s", exc)

    def _parse_tle_block(
        self,
        raw_tle: str,
        group_metadata: dict[int, dict[str, Any]] | None = None,
    ) -> dict[int, dict[str, Any]]:
        lines = [line.rstrip() for line in raw_tle.splitlines() if line.strip()]
        if len(lines) < 3:
            raise RuntimeError("invalid TLE payload")

        catalog: dict[int, dict[str, Any]] = {}
        for index in range(0, len(lines) - 2, 3):
            name, line1, line2 = lines[index], lines[index + 1], lines[index + 2]
            match = PRN_RE.search(name)
            if not match:
                continue
            prn = int(match.group(1))
            norad_id = int(line1.split()[1][:5])
            metadata = (group_metadata or {}).get(norad_id, {})
            intl_designator = metadata.get("intl_designator")
            block = self._block_from_name(name)
            launch = self._resolve_launch_metadata(intl_designator)
            qzss_launch_date = self._qzss_launch_dates_by_prn.get(prn)
            if qzss_launch_date:
                launch = self._merge_launch_metadata(launch, qzss_launch_date)
            catalog[prn] = {
                "name": name.strip(),
                "norad_id": norad_id,
                "intl_designator": intl_designator,
                "block": block,
                "image_url": self._image_url_for_block(block),
                "launch": launch,
                "satellite": EarthSatellite(line1, line2, name, self._timescale),
            }
        if not catalog:
            raise RuntimeError("no PRNs found in TLE payload")
        return catalog

    def _fetch_group_metadata(self) -> dict[int, dict[str, Any]]:
        group_html = fetch_text(GROUP_TABLE_URL)
        metadata: dict[int, dict[str, Any]] = {}
        for match in TABLE_ROW_RE.finditer(group_html):
            norad_id = int(match.group("norad"))
            metadata[norad_id] = {
                "intl_designator": match.group("intl").strip(),
                "name": html.unescape(match.group("name").strip()),
            }
        return metadata

    def _resolve_launch_metadata(self, intl_designator: str | None) -> dict[str, Any] | None:
        if not intl_designator:
            return None
        launch_id = intl_designator[:-1] if intl_designator[-1].isalpha() else intl_designator
        cached = self._launch_metadata.get(launch_id)
        if cached:
            return copy.deepcopy(cached)
        return None

    def _fetch_launch_metadata(self, launch_id: str) -> dict[str, Any] | None:
        year = launch_id.split("-")[0]
        html_doc = fetch_text(f"https://celestrak.org/satcat/{year}/{launch_id}.php")
        text = html.unescape(re.sub(r"<[^>]+>", " ", html_doc))
        normalized = re.sub(r"\s+", " ", text).strip()

        launch_match = re.search(
            r"launched by a[n]?\s+(?P<vehicle>.+?)\s+rocket from\s+(?P<site>.+?)\s+at\s+(?P<time>\d{1,2}:\d{2})\s+UT\s+on\s+(?P<date>\d{4}\s+[A-Za-z]+\s+\d{1,2})",
            normalized,
            re.IGNORECASE,
        )
        if not launch_match:
            return None

        raw_date = launch_match.group("date")
        parsed_date = None
        for fmt in ("%Y %B %d", "%Y %b %d"):
            try:
                parsed_date = datetime.strptime(raw_date, fmt)
                break
            except ValueError:
                continue
        if parsed_date is None:
            return None
        launch_date = parsed_date.strftime("%d/%m/%Y")
        return {
            "date_localized": launch_date,
            "time_utc": launch_match.group("time"),
            "site": launch_match.group("site").strip(" ."),
            "vehicle": launch_match.group("vehicle").strip(" ."),
        }

    def _load_metadata_cache(self) -> None:
        if not SATELLITE_METADATA_CACHE_PATH.exists():
            return
        try:
            payload = json.loads(SATELLITE_METADATA_CACHE_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            logging.warning("Unable to load metadata cache: %s", exc)
            return
        launches = payload.get("launches")
        if isinstance(launches, dict):
            self._launch_metadata = launches
        qzss_dates = payload.get("qzss_launch_dates_by_prn")
        if isinstance(qzss_dates, dict):
            self._qzss_launch_dates_by_prn = {
                int(prn): date for prn, date in qzss_dates.items() if isinstance(date, str)
            }

    def _save_metadata_cache(self) -> None:
        payload = {
            "launches": self._launch_metadata,
            "qzss_launch_dates_by_prn": self._qzss_launch_dates_by_prn,
        }
        SATELLITE_METADATA_CACHE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _refresh_qzss_launch_dates(self) -> None:
        if self._qzss_launch_dates_by_prn:
            return
        try:
            html_doc = fetch_text(QZSS_GPS_SATELLITES_URL)
        except Exception as exc:
            logging.warning("Unable to fetch QZSS GPS launch dates: %s", exc)
            return
        parsed: dict[int, str] = {}
        for match in QZSS_GPS_ROW_RE.finditer(html_doc):
            prn = int(match.group("prn"))
            launch_date = datetime.strptime(match.group("launch"), "%Y/%m/%d").strftime("%d/%m/%Y")
            parsed[prn] = launch_date
        if parsed:
            self._qzss_launch_dates_by_prn = parsed
            self._save_metadata_cache()

    @staticmethod
    def _merge_launch_metadata(launch: dict[str, Any] | None, qzss_launch_date: str) -> dict[str, Any]:
        base = copy.deepcopy(launch) if launch else {}
        base.setdefault("date_localized", qzss_launch_date)
        return base

    @staticmethod
    def _block_from_name(name: str) -> str:
        upper_name = name.upper()
        if "BIII" in upper_name:
            return "gps-block-iii"
        if "BIIF" in upper_name:
            return "gps-block-iif"
        if "BIIRM" in upper_name:
            return "gps-block-iirm"
        if "BIIR" in upper_name:
            return "gps-block-iir"
        return "gps-block-generic"

    @staticmethod
    def _image_url_for_block(block: str) -> str:
        if block == "gps-block-generic":
            return "/assets/gps-block-generic.svg"
        return f"/assets/{block}.jpg"

    @staticmethod
    def _orbital_period_minutes(sat: EarthSatellite) -> float | None:
        mean_motion = getattr(sat.model, "no_kozai", None)
        if not mean_motion:
            return None
        return (2 * math.pi) / float(mean_motion)

    @staticmethod
    def _display_altitude(altitude_km: float) -> float:
        scaled = 0.18 + min(max(altitude_km, 0.0), 25000.0) / 25000.0 * 0.52
        return min(0.72, max(0.18, scaled))


class AppState:
    def __init__(self) -> None:
        self.gpsd = GpsdReader()
        self.tles = GpsOpsCatalog()

    def start(self) -> None:
        self.gpsd.start()
        self.tles.start()

    def build_state(self) -> dict[str, Any]:
        gps_snapshot = self.gpsd.snapshot()
        tle_meta = self.tles.snapshot_meta()
        tpv = gps_snapshot.get("tpv") or {}
        sky = gps_snapshot.get("sky") or {}

        receiver = self._build_receiver_payload(tpv, gps_snapshot.get("last_message_at"))
        visible_satellites = sky.get("satellites") or []
        gps_visible = [sat for sat in visible_satellites if sat.get("gnssid") == 0]
        gps_used = [sat for sat in gps_visible if sat.get("used")]
        position_index = self.tles.positions_for_prns([int(sat["PRN"]) for sat in gps_visible if "PRN" in sat])

        satellites_visible: list[dict[str, Any]] = []
        for sat in sorted(gps_visible, key=lambda item: (-float(item.get("ss", 0.0)), int(item.get("PRN", 0)))):
            prn = int(sat["PRN"])
            sat_state = {
                "prn": prn,
                "azimuth_deg": sat.get("az"),
                "elevation_deg": sat.get("el"),
                "signal_dbhz": sat.get("ss"),
                "used": bool(sat.get("used")),
                "health": sat.get("health"),
            }
            if prn in position_index:
                sat_state.update(position_index[prn])
            satellites_visible.append(sat_state)

        satellites_used = [sat for sat in satellites_visible if sat.get("used")]

        return {
            "generated_at": utc_now_iso(),
            "tz_offset_minutes": GPS_LOCAL_TZ_OFFSET_MINUTES,
            "tz_name": GPS_LOCAL_TZ_NAME,
            "receiver": receiver,
            "gpsd": {
                "device": gps_snapshot.get("device"),
                "last_message_at": gps_snapshot.get("last_message_at"),
                "error": gps_snapshot.get("error"),
            },
            "sky": {
                "hdop": sky.get("hdop"),
                "pdop": sky.get("pdop"),
                "vdop": sky.get("vdop"),
                "n_satellites": sky.get("nSat"),
                "used_satellites": sky.get("uSat"),
                "gps_visible": len(gps_visible),
                "gps_used": len(gps_used),
            },
            "tle": tle_meta,
            "satellites_visible": satellites_visible,
            "satellites_used": satellites_used,
            "gps_visible_prns": sorted(int(sat["PRN"]) for sat in gps_visible if "PRN" in sat),
        }

    @staticmethod
    def _build_receiver_payload(tpv: dict[str, Any], last_message_at: float | None) -> dict[str, Any] | None:
        if "lat" not in tpv or "lon" not in tpv:
            return None
        fix_time_epoch = iso_to_epoch(tpv.get("time"))
        return {
            "lat": round(float(tpv["lat"]), 8),
            "lon": round(float(tpv["lon"]), 8),
            "altitude_m": round(float(tpv.get("altMSL", tpv.get("alt", 0.0))), 2),
            "mode": int(tpv.get("mode", 0)),
            "speed_ms": round(float(tpv.get("speed", 0.0)), 3),
            "track_deg": round(float(tpv.get("track", 0.0)), 2),
            "horizontal_error_m": round(float(tpv.get("eph", 0.0)), 2),
            "vertical_error_m": round(float(tpv.get("epv", 0.0)), 2),
            "timestamp": tpv.get("time"),
            "age_seconds": round(max(0.0, time.time() - fix_time_epoch), 1) if fix_time_epoch else None,
            "last_message_age_seconds": round(max(0.0, time.time() - last_message_at), 1) if last_message_at else None,
        }


class GpsGlobeHandler(SimpleHTTPRequestHandler):
    server_version = "GPSGlobe/1.0"
    app_state: AppState

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            self._handle_json(self.app_state.build_state())
            return
        if parsed.path == "/healthz":
            self._handle_json({"ok": True, "time": utc_now_iso()}, status=HTTPStatus.OK)
            return
        if parsed.path in {"", "/"}:
            self.path = "/index.html"
        else:
            self.path = parsed.path
        super().do_GET()

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt: str, *args: Any) -> None:
        logging.info("%s - %s", self.address_string(), fmt % args)

    def _handle_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Last-Modified", formatdate(timeval=None, usegmt=True))
        self.end_headers()
        self.wfile.write(raw)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GPS globe web app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18196)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    app_state = AppState()
    app_state.start()
    GpsGlobeHandler.app_state = app_state

    server = ThreadingHTTPServer((args.host, args.port), GpsGlobeHandler)
    logging.info("Serving GPS globe on http://%s:%s", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Shutting down")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
