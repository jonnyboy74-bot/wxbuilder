#!/usr/bin/env python3
"""Extract TWS/TWD/gust at a point from Squid X GRIBs in ./Squid Gribs/ → squid_forecast.json"""

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import eccodes

LIFT_DIR = Path(__file__).resolve().parent
GRIB_DIR = LIFT_DIR / "Squid Gribs"
OUT_FILE = LIFT_DIR / "squid_forecast.json"
KT_PER_MS = 1.94384
MAX_COMPONENT_MS = 150
MAX_SPEED_MS = 150
MAX_GUST_MS = 150
MAX_CAPE = 20000
MAX_PRECIP_MM = 1000
MAX_WAVE_M = 50
EARTH_KM_PER_DEG = 111.32

CAPE_SHORT_NAMES = {"cape", "mucape"}
CAPE_PARAM_IDS = {59, 228001, 260255}
CAPE_GRIB2_IDS = {(0, 7, 6)}
PRECIP_SHORT_NAMES = {"tp", "prate", "precip", "precipitation", "apcp", "lsp", "cp"}
PRECIP_PARAM_IDS = {52, 61, 142, 143, 228, 228228, 3059}
PRECIP_GRIB2_IDS = {(0, 1, 8)}
TEMP_SHORT_NAMES = {"2t", "t2m"}
TEMP_PARAM_IDS = {167}
WAVE_HEIGHT_SHORT_NAMES = {"swh", "htsgw", "shww", "shts"}
WAVE_HEIGHT_PARAM_IDS = {140229, 140234, 140237, 100, 102}
WAVE_HEIGHT_GRIB2_IDS = {(10, 0, 3)}
WAVE_DIR_SHORT_NAMES = {"mwd", "dirpw", "mdww", "dwww", "wvdir", "swdir"}
WAVE_DIR_PARAM_IDS = {140230, 260232, 260233, 3104, 101}
WAVE_DIR_GRIB2_IDS = {(10, 0, 4)}


def latest_grib():
    files = candidate_gribs()
    return files[0] if files else None


def candidate_gribs():
    return sorted(GRIB_DIR.glob("*.grb*"), key=lambda p: p.stat().st_mtime, reverse=True)


def resolve_grib_file(name):
    path = (GRIB_DIR / name).resolve()
    grib_dir = GRIB_DIR.resolve()
    if grib_dir not in path.parents or path.name != name:
        raise ValueError("Invalid GRIB filename")
    if not path.exists():
        raise FileNotFoundError(f"No GRIB file named {name}")
    return path


def message_key(gid):
    return (
        eccodes.codes_get(gid, "dataDate"),
        eccodes.codes_get(gid, "dataTime"),
        eccodes.codes_get(gid, "step"),
        eccodes.codes_get(gid, "shortName"),
    )


def safe_codes_get(gid, key, default=None):
    try:
        return eccodes.codes_get(gid, key)
    except Exception:
        return default


def grib_text(gid, key):
    value = safe_codes_get(gid, key, "")
    return str(value or "").strip().lower()


def grib_int(gid, key):
    value = safe_codes_get(gid, key)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def grib2_parameter_id(gid):
    values = (
        grib_int(gid, "discipline"),
        grib_int(gid, "parameterCategory"),
        grib_int(gid, "parameterNumber"),
    )
    return values if all(value is not None for value in values) else None


def is_grib2_parameter(gid, ids):
    return grib2_parameter_id(gid) in ids


def wave_height_rank(gid):
    short_name = grib_text(gid, "shortName")
    name = grib_text(gid, "name")
    param_id = grib_int(gid, "paramId")
    if short_name in ("swh", "htsgw") or param_id in (140229, 100) or is_grib2_parameter(gid, WAVE_HEIGHT_GRIB2_IDS):
        return 30
    if short_name == "shts" or param_id == 140237 or "total swell" in name:
        return 20
    if short_name == "shww" or param_id == 140234 or "wind waves" in name:
        return 10
    return 1


