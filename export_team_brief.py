#!/usr/bin/env python3
"""Generate team_brief.html — static crew page from WXBuilder export payload."""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INDEX_HTML = ROOT / "index.html"
TEMPLATE_HTML = ROOT / "team_brief_template.html"
OUTPUT_HTML = ROOT / "team_brief.html"

TEAM_PAGE_CSS = """
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
"""

SCRIPT_PREFIX = "const TEAM_BRIEF_MODE = true;\n"

CREW_BOOTSTRAP = """
const TEAM_EXPORT_META = __EXPORT_META_JSON__;
const TEAM_COMPARE_SNAPSHOT = __COMPARE_SNAPSHOT_JSON__;
const TEAM_BRIEFING_HTML = __BRIEFING_HTML_JSON__;

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
  const snap = TEAM_COMPARE_SNAPSHOT || {};
  const meta = TEAM_EXPORT_META || {};
  gribSourceLabel = meta.gribSourceLabel || 'Squid GRIB bundle';
  comparisonDataRaw = snap.raw || {};
  comparisonConfigs = snap.configs || [];
  comparisonSkippedGribs = snap.skipped || [];
  comparisonFetchSite = snap.fetchSite || null;
  comparisonTimelineBaseDate = snap.timelineBaseDate || snap.date || null;
  comparisonIssuedAt = snap.issuedAt || meta.exportedAt || null;
  const compareDate = document.getElementById('compareDate');
  const fDate = document.getElementById('fDate');
  const raceDate = snap.date || meta.raceDate || '';
  if(compareDate && raceDate) compareDate.value = raceDate;
  if(fDate && raceDate) fDate.value = raceDate;
  const periodSel = document.getElementById('comparePeriod');
  const defaultTab = meta.briefingAvailable ? 'compare' : 'compare';
  switchMainTab(defaultTab);
  if(periodSel && snap.periodId) periodSel.value = snap.periodId;
  applyComparisonPeriodFilter();
  const briefDoc = document.getElementById('forecastDoc');
  if(briefDoc && typeof TEAM_BRIEFING_HTML === 'string') briefDoc.innerHTML = TEAM_BRIEFING_HTML;
  requestAnimationFrame(() => {
    renderComparison();
    updateComparisonStatusLine();
    const updated = document.getElementById('lastUpdated');
    if(updated){
      const stamp = comparisonIssuedAt || meta.exportedAt;
      if(stamp){
        try {
          updated.textContent = 'Snapshot ' + new Date(stamp).toLocaleString('en-GB', { dateStyle:'medium', timeStyle:'short' });
        } catch {
          updated.textContent = 'Static snapshot';
        }
      } else {
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

NO_BRIEFING_HTML = '<div class="empty">No briefing content for this export.</div>'


class TeamBriefExportError(Exception):
    """Invalid or incomplete export payload."""


def extract_index_styles(index_html: str) -> str:
    match = re.search(r"<style>(.*?)</style>", index_html, re.S)
    return match.group(1) if match else ""


def extract_index_script(index_html: str) -> str:
    match = re.search(
        r'<script src="https://cdn.jsdelivr.net/npm/chart.js.*?</script>\s*<script>(.*?)</script>\s*</body>',
        index_html,
        re.S,
    )
    return match.group(1) if match else ""


def patch_index_script_for_crew(script: str) -> str:
    script = SCRIPT_PREFIX + script
    script = script.replace(DATE_BOOTSTRAP, DATE_BOOTSTRAP_CREW)
    script = script.replace(OLD_INIT.strip(), "")
    script = script.replace(
        "const el = document.getElementById(id);\n  el.addEventListener('change', () => {",
        "const el = document.getElementById(id);\n  if(!el) return;\n  el.addEventListener('change', () => {",
    )
    return script + "\n" + CREW_BOOTSTRAP.strip() + "\n"


def _attr_value(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def build_crew_form_stubs(form: dict) -> str:
    form = form or {}
    lat = form.get("lat", 40.626)
    lon = form.get("lon", 14.376)
    return f"""
<div hidden aria-hidden="true" id="crewFormStubs">
  <input id="latInput" type="hidden" value="{_attr_value(lat)}">
  <input id="lonInput" type="hidden" value="{_attr_value(lon)}">
  <input id="fDate" type="hidden" value="{_attr_value(form.get('fDate', ''))}">
  <input id="compareDate" type="hidden" value="{_attr_value(form.get('compareDate', form.get('fDate', '')))}">
  <input id="venueInput" type="hidden" value="{_attr_value(form.get('venue', ''))}">
  <input id="vesselName" type="hidden" value="{_attr_value(form.get('vessel', ''))}">
  <input id="eventName" type="hidden" value="{_attr_value(form.get('event', ''))}">
  <input id="raceDay" type="hidden" value="{_attr_value(form.get('raceDay', ''))}">
  <input id="fNote" type="hidden" value="{_attr_value(form.get('fNote', ''))}">
  <input id="fFooter" type="hidden" value="{_attr_value(form.get('fFooter', ''))}">
  <select id="comparePeriod"><option value="race" selected>Race day</option><option value="fullday">Full day</option><option value="h12">12 hours</option><option value="h24">24 hours</option><option value="allhours">Full range (all hours)</option></select>
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


