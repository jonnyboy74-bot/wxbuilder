#!/usr/bin/env python3
"""One-off generator for team_brief.html — run locally when refreshing the crew snapshot."""
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "index.html"
OUT = ROOT / "team_brief.html"
LAT, LON = 40.626, 14.376
COMPARE_DATE = "2026-05-22"
COMPARE_MAX_HOURS = 96
LOCAL_OFFSET_H = 2
GRIB_FILES = [
    "lamma_0_01.2026-05-22T11-31-20Z.grb2",
    "arpege_0_1.2026-05-22T11-31-40Z.grb2",
    "ecmwf_early_0_1.2026-05-22T11-31-41Z.grb2",
    "icon_eu.2026-05-22T11-31-48Z.grb2",
]
VENUE = "Sorrento Race Area"
VESSEL = "Crew brief"
RACE_DAY = "22 May 2026"
EVENT = "WX Builder demo"


def fetch_grib(file_name: str) -> dict:
    url = (
        f"http://localhost:8765/api/squid-grib?lat={LAT}&lon={LON}&file={file_name}"
    )
    with urllib.request.urlopen(url, timeout=120) as res:
        return json.loads(res.read().decode())


def clean_grib_label(label: str) -> str:
    return re.sub(r"\s*\(Squid GRIB\)\s*", "", label or "GRIB", flags=re.I).strip() or "GRIB"


def grib_compare_id(meta: dict, i: int) -> str:
    file_name = meta.get("file") or f"bundle-{i + 1}"
    slug = re.sub(r"[^a-z0-9]+", "-", file_name.lower()).strip("-")
    return f"grib-{slug}" if slug else f"grib-{i}"


def grib_compare_config(payload: dict, i: int) -> dict:
    meta = payload.get("meta") or {}
    label = clean_grib_label(meta.get("modelLabel") or "Squid GRIB")
    fields = meta.get("availableFields") or []
    has_wind = "TWS" in fields or "TWD" in fields
    has_wave = any("wave" in str(f).lower() for f in fields)
    return {
        "id": grib_compare_id(meta, i),
        "label": label,
        "detail": "Wave GRIB" if has_wave and not has_wind else "GRIB",
        "resolution": meta.get("fileResolutionLabel") or "",
    }


def format_run_time(meta: dict) -> str:
    ref_date = meta.get("refDate")
    ref_time = meta.get("refTime")
    if not ref_date or ref_time is None:
        return ""
    d = str(ref_date)
    t = str(ref_time).zfill(4)
    if len(d) != 8:
        return ""
    return f"{d[:4]}-{d[4:6]}-{d[6:8]} {t[:2]}{t[2:]}Z"