def wave_direction_rank(gid):
    short_name = grib_text(gid, "shortName")
    name = grib_text(gid, "name")
    param_id = grib_int(gid, "paramId")
    if short_name in ("mwd", "dirpw") or param_id in (140230, 260233) or "primary wave direction" in name:
        return 30
    if short_name in ("wvdir", "mdww", "dwww") or param_id in (260232, 101) or is_grib2_parameter(gid, WAVE_DIR_GRIB2_IDS):
        return 20
    if short_name == "swdir" or param_id == 3104 or "swell" in name:
        return 10
    return 1


def classify_message(gid):
    short_name = grib_text(gid, "shortName")
    name = grib_text(gid, "name")
    param_id = grib_int(gid, "paramId")

    if short_name == "10u":
        return "u"
    if short_name == "10v":
        return "v"
    if short_name == "gust":
        return "gust"
    if (
        short_name in CAPE_SHORT_NAMES
        or param_id in CAPE_PARAM_IDS
        or is_grib2_parameter(gid, CAPE_GRIB2_IDS)
        or "convective available potential energy" in name
    ):
        return "cape"
    if short_name in TEMP_SHORT_NAMES or param_id in TEMP_PARAM_IDS or name in ("2 metre temperature", "2 meter temperature"):
        return "temp"
    if (
        short_name in WAVE_HEIGHT_SHORT_NAMES
        or param_id in WAVE_HEIGHT_PARAM_IDS
        or is_grib2_parameter(gid, WAVE_HEIGHT_GRIB2_IDS)
        or ("significant" in name and "wave" in name and ("height" in name or "ht" in name))
    ):
        return "wave"
    if (
        short_name in WAVE_DIR_SHORT_NAMES
        or param_id in WAVE_DIR_PARAM_IDS
        or is_grib2_parameter(gid, WAVE_DIR_GRIB2_IDS)
        or ("wave" in name and "direction" in name)
    ):
        return "waveDir"
    if (
        short_name in PRECIP_SHORT_NAMES
        or param_id in PRECIP_PARAM_IDS
        or is_grib2_parameter(gid, PRECIP_GRIB2_IDS)
        or "precipitation" in name
        or "rain" in name
    ):
        return "precip"
    return None


def is_valid_grib_value(value, short_name):
    if value is None:
        return False
    if not math.isfinite(value):
        return False
    if short_name in ("10u", "10v"):
        return abs(value) <= MAX_COMPONENT_MS
    if short_name == "gust":
        return 0 <= value <= MAX_GUST_MS
    return True


def is_valid_field_value(value, field):
    if value is None or not math.isfinite(value):
        return False
    if field == "cape":
        return 0 <= value <= MAX_CAPE
    if field == "precip":
        return 0 <= value <= MAX_PRECIP_MM
    if field == "temp":
        return -100 <= value <= 70
    if field == "wave":
        return 0 <= value <= MAX_WAVE_M
    if field == "waveDir":
        return 0 <= value <= 360
    return True


def convert_temperature(value, gid):
    units = grib_text(gid, "units")
    if units in ("k", "kelvin") or value > 150:
        return value - 273.15
    return value


def convert_precip_to_mm(value, gid):
    units = grib_text(gid, "units")
    if "kg" in units and ("m**-2" in units or "m-2" in units):
        return value
    if units in ("m", "metre", "meter"):
        return value * 1000
    return value


def is_precip_rate(gid):
    short_name = grib_text(gid, "shortName")
    units = grib_text(gid, "units")
    name = grib_text(gid, "name")
    return short_name == "prate" or "/s" in units or "s**-1" in units or "rate" in name


def is_total_precip(gid):
    short_name = grib_text(gid, "shortName")
    name = grib_text(gid, "name")
    param_id = grib_int(gid, "paramId")
    return (
        short_name in ("tp", "apcp", "lsp", "cp")
        or param_id in PRECIP_PARAM_IDS
        or is_grib2_parameter(gid, PRECIP_GRIB2_IDS)
        or "precipitation" in name
        or "rain" in name
    )