def validate_export_payload(payload: dict) -> None:
    if not isinstance(payload, dict):
        raise TeamBriefExportError("Export payload must be a JSON object.")
    compare = payload.get("compare") or {}
    raw = compare.get("raw") or {}
    loaded = [
        model
        for model in raw.values()
        if isinstance(model, dict) and not model.get("error")
    ]
    if not loaded:
        raise TeamBriefExportError(
            "Model comparison has no loaded data. Fetch comparison in WXBuilder before exporting."
        )


def normalize_export_payload(payload: dict) -> dict:
    """Shape client POST body into template placeholders."""
    validate_export_payload(payload)
    compare = payload.get("compare") or {}
    form = payload.get("form") or {}
    briefing_available = bool(payload.get("briefingAvailable"))
    briefing_html = payload.get("briefingHtml") or ""
    if not briefing_available or not str(briefing_html).strip():
        briefing_html = NO_BRIEFING_HTML
        briefing_available = False

    race_date = compare.get("date") or form.get("compareDate") or form.get("fDate") or ""
    compare_snapshot = {
        "raw": compare.get("raw") or {},
        "configs": compare.get("configs") or [],
        "skipped": compare.get("skipped") or [],
        "fetchSite": compare.get("fetchSite"),
        "date": race_date,
        "periodId": compare.get("periodId") or "race",
        "issuedAt": compare.get("issuedAt"),
        "timelineBaseDate": compare.get("timelineBaseDate") or race_date,
    }
    export_meta = {
        "exportedAt": payload.get("exportedAt")
        or datetime.now(timezone.utc).isoformat(),
        "briefingAvailable": briefing_available,
        "raceDate": race_date,
        "gribSourceLabel": payload.get("gribSourceLabel") or "",
    }
    return {
        "briefing_html": briefing_html,
        "compare_snapshot": compare_snapshot,
        "export_meta": export_meta,
        "form": form,
    }


def render_team_brief_html(payload: dict, *, index_path: Path = INDEX_HTML) -> str:
    """Render full team_brief.html from WXBuilder export payload."""
    normalized = normalize_export_payload(payload)
    index_html = index_path.read_text(encoding="utf-8")
    styles = extract_index_styles(index_html)
    script = patch_index_script_for_crew(extract_index_script(index_html))
    script = script.replace(
        "const TEAM_EXPORT_META = __EXPORT_META_JSON__;",
        "const TEAM_EXPORT_META = "
        + json.dumps(normalized["export_meta"], separators=(",", ":"))
        + ";",
    )
    script = script.replace(
        "const TEAM_COMPARE_SNAPSHOT = __COMPARE_SNAPSHOT_JSON__;",
        "const TEAM_COMPARE_SNAPSHOT = "
        + json.dumps(normalized["compare_snapshot"], separators=(",", ":"))
        + ";",
    )
    script = script.replace(
        "const TEAM_BRIEFING_HTML = __BRIEFING_HTML_JSON__;",
        "const TEAM_BRIEFING_HTML = "
        + json.dumps(normalized["briefing_html"])
        + ";",
    )

    template = TEMPLATE_HTML.read_text(encoding="utf-8")
    return (
        template.replace("__INDEX_STYLES__", styles)
        .replace("__TEAM_PAGE_CSS__", TEAM_PAGE_CSS.strip())
        .replace("__TEAM_BODY__", TEAM_BODY.strip())
        .replace("__CREW_FORM_STUBS__", build_crew_form_stubs(normalized["form"]).strip())
        .replace("__APP_SCRIPT__", script)
    )


def export_team_brief(
    payload: dict,
    *,
    output_path: Path = OUTPUT_HTML,
    index_path: Path = INDEX_HTML,
) -> Path:
    """Write team_brief.html from export payload. Overwrites previous file."""
    html_out = render_team_brief_html(payload, index_path=index_path)
    output_path.write_text(html_out, encoding="utf-8")
    return output_path.resolve()


def export_team_brief_from_request(body: bytes) -> dict:
    """Parse POST body and write team_brief.html. Returns API response dict."""
    try:
        payload = json.loads(body.decode("utf-8") if body else "{}")
    except json.JSONDecodeError as exc:
        raise TeamBriefExportError(f"Invalid JSON: {exc}") from exc
    path = export_team_brief(payload)
    return {
        "ok": True,
        "status": "ok",
        "path": path.name,
        "absolutePath": str(path),
        "bytes": path.stat().st_size,
    }