def grib_step_to_local_iso(meta: dict, step) -> str | None:
    if meta.get("refDate") is None or step is None:
        return None
    d = str(meta["refDate"])
    if len(d) < 8:
        return None
    yyyy, mm, dd = int(d[:4]), int(d[4:6]), int(d[6:8])
    t = str(meta.get("refTime", "0")).zfill(4)
    rh, rm = int(t[:2]), int(t[2:4]) if len(t) >= 4 else 0
    ref_ms = datetime(yyyy, mm, dd, rh, rm, tzinfo=timezone.utc).timestamp() * 1000
    local_ms = ref_ms + float(step) * 3600000 + LOCAL_OFFSET_H * 3600000
    dt = datetime.fromtimestamp(local_ms / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:00")


def cap_grib_payload(payload: dict) -> dict:
    hours = payload.get("hours") or []
    indexed = sorted(
        [(i, float(h)) for i, h in enumerate(hours) if h is not None and str(h) != ""],
        key=lambda x: x[1],
    )[:COMPARE_MAX_HOURS]
    if not indexed:
        indexed = list(enumerate(hours[:COMPARE_MAX_HOURS]))
    idxs = [i for i, _ in indexed]

    def pick(key):
        arr = payload.get(key)
        if not isinstance(arr, list):
            return [None] * len(idxs)
        return [arr[i] if i < len(arr) else None for i in idxs]

    return {
        "hours": [hours[i] for i in idxs],
        "tws": pick("tws"),
        "twd": pick("twd"),
        "gust": pick("gust"),
        "temp": pick("temp"),
        "wmo": pick("wmo"),
        "cape": pick("cape"),
        "rain": pick("rain"),
        "wave": pick("wave"),
        "waveDir": pick("waveDir"),
    }


def grib_bundle_comparison(payload: dict, cfg: dict, loaded_at: str) -> dict:
    meta = payload.get("meta") or {}
    capped = cap_grib_payload(payload)
    hours = capped["hours"]
    grib_meta = {
        "resolution": cfg.get("resolution", ""),
        "run": format_run_time(meta),
        "loadedAt": loaded_at,
        "file": meta.get("file") or "",
        "rainMode": meta.get("rainMode") or "",
        "refDate": meta.get("refDate"),
        "refTime": meta.get("refTime"),
    }
    return {
        "cfg": cfg,
        "hours": hours,
        "times": [grib_step_to_local_iso(grib_meta, step) for step in hours],
        "tws": capped["tws"],
        "twd": capped["twd"],
        "gust": capped["gust"],
        "temp": capped["temp"],
        "wmo": capped["wmo"],
        "cape": capped["cape"],
        "rain": capped["rain"],
        "wave": capped["wave"],
        "waveDir": capped["waveDir"],
        "metadata": grib_meta,
    }


def build_comparison_snapshot() -> dict:
    loaded_at = datetime.now(timezone.utc).isoformat()
    raw = {}
    configs = []
    for i, file_name in enumerate(GRIB_FILES):
        try:
            payload = fetch_grib(file_name)
            if not payload.get("hours"):
                continue
            cfg = grib_compare_config(payload, i)
            raw[cfg["id"]] = grib_bundle_comparison(payload, cfg, loaded_at)
            configs.append(cfg)
        except Exception as exc:
            print(f"skip {file_name}: {exc}")
    return {
        "raw": raw,
        "configs": configs,
        "skipped": [],
        "fetchSite": {"lat": LAT, "lon": LON, "label": VENUE},
        "date": COMPARE_DATE,
        "issuedAt": loaded_at,
    }


def dir16(deg):
    if deg is None:
        return "—"
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return dirs[int(((float(deg) % 360) + 11.25) / 22.5) % 16]


def slice_period(model: dict, start_h: int, end_h: int) -> dict | None:
    entries = []
    for i, iso in enumerate(model.get("times") or []):
        if not iso or not iso.startswith(COMPARE_DATE):
            continue
        hour = int(iso[11:13])
        if start_h <= hour < end_h:
            entries.append(i)
    if not entries:
        return None

    def vals(key):
        arr = model.get(key) or []
        return [arr[i] for i in entries if i < len(arr)]

    tws = [v for v in vals("tws") if v is not None]
    twd = [v for v in vals("twd") if v is not None]
    gust = [v for v in vals("gust") if v is not None]
    if not tws:
        return None
    twd_mean = sum(twd) / len(twd) if twd else None
    return {
        "tws_min": min(tws),
        "tws_max": max(tws),
        "gust": max(gust) if gust else None,
        "twd_str": dir16(twd_mean),
        "twd_deg": twd_mean,
    }


def build_briefing_html(lamma: dict) -> str:
    periods = [
        ("Early", "07:00", "09:00", 7, 9, "c0"),
        ("Morning", "09:00", "12:00", 9, 12, "c1"),
        ("Midday", "12:00", "15:00", 12, 15, "c2"),
        ("Afternoon", "15:00", "18:00", 15, 18, "c3"),
    ]
    meta = lamma.get("meta") or {}
    model_label = clean_grib_label(meta.get("modelLabel") or "LaMMA 1 km")
    cards = []
    for name, t_from, t_to, h0, h1, cls in periods:
        d = slice_period(lamma, h0, h1)
        if not d:
            wind = "No data in snapshot window."
        else:
            gust = "—" if d["gust"] is None else f"{round(d['gust'])} kt"
            wind = (
                f"TWD <strong>{d['twd_str']}</strong> {round(d['twd_deg'])}° · "
                f"TWS <strong>{round(d['tws_min'])}–{round(d['tws_max'])} kt</strong> · "
                f"gusts {gust}"
            )
        cards.append(
            f"""<article class="pcard {cls}">
      <div class="pt-row"><span class="pt-name">{name}</span><span class="pt-time">{t_from} – {t_to}</span></div>
      <div class="frow"><span class="frow-main">{wind}</span></div>
    </article>"""
        )
    return f"""<header class="f-header">
    <div class="f-venue">{VESSEL}</div>
    <div class="f-date">Thursday 22 May 2026</div>
    <div class="f-meta">{EVENT} · {RACE_DAY} · {VENUE}</div>
    <div class="f-meta">{model_label} · Squid GRIB · static crew snapshot</div>
  </header>
  <div class="day-row-title">Thu <span>22 May 2026 · race periods</span></div>
  {''.join(cards)}
  <footer class="f-footer">Navigation · snapshot for crew — no fetch controls on this page</footer>"""


def extract_style(html: str) -> str:
    m = re.search(r"<style>(.*?)</style>", html, re.S)
    return m.group(1) if m else ""


def extract_script(html: str) -> str:
    m = re.search(
        r'<script src="https://cdn.jsdelivr.net/npm/chart.js.*?</script>\s*<script>(.*?)</script>\s*</body>',
        html,
        re.S,
    )
    return m.group(1) if m else ""


TEAM_CSS = """
body.team-brief-page{
  display:grid;grid-template-columns:1fr;grid-template-rows:auto 1fr;
}
body.team-brief-page .app-body{grid-template-columns:1fr}
body.team-brief-page .preview-area{align-items:stretch}
body.team-brief-page .compare-panel,
body.team-brief-page .forecast-doc{max-width:none}
body.team-brief-page .crew-snapshot-note{
  font-size:var(--xs);color:var(--muted);margin-left:auto;
}
"""

TEAM_BODY = """
<header class="no-print">
  <div class="logo">
    <svg width="32" height="32" viewBox="0 0 32 32" fill="none" aria-hidden="true">
      <circle cx="16" cy="16" r="15" stroke="currentColor" stroke-width="1.5"/>
      <path d="M16 26L16 8L8 22Z" fill="currentColor" opacity=".9"/>
      <path d="M16 26L16 10L23 20Z" fill="currentColor" opacity=".5"/>
      <path d="M6 26L26 26" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
    </svg>
    <div>
      <div class="logo-name">WX Builder</div>
      <div class="logo-sub">Team brief · read-only snapshot</div>
    </div>
  </div>
  <div class="hdr-actions">
    <span class="crew-snapshot-note">No GRIB fetch · display controls only</span>
    <button type="button" class="btn btn-ghost" onclick="window.print()">Print A4</button>
  </div>
</header>

<div class="app-body">
<main>
  <div class="toolbar no-print">
    <h2 id="mainToolbarTitle">Model comparison</h2>
    <div class="tab-bar">
      <button type="button" class="tab-btn" id="briefTabBtn" onclick="switchMainTab('brief')">Briefing</button>
      <button type="button" class="tab-btn active" id="compareTabBtn" onclick="switchMainTab('compare')">Model comparison</button>
    </div>
    <span id="lastUpdated" style="font-size:var(--xs);color:var(--muted)"></span>
  </div>
  <div class="preview-area">
    <div id="forecastDoc" class="forecast-doc" style="display:none"></div>
    <div id="comparePanel" class="compare-panel" style="display:flex">
      <div class="compare-head">
        <div>
          <div class="compare-title">Model Comparison</div>
          <div class="compare-sub" id="compareStatus"></div>
        </div>
        <div class="compare-issued" id="compareIssued"></div>
      </div>
      <div id="compareSkipped" class="compare-skipped"></div>
      <div id="comparePanelEmpty" class="empty">No model comparison loaded.</div>
      <div id="compareRangeWrap" class="compare-data-wrap">
        <div class="compare-range-head">
          <div class="compare-range-title">Timeline summary</div>
          <div class="compare-range-sub" id="compareRangeSub">Max and average values across the selected timeline window.</div>
        </div>
        <div id="compareRangeGrid" class="compare-grid"></div>
      </div>
      <div id="compareLiveWrap" class="compare-data-wrap compare-live-wrap">
        <div class="compare-range-head">
          <div class="compare-range-title">Hourly comparison</div>
          <div class="compare-range-sub" id="compareLiveSub">Values for the selected timeline hour.</div>
        </div>
        <div id="compareHourRow" class="compare-hour-row"></div>
        <div class="compare-table-controls">
          <div class="compare-metric-tabs" id="compareMetricTabs"></div>
          <div class="compare-view-toggle" id="compareViewToggle"></div>
        </div>
        <div id="compareGrid" class="compare-table-outer">
          <div class="compare-table-wrap">
            <table class="compare-table">
              <thead id="compareTableHead"></thead>
              <tbody id="compareTableBody"></tbody>
            </table>
          </div>
          <div id="compareTableScaleLegend" class="compare-table-legend"></div>
        </div>
      </div>
      <div id="compareChartWrap" class="compare-chart-wrap">
        <div class="compare-chart-hd">
          <div class="compare-chart-title" id="compareChartTitle">TWS — all models (kt)</div>
          <div id="compareChartLegend" class="compare-chart-legend"></div>
        </div>
        <div class="compare-main-chart">
          <canvas id="compareMainChart"></canvas>
        </div>
        <div class="compare-chart-canvases-export" aria-hidden="true">
          <div class="compare-chart-title" id="compareChartTitleTws">TWS by Model</div>
          <canvas id="compareChartTws" height="280"></canvas>
          <div class="compare-chart-title" id="compareChartTitleGust">Gusts by Model</div>
          <canvas id="compareChartGust" height="280"></canvas>
          <div class="compare-chart-title" id="compareChartTitleTwd">TWD by Model</div>
          <canvas id="compareChartTwd" height="220"></canvas>
        </div>
      </div>
      <div id="compareAgreement" class="compare-agreement"></div>
    </div>
    <div id="expeditionPanel" class="expedition-panel" hidden style="display:none" aria-hidden="true"></div>
  </div>
</main>
</div>

<div hidden aria-hidden="true" id="crewFormStubs">
  <input id="latInput" type="hidden" value="40.626">
  <input id="lonInput" type="hidden" value="14.376">
  <input id="fDate" type="hidden" value="2026-05-22">
  <input id="compareDate" type="hidden" value="2026-05-22">
  <input id="venueInput" type="hidden" value="Sorrento Race Area">
  <input id="vesselName" type="hidden" value="Crew brief">
  <input id="eventName" type="hidden" value="WX Builder demo">
  <input id="raceDay" type="hidden" value="22 May 2026">
  <input id="fNote" type="hidden" value="">
  <input id="fFooter" type="hidden" value="Navigation · snapshot for crew">
  <select id="comparePeriod"><option value="race" selected>Race day</option></select>
  <select id="briefingModel"><option value="grib" selected>grib</option></select>
  <select id="forecastSource"><option value="grib" selected>grib</option></select>
  <div id="periodList"></div>
  <div id="compareOmModelList"></div>
  <div id="compareOmSection"></div>
  <div id="compareSidebarSection"></div>
  <div id="venueMap"></div>
  <div id="searchResults"></div>
  <span id="statusDot" class="dot"></span><span id="statusMsg"></span>
  <button id="fetchBtn"></button><button id="compareFetchBtn"></button>
</div>
"""

SCRIPT_PREFIX = "const TEAM_BRIEF_MODE = true;\n"

CREW_INIT = """
const TEAM_COMPARE_SNAPSHOT = __SNAPSHOT_JSON__;
const TEAM_BRIEFING_HTML = __BRIEFING_JSON__;

const _origInitVenueMap = typeof initVenueMap === 'function' ? initVenueMap : null;
function initVenueMap(){
  if(!document.getElementById('venueMap') || typeof L === 'undefined') return;
  if(_origInitVenueMap) _origInitVenueMap();
}

async function fetchModelComparison(){ return; }
async function fetchSelectedSource(){ return; }
async function supplementForecastFromOpenMeteo(){ return; }
async function loadSquidGrib(){ return; }
async function refreshCompareGribModelList(){ return; }
function renderCompareOmModelList(){}
function updateCompareSidebarPanels(){}
function invalidateComparisonIfCoordsChanged(){ return false; }
function updateExportCompareOption(){}

function initCrewBriefPage(){
  gribSourceLabel = 'Squid GRIB bundle';
  comparisonDataRaw = TEAM_COMPARE_SNAPSHOT.raw || {};
  comparisonConfigs = TEAM_COMPARE_SNAPSHOT.configs || [];
  comparisonSkippedGribs = TEAM_COMPARE_SNAPSHOT.skipped || [];
  comparisonFetchSite = TEAM_COMPARE_SNAPSHOT.fetchSite || { lat: 40.626, lon: 14.376, label: 'Sorrento Race Area' };
  comparisonTimelineBaseDate = TEAM_COMPARE_SNAPSHOT.date || '2026-05-22';
  comparisonIssuedAt = TEAM_COMPARE_SNAPSHOT.issuedAt || null;
  const compareDate = document.getElementById('compareDate');
  const fDate = document.getElementById('fDate');
  if(compareDate) compareDate.value = comparisonTimelineBaseDate;
  if(fDate) fDate.value = comparisonTimelineBaseDate;
  const periodSel = document.getElementById('comparePeriod');
  if(periodSel) periodSel.value = 'race';
  const briefDoc = document.getElementById('forecastDoc');
  if(briefDoc) briefDoc.innerHTML = TEAM_BRIEFING_HTML;
  applyComparisonPeriodFilter();
  switchMainTab('compare');
  requestAnimationFrame(() => {
    renderComparison();
    updateComparisonStatusLine();
    const updated = document.getElementById('lastUpdated');
    if(updated && comparisonIssuedAt){
      try {
        updated.textContent = 'Snapshot ' + new Date(comparisonIssuedAt).toLocaleString('en-GB', { dateStyle:'medium', timeStyle:'short' });
      } catch {
        updated.textContent = 'Static snapshot';
      }
    }
  });
}

function updateSidebarForMainTab(tab){
  const title = document.getElementById('mainToolbarTitle');
  if(title) title.textContent = tab === 'compare' ? 'Model comparison' : 'Period brief';
}

function switchMainTab(tab){
  const isCompare = tab === 'compare';
  const isExpedition = tab === 'expedition';
  const forecastDoc = document.getElementById('forecastDoc');
  const comparePanel = document.getElementById('comparePanel');
  const expeditionPanel = document.getElementById('expeditionPanel');
  if(forecastDoc) forecastDoc.style.display = (!isCompare && !isExpedition) ? 'flex' : 'none';
  if(comparePanel) comparePanel.style.display = isCompare ? 'flex' : 'none';
  if(expeditionPanel) expeditionPanel.style.display = isExpedition ? 'flex' : 'none';
  const briefBtn = document.getElementById('briefTabBtn');
  const compareBtn = document.getElementById('compareTabBtn');
  const expeditionBtn = document.getElementById('expeditionTabBtn');
  if(briefBtn) briefBtn.classList.toggle('active', tab === 'brief');
  if(compareBtn) compareBtn.classList.toggle('active', isCompare);
  if(expeditionBtn) expeditionBtn.classList.toggle('active', isExpedition);
  updateSidebarForMainTab(tab);
  if(isCompare){
    syncComparisonDateFromRace();
    initComparePeriodSelect();
    updateCompareSourceChrome(getSharedForecastSource());
    if(!Object.keys(comparisonData).length) renderComparison();
    else updateComparisonStatusLine();
  }
}
"""

DATE_BOOTSTRAP = """document.getElementById('fDate').value = new Date().toISOString().split('T')[0];
syncComparisonDateFromRace();"""

DATE_BOOTSTRAP_CREW = """/* crew snapshot keeps embedded race date */"""

OLD_INIT = """buildPeriodList();
populateBriefingModelSelect();
ensureStorageVersion();
refreshVenuePresetSelect('');
refreshVesselPresetSelect('');
refreshEventPresetSelect('');
updateSaveVenueBtn();
updateSaveVesselBtn();
updateSaveEventBtn();
initSidebar();
initVenueMap();
const storedSource = getStoredForecastSource();
setSharedForecastSource(storedSource || 'grib', { skipBriefUi: false, skipCompareUi: false, clearData: false });
const initialEventId = document.getElementById('eventPreset')?.value;
if(initialEventId){
  loadEventById(initialEventId);
} else {
  const lastVenue = getLastVenueValue();
  if(lastVenue && [...(document.getElementById('venuePreset')?.options || [])].some(o => o.value === lastVenue)){
    loadPreset(lastVenue);
  }
  const lastVessel = getLastVesselId();
  if(lastVessel && [...(document.getElementById('vesselPreset')?.options || [])].some(o => o.value === lastVessel)){
    document.getElementById('vesselPreset').value = lastVessel;
    applyVesselPreset(lastVessel);
  } else {
    renderBrief();
  }
}
refreshSquidGribHint();
initComparePeriodSelect();
renderCompareOmModelList();
refreshCompareGribModelList();
updateCompareSidebarPanels();
try {
  const savedTab = sessionStorage.getItem(MAIN_TAB_KEY);
  if(savedTab && ['brief', 'compare', 'expedition'].includes(savedTab)) switchMainTab(savedTab);
} catch {}"""


def main():
    index_html = INDEX.read_text(encoding="utf-8")
    style = extract_style(index_html)
    script = extract_script(index_html)
    script = SCRIPT_PREFIX + script
    script = script.replace(DATE_BOOTSTRAP, DATE_BOOTSTRAP_CREW)
    script = script.replace(OLD_INIT.strip(), CREW_INIT.strip())
    script = script.replace(
        "const el = document.getElementById(id);\n  el.addEventListener('change', () => {",
        "const el = document.getElementById(id);\n  if(!el) return;\n  el.addEventListener('change', () => {",
    )
    script = script.replace(
        "const TEAM_COMPARE_SNAPSHOT = __SNAPSHOT_JSON__;",
        "const TEAM_COMPARE_SNAPSHOT = " + json.dumps(build_comparison_snapshot(), separators=(",", ":")) + ";",
    )
    lamma_payload = fetch_grib(GRIB_FILES[0])
    briefing_html = build_briefing_html(
        grib_bundle_comparison(lamma_payload, grib_compare_config(lamma_payload, 0), datetime.now(timezone.utc).isoformat())
    )
    script = script.replace(
        "const TEAM_BRIEFING_HTML = __BRIEFING_JSON__;",
        "const TEAM_BRIEFING_HTML = " + json.dumps(briefing_html) + ";",
    )

    out = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WX Builder — Team brief</title>
<link href="https://api.fontshare.com/v2/css?f[]=satoshi@400,500,600,700&display=swap" rel="stylesheet">
<style>
{style}
{TEAM_CSS}
</style>
</head>
<body class="team-brief-page">
{TEAM_BODY}
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>
{script}
initCrewBriefPage();
</script>
</body>
</html>
"""
    OUT.write_text(out, encoding="utf-8")
    print(f"Wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