def precip_interval_mode(gid):
    step_range = grib_text(gid, "stepRange")
    if "-" not in step_range:
        return None
    start, _, end = step_range.partition("-")
    if start and end and start != "0":
        return "period"
    return None


def is_accumulated_precip(gid):
    step_type = grib_text(gid, "stepType")
    name = grib_text(gid, "name")
    return step_type == "accum" or is_total_precip(gid) or "accum" in name


def normalize_precip(value, gid):
    if is_precip_rate(gid):
        return convert_precip_to_mm(value, gid) * 3600, "rate"
    mode = precip_interval_mode(gid)
    if mode:
        return convert_precip_to_mm(value, gid), mode
    mode = "accumulated" if is_accumulated_precip(gid) else "instant"
    return convert_precip_to_mm(value, gid), mode


def normalize_wave_height(value, gid):
    units = grib_text(gid, "units")
    if units in ("cm", "centimetre", "centimeter"):
        return value / 100
    if units in ("mm", "millimetre", "millimeter"):
        return value / 1000
    return value


def normalize_wave_direction(value):
    return value % 360


def derive_period_precip(rows):
    previous_step = None
    previous_value = None
    precip = {}
    mode = "instant"

    for step in sorted(rows.keys()):
        info = rows[step].get("precip")
        if not info or info.get("value") is None:
            precip[step] = None
            continue

        value = info["value"]
        info_mode = info.get("mode") or "instant"
        if info_mode == "rate":
            precip[step] = round(max(value, 0), 2)
            mode = "rate"
        elif info_mode == "period":
            precip[step] = round(max(value, 0), 2)
            mode = "period"
        elif info_mode == "accumulated":
            if previous_step is None or previous_value is None:
                precip[step] = round(max(value, 0), 2)
            else:
                delta = value - previous_value
                if delta < -0.01:
                    delta = value
                precip[step] = round(max(delta, 0), 2)
            mode = "period"
            previous_step = step
            previous_value = value
        else:
            precip[step] = round(max(value, 0), 2)
            mode = "instant"

    return precip, mode


def resolution_label_from_km(km):
    if km is None or not math.isfinite(km) or km <= 0:
        return None
    if km < 10:
        rounded = round(km, 1)
        return f"{rounded:g} km"
    return f"{round(km):g} km"


def infer_file_resolution_km(name):
    n = name.lower()
    markers = [
        ("1km", 1),
        ("1_km", 1),
        ("1-km", 1),
        ("_1k", 1),
        ("-1k", 1),
        ("7km", 7),
        ("7_km", 7),
        ("7-km", 7),
        ("_7k", 7),
        ("-7k", 7),
        ("0_01", 1.1),
        ("0.01", 1.1),
        ("0_025", 2.8),
        ("0.025", 2.8),
        ("0_05", 5.6),
        ("0.05", 5.6),
        ("0_0625", 7),
        ("0.0625", 7),
    ]
    for marker, km in markers:
        if marker in n:
            return km
    if "lamma" in n:
        return 1
    if "icon" in n:
        return 7
    return None


def infer_file_resolution_label(name):
    return resolution_label_from_km(infer_file_resolution_km(name))


def grib_increment_resolution(gid, lat):
    i_deg = safe_codes_get(gid, "iDirectionIncrementInDegrees")
    j_deg = safe_codes_get(gid, "jDirectionIncrementInDegrees")
    try:
        i_deg = float(i_deg) if i_deg is not None else None
        j_deg = float(j_deg) if j_deg is not None else None
    except (TypeError, ValueError):
        return None
    if not i_deg and not j_deg:
        return None
    if (i_deg and abs(i_deg) > 5) or (j_deg and abs(j_deg) > 5):
        return None

    lat_km = abs(j_deg) * EARTH_KM_PER_DEG if j_deg else None
    lon_km = abs(i_deg) * EARTH_KM_PER_DEG * max(math.cos(math.radians(lat)), 0.01) if i_deg else None
    vals = [v for v in (lat_km, lon_km) if v is not None and math.isfinite(v) and v > 0]
    return max(vals) if vals else None


