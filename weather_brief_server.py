#!/usr/bin/env python3
"""Serve Weather Brief and extract Squid GRIB data on demand."""

import json
import errno
import subprocess
import sys
import time
import webbrowser
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

LIFT_DIR = Path(__file__).resolve().parent
GRIB_DIR = LIFT_DIR / "Squid Gribs"
PORT = 8765
EXPEDITION_LAUNCHERS = [
    Path.home() / "Desktop" / "Start Expedition Builder.command",
    Path.home() / "Desktop" / "expedition-course-tool" / "Start Server (background).command",
]
EXPEDITION_DIR = Path.home() / "Desktop" / "expedition-course-tool"
EXPEDITION_SERVE = EXPEDITION_DIR / "serve.py"

try:
    import extract_squid_grib as grib_io
    GRIB_IMPORT_ERROR = None
except Exception as e:
    grib_io = None
    GRIB_IMPORT_ERROR = e


def grib_status(grib):
    stat = grib.stat()
    status = {
        "name": grib.name,
        "sizeBytes": stat.st_size,
        "sizeMB": round(stat.st_size / 1_000_000, 1),
        "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }
    if grib_io:
        status["modelLabel"] = grib_io.infer_model_label(grib.name)
        resolution = grib_io.infer_file_resolution_label(grib.name)
        if resolution:
            status["fileResolutionLabel"] = resolution
    return status


def grib_statuses():
    files = sorted(GRIB_DIR.glob("*.grb*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [grib_status(grib) for grib in files]


def latest_grib_status():
    statuses = grib_statuses()
    return statuses[0] if statuses else None


def float_query(qs, name, default):
    raw = qs.get(name, [default])[0]
    try:
        return float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid {name}: {raw}")


class WeatherBriefHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(LIFT_DIR), **kwargs)

    def log_message(self, fmt, *args):
        if args and str(args[0]).startswith("GET /api/"):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            latest = latest_grib_status()
            gribs = grib_statuses()
            self._json(
                200,
                {
                    "ok": True,
                    "dependencyOk": grib_io is not None,
                    "importError": str(GRIB_IMPORT_ERROR) if GRIB_IMPORT_ERROR else None,
                    "gribDir": str(GRIB_DIR),
                    "gribCount": len(gribs),
                    "latestGrib": latest["name"] if latest else None,
                    "latest": latest,
                    "bundleEndpoint": "/api/squid-grib-bundle",
                },
            )
            return

        if parsed.path == "/api/gribs":
            self._json(
                200,
                {
                    "ok": True,
                    "dependencyOk": grib_io is not None,
                    "importError": str(GRIB_IMPORT_ERROR) if GRIB_IMPORT_ERROR else None,
                    "gribDir": str(GRIB_DIR),
                    "gribs": grib_statuses(),
                    "bundleEndpoint": "/api/squid-grib-bundle",
                },
            )
            return

        if parsed.path == "/api/squid-grib":
            if grib_io is None:
                self._json(
                    503,
                    {
                        "error": "GRIB tools are not available. Run: python3 -m pip install eccodes cfgrib",
                        "detail": str(GRIB_IMPORT_ERROR),
                    },
                )
                return
            qs = parse_qs(parsed.query)
            try:
                lat = float_query(qs, "lat", "40.576")
                lon = float_query(qs, "lon", "14.376")
                grib_name = qs.get("file", [""])[0]
                if grib_name:
                    data = grib_io.extract_named(grib_name, lat, lon, write_file=True)
                else:
                    data = grib_io.extract_latest(lat, lon, write_file=True)
                self._json(200, data)
            except FileNotFoundError as e:
                self._json(404, {"error": str(e)})
            except Exception as e:
                self._json(400, {"error": str(e)})
            return

        if parsed.path == "/api/launch-expedition":
            my_port = int(self.server.server_address[1])
            payload = launch_expedition_tool(skip_port=my_port)
            self._json(200 if payload.get("ok") else 404, payload)
            return

        if parsed.path == "/api/expedition-health":
            my_port = int(self.server.server_address[1])
            port = find_expedition_port(skip_port=my_port)
            if port is None:
                self._json(200, {"ok": False, "running": False})
                return
            self._json(
                200,
                {
                    "ok": True,
                    "running": True,
                    "port": port,
                    "url": f"http://127.0.0.1:{port}/?v=6",
                },
            )
            return

        if parsed.path == "/api/open-meteo-marine":
            qs = parse_qs(parsed.query)
            try:
                lat = float_query(qs, "lat", "40.576")
                lon = float_query(qs, "lon", "14.376")
                start_date = qs.get("start_date", [""])[0]
                end_date = qs.get("end_date", start_date)[0] or start_date
                if not start_date:
                    raise ValueError("start_date is required")
                url = (
                    "https://marine-api.open-meteo.com/v1/marine"
                    f"?latitude={lat}&longitude={lon}"
                    "&hourly=wave_height,wave_direction"
                    "&timezone=Europe%2FRome"
                    f"&start_date={start_date}&end_date={end_date}"
                )
                with urlopen(url, timeout=30) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                self._json(resp.status, payload)
            except Exception as e:
                self._json(502, {"error": str(e)})
            return

        if parsed.path == "/api/squid-grib-bundle":
            if grib_io is None:
                self._json(
                    503,
                    {
                        "error": "GRIB tools are not available. Run: python3 -m pip install eccodes cfgrib",
                        "detail": str(GRIB_IMPORT_ERROR),
                    },
                )
                return
            qs = parse_qs(parsed.query)
            try:
                lat = float_query(qs, "lat", "40.576")
                lon = float_query(qs, "lon", "14.376")
                files = [name for name in qs.get("files", []) if name]
                if not files:
                    self._json(400, {"error": "Select at least one GRIB file (files query parameter required)."})
                    return
                data = grib_io.extract_bundle(lat, lon, files)
                self._json(200, data)
            except FileNotFoundError as e:
                self._json(404, {"error": str(e)})
            except Exception as e:
                self._json(400, {"error": str(e)})
            return

        if parsed.path in ("/", ""):
            self.path = "/index.html"
        return super().do_GET()

    def _json(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def weather_brief_is_running(port):
    try:
        with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as res:
            return json.loads(res.read()).get("ok") is True
    except Exception:
        return False


def open_weather_brief(port):
    url = f"http://127.0.0.1:{port}/"
    webbrowser.open(url)
    return url


def expedition_launcher_path() -> Path | None:
    for path in EXPEDITION_LAUNCHERS:
        if path.exists():
            return path
    return None


def find_expedition_port(skip_port: int | None = None) -> int | None:
    """Find SI → Expedition converter (not this Weather Brief server)."""
    for port in range(8765, 8785):
        if skip_port is not None and port == skip_port:
            continue
        try:
            with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.5) as res:
                payload = json.loads(res.read())
        except Exception:
            continue
        if payload.get("ok") and "tesseract" in payload and "gribCount" not in payload:
            iv = payload.get("import_version")
            if iv is not None and iv < 4:
                continue
            return port
    return None


def launch_expedition_tool(skip_port: int | None = None) -> dict:
    existing = find_expedition_port(skip_port=skip_port)
    if existing:
        url = f"http://127.0.0.1:{existing}/?v=6"
        return {
            "ok": True,
            "message": "Expedition converter is already running.",
            "url": url,
            "already_running": True,
        }

    if not EXPEDITION_SERVE.exists():
        launcher = expedition_launcher_path()
        if launcher is None:
            return {
                "ok": False,
                "error": "expedition-course-tool not found on Desktop.",
            }
        subprocess.Popen(["open", str(launcher)], start_new_session=True)
        return {
            "ok": True,
            "message": f"Opened {launcher.name}.",
            "url": None,
        }

    subprocess.Popen(
        [sys.executable, str(EXPEDITION_SERVE), "--no-browser"],
        cwd=str(EXPEDITION_DIR),
        start_new_session=True,
    )

    for _ in range(40):
        time.sleep(0.25)
        port = find_expedition_port(skip_port=skip_port)
        if port:
            url = f"http://127.0.0.1:{port}/?v=6"
            return {
                "ok": True,
                "message": "Expedition converter started.",
                "url": url,
                "already_running": False,
            }

    return {
        "ok": True,
        "message": "Expedition converter is starting… if nothing opens, check /tmp/expedition-serve.log",
        "url": None,
    }


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    url = f"http://127.0.0.1:{port}/"

    if weather_brief_is_running(port):
        print(f"Weather Brief already running - opening {url}")
        open_weather_brief(port)
        return

    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), WeatherBriefHandler)
    except OSError as e:
        if e.errno != errno.EADDRINUSE:
            raise
        if weather_brief_is_running(port):
            print(f"Weather Brief already running - opening {url}")
            open_weather_brief(port)
            return
        print(
            f"Port {port} is in use by another program.\n"
            f"Close it, or start Weather Brief on another port:\n"
            f"  python3 weather_brief_server.py 8766",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Weather Brief: {url}")
    print(f"Squid GRIB folder: {GRIB_DIR}")
    if GRIB_IMPORT_ERROR:
        print("GRIB tools unavailable.")
        print(f"Python error: {GRIB_IMPORT_ERROR}")
        print("Install with: python3 -m pip install eccodes cfgrib")
    latest = latest_grib_status()
    if latest:
        label = latest.get("modelLabel", "Squid GRIB")
        print(f"Latest GRIB: {latest['name']} ({label}, {latest['sizeMB']} MB)")
    else:
        print("No GRIB in folder yet - download in Squid X first.")
    open_weather_brief(port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