def add_grid_metadata(meta, gid, nearest, lat, lon, path):
    if "gridLat" not in meta:
        meta["gridLat"] = round(float(nearest.get("lat", lat)), 4)
        meta["gridLon"] = round(float(nearest.get("lon", lon)), 4)
        if "distance" in nearest:
            meta["gridDistanceKm"] = round(float(nearest["distance"]), 2)

    if "fileResolutionLabel" not in meta:
        km = grib_increment_resolution(gid, meta.get("gridLat", lat))
        source = "GRIB increments"
        if km is None:
            km = infer_file_resolution_km(path.name)
            source = "filename/model"
        label = resolution_label_from_km(km)
        if label:
            meta["fileResolutionKm"] = round(km, 1)
            meta["fileResolutionLabel"] = label
            meta["fileResolutionSource"] = source


def nearest_at_point(gid, lat, lon):
    nearest = eccodes.codes_grib_find_nearest(gid, lat, lon, npoints=1)
    return float(nearest[0]["value"]), nearest[0]


def extract(path, lat, lon):
    by_step = {}
    invalid = {}
    meta = {"file": path.name, "lat": lat, "lon": lon}

    with open(path, "rb") as f:
        while True:
            gid = eccodes.codes_grib_new_from_file(f)
            if gid is None:
                break
            try:
                sn = grib_text(gid, "shortName")
                field = classify_message(gid)
                if field is None:
                    continue
                step = int(safe_codes_get(gid, "step", 0))
                val, nearest = nearest_at_point(gid, lat, lon)
                row = by_step.setdefault(
                    step,
                    {
                        "u": None,
                        "v": None,
                        "gust": None,
                        "temp": None,
                        "cape": None,
                        "precip": None,
                        "wave": None,
                        "waveDir": None,
                        "waveRank": 0,
                        "waveDirRank": 0,
                    },
                )
                add_grid_metadata(meta, gid, nearest, lat, lon, path)
                missing_value = safe_codes_get(gid, "missingValue")
                try:
                    is_missing = missing_value is not None and math.isclose(val, float(missing_value), rel_tol=0, abs_tol=1e-9)
                except (TypeError, ValueError):
                    is_missing = False
                if field == "temp":
                    val = convert_temperature(val, gid)
                elif field == "precip":
                    val, precip_mode = normalize_precip(val, gid)
                elif field == "wave":
                    val = normalize_wave_height(val, gid)
                elif field == "waveDir":
                    val = normalize_wave_direction(val)

                if is_missing or (
                    field in ("u", "v", "gust") and not is_valid_grib_value(val, sn)
                ) or (
                    field not in ("u", "v", "gust") and not is_valid_field_value(val, field)
                ):
                    invalid[sn or field] = invalid.get(sn or field, 0) + 1
                    val = None

                if field == "u":
                    row["u"] = val
                elif field == "v":
                    row["v"] = val
                elif field == "gust":
                    row["gust"] = val
                elif field == "precip":
                    row["precip"] = {"value": val, "mode": precip_mode} if val is not None else None
                elif field == "wave":
                    rank = wave_height_rank(gid)
                    if row["wave"] is None or rank >= row["waveRank"]:
                        row["wave"] = val
                        row["waveRank"] = rank
                elif field == "waveDir":
                    rank = wave_direction_rank(gid)
                    if row["waveDir"] is None or rank >= row["waveDirRank"]:
                        row["waveDir"] = val
                        row["waveDirRank"] = rank
                else:
                    row[field] = val
                if "refDate" not in meta:
                    d = safe_codes_get(gid, "dataDate")
                    t = safe_codes_get(gid, "dataTime")
                    meta["refDate"] = f"{d:08d}"
                    meta["refTime"] = f"{t:04d}"
            finally:
                eccodes.codes_release(gid)

    steps = sorted(by_step.keys())
    precip_by_step, precip_mode = derive_period_precip(by_step)
    hours = []
    tws = []
    twd = []
    gust = []
    temp = []
    cape = []
    rain = []
    wave = []
    wave_dir = []
    usable_wind_count = 0

    for step in steps:
        row = by_step[step]
        if all(row.get(key) is None for key in ("u", "v", "gust", "temp", "cape", "precip", "wave", "waveDir")):
            continue
        hours.append(step)
        u, v = row["u"], row["v"]
        if u is None or v is None:
            tws.append(None)
            twd.append(None)
        else:
            speed_ms = math.hypot(u, v)
            if speed_ms > MAX_SPEED_MS:
                invalid["wind"] = invalid.get("wind", 0) + 1
                tws.append(None)
                twd.append(None)
            else:
                # meteorological direction (from which wind blows)
                direction = (270 - math.degrees(math.atan2(v, u))) % 360
                tws.append(round(speed_ms * KT_PER_MS, 1))
                twd.append(round(direction))
                usable_wind_count += 1
        g = row["gust"]
        gust.append(round(g * KT_PER_MS, 1) if g is not None else None)
        temp.append(round(row["temp"], 1) if row["temp"] is not None else None)
        cape.append(round(row["cape"]) if row["cape"] is not None else None)
        rain.append(precip_by_step.get(step))
        wave.append(round(row["wave"], 2) if row["wave"] is not None else None)
        wd = row["waveDir"]
        wave_dir.append(round(wd) if wd is not None else None)

    meta["modelLabel"] = infer_model_label(path.name)
    meta["extracted"] = datetime.now(timezone.utc).isoformat()
    meta["availableFields"] = (
        (["TWS", "TWD"] if usable_wind_count else [])
        + (["gust"] if any(g is not None for g in gust) else [])
        + (["temperature"] if any(t is not None for t in temp) else [])
        + (["CAPE"] if any(c is not None for c in cape) else [])
        + (["rain"] if any(r is not None for r in rain) else [])
        + (["Sig Wave Height"] if any(w is not None for w in wave) else [])
        + (["Wave Direction"] if any(wd is not None for wd in wave_dir) else [])
    )
    meta["windSampleCount"] = usable_wind_count
    if any(r is not None for r in rain):
        meta["rainMode"] = precip_mode
        meta["rainUnits"] = "mm/h" if precip_mode == "rate" else "mm"
    if invalid:
        meta["invalidValueCounts"] = invalid

    result = {
        "meta": meta,
        "hours": hours,
        "tws": tws,
        "twd": twd,
        "gust": gust,
        "gwd": [None] * len(hours),
        "temp": temp,
        "wmo": [None] * len(hours),
        "wave": wave,
    }
    if any(c is not None for c in cape):
        result["cape"] = cape
    if any(r is not None for r in rain):
        result["rain"] = rain
    if any(wd is not None for wd in wave_dir):
        result["waveDir"] = wave_dir
    return result


def extract_latest(lat, lon, write_file=True):
    gribs = candidate_gribs()
    if not gribs:
        raise FileNotFoundError(f"No GRIB file in {GRIB_DIR}")

    skipped = []
    for grib in gribs:
        try:
            data = extract(grib, lat, lon)
            if not data["hours"] or data["meta"].get("windSampleCount", 0) == 0:
                raise ValueError(f"No wind data at {lat}, {lon}")
            if skipped:
                data["meta"]["skippedFiles"] = skipped
            if write_file:
                OUT_FILE.write_text(json.dumps(data, indent=2))
            return data
        except Exception as e:
            skipped.append({"file": grib.name, "error": str(e)})

    errors = "; ".join(f"{s['file']}: {s['error']}" for s in skipped[:3])
    raise ValueError(f"No usable wind GRIB at {lat}, {lon}. {errors}")


def extract_named(name, lat, lon, write_file=True):
    grib = resolve_grib_file(name)
    data = extract(grib, lat, lon)
    if not data["hours"] or data["meta"].get("windSampleCount", 0) == 0:
        raise ValueError(f"No wind data at {lat}, {lon} in {grib.name}")
    if write_file:
        OUT_FILE.write_text(json.dumps(data, indent=2))
    return data


def has_usable_comparison_data(data):
    has_wind = any(
        tws is not None and twd is not None
        for tws, twd in zip(data.get("tws", []), data.get("twd", []))
    )
    has_wave = any(value is not None for value in data.get("wave", [])) or any(
        value is not None for value in data.get("waveDir", [])
    )
    return has_wind or has_wave


def skipped_grib_record(grib, error):
    record = {
        "file": grib.name,
        "modelLabel": infer_model_label(grib.name),
        "error": str(error),
    }
    resolution = infer_file_resolution_label(grib.name)
    if resolution:
        record["fileResolutionLabel"] = resolution
    return record


def grouped_skipped_gribs(skipped):
    grouped = {}
    for item in skipped:
        label = item.get("modelLabel") or infer_model_label(item.get("file", ""))
        error = item.get("error") or "No usable data at selected location"
        key = (label, error)
        if key not in grouped:
            grouped[key] = {**item, "modelLabel": label}
            grouped[key]["files"] = [item["file"]] if item.get("file") else []
            continue
        if item.get("file"):
            grouped[key].setdefault("files", []).append(item["file"])
    return list(grouped.values())


def extract_bundle(lat, lon, files=None):
    gribs = candidate_gribs()
    if files:
        wanted = {name for name in files if name}
        gribs = [grib for grib in gribs if grib.name in wanted]
        if not gribs:
            raise FileNotFoundError(f"No matching GRIB files in {GRIB_DIR}")
    if not gribs:
        raise FileNotFoundError(f"No GRIB file in {GRIB_DIR}")

    models = []
    skipped = []
    for grib in gribs:
        try:
            data = extract(grib, lat, lon)
            if not data["hours"]:
                raise ValueError(f"No usable data at {lat}, {lon}")
            if not has_usable_comparison_data(data):
                raise ValueError(f"No usable TWS/TWD or wave data at {lat}, {lon}")
            models.append(data)
        except Exception as e:
            skipped.append(skipped_grib_record(grib, e))

    if not models:
        errors = "; ".join(f"{s['file']}: {s['error']}" for s in skipped[:3])
        raise ValueError(f"No usable wind GRIB at {lat}, {lon}. {errors}")

    return {
        "ok": True,
        "lat": lat,
        "lon": lon,
        "gribDir": str(GRIB_DIR),
        "modelCount": len(models),
        "models": models,
        "skippedFiles": grouped_skipped_gribs(skipped),
        "extracted": datetime.now(timezone.utc).isoformat(),
    }


def infer_model_label(name):
    n = name.lower()
    if "wam" in n or "mfwam" in n:
        return "WAM (Squid GRIB)"
    if "ecmwf" in n or "ifs" in n:
        return "ECMWF (Squid GRIB)"
    if "gfs" in n:
        return "GFS (Squid GRIB)"
    if "icon" in n:
        return "ICON (Squid GRIB)"
    if "lamma" in n and ("0_01" in n or "1km" in n):
        return "LaMMA 1 km (Squid GRIB)"
    if "lamma" in n:
        return "LaMMA (Squid GRIB)"
    if "arome" in n:
        return "AROME (Squid GRIB)"
    if "arpege" in n:
        return "ARPEGE (Squid GRIB)"
    return "Squid GRIB"


def main():
    lat = float(sys.argv[1]) if len(sys.argv) > 1 else 40.576
    lon = float(sys.argv[2]) if len(sys.argv) > 2 else 14.376
    grib_path = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    if grib_path:
        data = extract(grib_path, lat, lon)
        OUT_FILE.write_text(json.dumps(data, indent=2))
    else:
        data = extract_latest(lat, lon)
    print(f"Wrote {OUT_FILE} from {data['meta']['file']} ({len(data['hours'])} hours)")


if __name__ == "__main__":
    main()
