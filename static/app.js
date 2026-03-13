const receiverColor = "#56e1d8";
const satelliteColor = "#ffb85c";
const nadirColor = "#ffdca5";

const globeContainer = document.getElementById("globeViz");
const statusLine = document.getElementById("statusLine");
const metricMode = document.getElementById("metricMode");
const metricUsed = document.getElementById("metricUsed");
const metricVisible = document.getElementById("metricVisible");
const metricHdop = document.getElementById("metricHdop");
const fixPill = document.getElementById("fixPill");
const tlePill = document.getElementById("tlePill");
const gpsClockEl = document.getElementById("gpsClock");
const gpsTzEl = document.getElementById("gpsTz");
const satelliteTooltip = document.getElementById("satelliteTooltip");
const satelliteTooltipClose = document.getElementById("satelliteTooltipClose");
const satelliteTooltipImage = document.getElementById("satelliteTooltipImage");
const satelliteTooltipKicker = document.getElementById("satelliteTooltipKicker");
const satelliteTooltipTitle = document.getElementById("satelliteTooltipTitle");
const satelliteTooltipLaunch = document.getElementById("satelliteTooltipLaunch");
const satelliteTooltipLocation = document.getElementById("satelliteTooltipLocation");
const satelliteTooltipPeriod = document.getElementById("satelliteTooltipPeriod");
const satelliteTooltipSpeed = document.getElementById("satelliteTooltipSpeed");

const receiverFields = {
  lat: document.getElementById("receiverLat"),
  lon: document.getElementById("receiverLon"),
  alt: document.getElementById("receiverAlt"),
  acc: document.getElementById("receiverAcc"),
  speed: document.getElementById("receiverSpeed"),
  age: document.getElementById("receiverAge"),
  time: document.getElementById("receiverTime"),
  gpsdAge: document.getElementById("gpsdAge"),
  pdop: document.getElementById("pdopValue"),
  vdop: document.getElementById("vdopValue"),
  tleAge: document.getElementById("tleAge"),
};

let firstFocusDone = false;
let globe;
let globeError = null;

// Clock state
let tzOffsetMinutes = 0;
let tzName = "";
let clockBase = null; // { gpsUtcMs, wallMs }
let selectedSatellitePrn = null;
let lastVisibleSatellites = [];

function satelliteRenderAltitude(rawAltitude) {
  if (!Number.isFinite(rawAltitude)) return 0.14;
  return Math.max(0.09, Math.min(0.24, rawAltitude * 0.32));
}

function tickClock() {
  if (!clockBase) {
    gpsClockEl.textContent = "--:--:--";
    return;
  }
  const elapsed = Date.now() - clockBase.wallMs;
  const localMs = clockBase.gpsUtcMs + elapsed + tzOffsetMinutes * 60000;
  const d = new Date(localMs);
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  const ss = String(d.getUTCSeconds()).padStart(2, "0");
  gpsClockEl.textContent = `${hh}:${mm}:${ss}`;
}

setInterval(tickClock, 1000);
tickClock();

function syncClock(state) {
  tzOffsetMinutes = Number.isFinite(state?.tz_offset_minutes) ? state.tz_offset_minutes : 0;
  tzName = state?.tz_name || "UTC";
  gpsTzEl.textContent = tzName;

  const baseIso = state?.receiver?.timestamp || state?.generated_at;
  if (!baseIso) {
    clockBase = null;
    tickClock();
    return;
  }

  const gpsUtcMs = new Date(baseIso).getTime();
  if (!Number.isFinite(gpsUtcMs)) {
    clockBase = null;
    tickClock();
    return;
  }

  clockBase = { gpsUtcMs, wallMs: Date.now() };
  tickClock();
}

function fmtLocalDateTime(utcIso) {
  if (!utcIso) return "--";
  const ms = new Date(utcIso).getTime();
  if (!Number.isFinite(ms)) return "--";
  const localMs = ms + tzOffsetMinutes * 60000;
  const d = new Date(localMs);
  const dd = String(d.getUTCDate()).padStart(2, "0");
  const mo = String(d.getUTCMonth() + 1).padStart(2, "0");
  const yyyy = String(d.getUTCFullYear());
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  const ss = String(d.getUTCSeconds()).padStart(2, "0");
  return `${dd}/${mo}/${yyyy} ${hh}:${mm}:${ss}`;
}

function signalClass(dbhz) {
  if (!Number.isFinite(dbhz)) return "poor";
  if (dbhz >= 35) return "good";
  if (dbhz >= 25) return "ok";
  return "poor";
}

function signalPct(dbhz) {
  if (!Number.isFinite(dbhz)) return 0;
  return Math.min(100, Math.max(0, ((dbhz - 10) / 40) * 100));
}

function buildSatelliteEmojiMarker(sat) {
  const marker = document.createElement("button");
  marker.type = "button";
  marker.className = "satellite-emoji-marker";
  if (!sat.used) {
    marker.classList.add("satellite-emoji-marker--visible");
  }
  if (sat.prn === selectedSatellitePrn) {
    marker.classList.add("satellite-emoji-marker--selected");
  }
  marker.title = `PRN ${sat.prn} | ${fmtNumber(sat.signal_dbhz, 0, "--")} dBHz`;
  marker.addEventListener("click", (event) => {
    event.stopPropagation();
    selectSatellite(sat.prn);
  });

  const emoji = document.createElement("span");
  emoji.className = "satellite-emoji-marker__icon";
  emoji.textContent = "🛰️";

  const label = document.createElement("span");
  label.className = "satellite-emoji-marker__label";
  label.textContent = `PRN ${sat.prn}`;

  marker.appendChild(emoji);
  marker.appendChild(label);
  return marker;
}

function fmtNumber(value, digits = 2, fallback = "--") {
  return Number.isFinite(value) ? value.toFixed(digits) : fallback;
}

function fmtSigned(value, digits = 5) {
  return Number.isFinite(value) ? value.toFixed(digits) : "--";
}

function fmtMeters(value) {
  return Number.isFinite(value) ? `${value.toFixed(1)} m` : "--";
}

function fmtKm(value) {
  return Number.isFinite(value) ? `${value.toFixed(0)} km` : "--";
}

function fmtSpeed(value) {
  if (!Number.isFinite(value)) return "--";
  return `${value.toFixed(2)} m/s`;
}

function fmtAge(value) {
  if (!Number.isFinite(value)) return "--";
  if (value < 1) return "agora";
  if (value < 60) return `${value.toFixed(0)} s`;
  const minutes = Math.floor(value / 60);
  const seconds = Math.floor(value % 60);
  return `${minutes}m ${seconds}s`;
}

function fmtKmh(value) {
  return Number.isFinite(value) ? `${value.toFixed(0)} km/h` : "--";
}

function fmtPeriod(minutes) {
  if (!Number.isFinite(minutes)) return "--";
  const hours = Math.floor(minutes / 60);
  const rest = Math.round(minutes % 60);
  return hours > 0 ? `${hours}h ${rest}min` : `${rest}min`;
}

function fmtCoordinateLabel(value, positive, negative) {
  if (!Number.isFinite(value)) return "--";
  return `${Math.abs(value).toFixed(2)}° ${value >= 0 ? positive : negative}`;
}

function fmtSatelliteLocation(subpoint) {
  if (!subpoint) return "--";
  return `${fmtCoordinateLabel(subpoint.lat, "N", "S")}, ${fmtCoordinateLabel(subpoint.lon, "L", "O")}`;
}

function syncSelectedSatellite() {
  if (!selectedSatellitePrn) {
    satelliteTooltip.hidden = true;
    return;
  }
  const selectedSatellite = lastVisibleSatellites.find((sat) => sat.prn === selectedSatellitePrn);
  if (!selectedSatellite) {
    selectedSatellitePrn = null;
    satelliteTooltip.hidden = true;
    return;
  }
  const launchBits = [];
  if (selectedSatellite.launch?.date_localized) {
    launchBits.push(selectedSatellite.launch.date_localized);
  }
  if (selectedSatellite.launch?.time_utc) {
    launchBits.push(`${selectedSatellite.launch.time_utc} UTC`);
  }
  if (selectedSatellite.launch?.vehicle) {
    launchBits.push(selectedSatellite.launch.vehicle);
  }
  if (selectedSatellite.launch?.site) {
    launchBits.push(selectedSatellite.launch.site);
  }

  satelliteTooltipImage.src = selectedSatellite.image_url || "/assets/gps-block-generic.svg";
  satelliteTooltipImage.alt = selectedSatellite.name || `Satélite GPS PRN ${selectedSatellite.prn}`;
  satelliteTooltipKicker.textContent = selectedSatellite.intl_designator || `PRN ${selectedSatellite.prn}`;
  satelliteTooltipTitle.textContent = selectedSatellite.name || `Satélite GPS PRN ${selectedSatellite.prn}`;
  satelliteTooltipLaunch.textContent = launchBits.length ? launchBits.join(" • ") : "--";
  satelliteTooltipLocation.textContent = fmtSatelliteLocation(selectedSatellite.subpoint);
  satelliteTooltipPeriod.textContent = fmtPeriod(selectedSatellite.orbit?.period_minutes);
  satelliteTooltipSpeed.textContent = fmtKmh(selectedSatellite.orbit?.speed_kmh);
  satelliteTooltip.hidden = false;
}

function selectSatellite(prn) {
  selectedSatellitePrn = prn;
  syncSelectedSatellite();
}

function closeSatelliteTooltip() {
  selectedSatellitePrn = null;
  satelliteTooltip.hidden = true;
}

function setText(el, value) {
  el.textContent = value ?? "--";
}

function renderState(state) {
  syncClock(state);

  const receiver = state.receiver;
  const satellites = state.satellites_used || [];
  const visibleSatellites = state.satellites_visible || satellites;
  const sky = state.sky || {};
  const tle = state.tle || {};
  const gpsd = state.gpsd || {};

  metricMode.textContent = receiver ? `${receiver.mode}D` : "--";
  metricUsed.textContent = `${sky.gps_used ?? 0}`;
  metricVisible.textContent = `${sky.gps_visible ?? 0}`;
  metricHdop.textContent = fmtNumber(sky.hdop, 2);

  fixPill.textContent = receiver && receiver.mode >= 3 ? "POSI\u00c7\u00c3O 3D" : receiver ? "POSI\u00c7\u00c3O 2D" : "SEM POSI\u00c7\u00c3O";
  fixPill.style.color = receiver && receiver.mode >= 3 ? "#95f1a5" : "#ff7e7e";

  tlePill.textContent = tle.last_error ? "TLE cache" : "TLE online";
  tlePill.style.color = tle.last_error ? "#ffd79a" : "#95f1a5";

  if (receiver) {
    setText(receiverFields.lat, fmtSigned(receiver.lat, 6));
    setText(receiverFields.lon, fmtSigned(receiver.lon, 6));
    setText(receiverFields.alt, fmtMeters(receiver.altitude_m));
    setText(receiverFields.acc, fmtMeters(receiver.horizontal_error_m));
    setText(receiverFields.speed, fmtSpeed(receiver.speed_ms));
    setText(receiverFields.age, fmtAge(receiver.age_seconds));
    setText(receiverFields.time, fmtLocalDateTime(receiver.timestamp));
    setText(receiverFields.gpsdAge, fmtAge(receiver.last_message_age_seconds));
    setText(receiverFields.pdop, fmtNumber(sky.pdop, 2));
    setText(receiverFields.vdop, fmtNumber(sky.vdop, 2));
    setText(receiverFields.tleAge, tle.last_fetch_at ? fmtAge((Date.now() / 1000) - tle.last_fetch_at) : "--");
  } else {
    Object.values(receiverFields).forEach((field) => setText(field, "--"));
  }

  lastVisibleSatellites = visibleSatellites;
  syncSelectedSatellite();

  if (!receiver) {
    const baseStatus = gpsd.error
      ? `GPSD conectado, mas ainda sem posi\u00e7\u00e3o utiliz\u00e1vel: ${gpsd.error}`
      : "GPSD ativo, aguardando latitude e longitude do receptor.";
    statusLine.textContent = globeError ? `${baseStatus} | ${globeError}` : baseStatus;
    if (globe) {
      globe.pointsData([]);
      globe.arcsData([]);
      globe.ringsData([]);
      globe.htmlElementsData([]);
    }
    closeSatelliteTooltip();
    return;
  }

  const liveStatus = `${sky.gps_used ?? 0} sat\u00e9lites GPS participam do c\u00e1lculo da posi\u00e7\u00e3o agora.`;
  statusLine.textContent = globeError ? `${liveStatus} | ${globeError}` : liveStatus;

  if (!globe) {
    return;
  }

  const points = [
    {
      lat: receiver.lat,
      lng: receiver.lon,
      altitude: 0.01,
      radius: 0.42,
      color: receiverColor,
    },
    ...satellites.flatMap((sat) => {
      if (!sat.subpoint) return [];
      return [
        {
          lat: sat.subpoint.lat,
          lng: sat.subpoint.lon,
          altitude: satelliteRenderAltitude(sat.subpoint.display_altitude),
          radius: 0.32,
          color: satelliteColor,
        },
        {
          lat: sat.subpoint.lat,
          lng: sat.subpoint.lon,
          altitude: 0.008,
          radius: 0.14,
          color: nadirColor,
        },
      ];
    }),
  ];

  const arcs = satellites
    .filter((sat) => sat.subpoint)
    .map((sat) => ({
      startLat: receiver.lat,
      startLng: receiver.lon,
      endLat: sat.subpoint.lat,
      endLng: sat.subpoint.lon,
      color: ["rgba(86,225,216,0.95)", "rgba(255,184,92,0.35)"],
    }));

  const satelliteEmojiMarkers = visibleSatellites
    .filter((sat) => sat.subpoint)
    .map((sat) => ({
      lat: sat.subpoint.lat,
      lng: sat.subpoint.lon,
      altitude:
        satelliteRenderAltitude(sat.subpoint.display_altitude) + (sat.used ? 0.015 : 0.008),
      sat,
    }));

  globe.pointsData(points);
  globe.arcsData(arcs);
  globe.ringsData([{ lat: receiver.lat, lng: receiver.lon }]);
  globe.htmlElementsData(satelliteEmojiMarkers);

  if (!firstFocusDone) {
    globe.pointOfView({ lat: receiver.lat, lng: receiver.lon, altitude: 1.12 }, 1600);
    firstFocusDone = true;
  }
}

async function refresh() {
  try {
    const response = await fetch("/api/state", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const state = await response.json();
    renderState(state);
  } catch (error) {
    statusLine.textContent = `Falha ao atualizar o painel: ${error.message}`;
  } finally {
    window.setTimeout(refresh, 2000);
  }
}

function initGlobe() {
  const resizeGlobe = () => {
    if (!globe) return;
    globe.width(globeContainer.clientWidth);
    globe.height(globeContainer.clientHeight);
  };

  const applyStep = (label, fn) => {
    try {
      fn();
    } catch (error) {
      throw new Error(`${label}: ${error.message}`);
    }
  };

  applyStep("constructor", () => {
    if (typeof window.Globe !== "function") {
      throw new Error("biblioteca Globe.gl n\u00e3o carregou");
    }
    globe = new window.Globe(globeContainer, {
      animateIn: false,
      waitForGlobeReady: false,
    });
  });
  resizeGlobe();
  applyStep("globeImageUrl", () =>
    globe.globeImageUrl("https://cdn.jsdelivr.net/npm/three-globe/example/img/earth-blue-marble.jpg")
  );
  applyStep("bumpImageUrl", () =>
    globe.bumpImageUrl("https://cdn.jsdelivr.net/npm/three-globe/example/img/earth-topology.png")
  );
  applyStep("backgroundImageUrl", () =>
    globe.backgroundImageUrl("https://cdn.jsdelivr.net/npm/three-globe/example/img/night-sky.png")
  );
  applyStep("showAtmosphere", () => globe.showAtmosphere(true));
  applyStep("atmosphereColor", () => globe.atmosphereColor("#56e1d8"));
  applyStep("atmosphereAltitude", () => globe.atmosphereAltitude(0.18));
  applyStep("enablePointerInteraction", () => globe.enablePointerInteraction(true));
  applyStep("showGraticules", () => globe.showGraticules(true));
  applyStep("globeOffset", () => globe.globeOffset([0, 32]));
  applyStep("htmlTransitionDuration", () => globe.htmlTransitionDuration(250));
  applyStep("pointLat", () => globe.pointLat("lat"));
  applyStep("pointLng", () => globe.pointLng("lng"));
  applyStep("pointAltitude", () => globe.pointAltitude("altitude"));
  applyStep("pointRadius", () => globe.pointRadius("radius"));
  applyStep("pointColor", () => globe.pointColor("color"));
  applyStep("arcStartLat", () => globe.arcStartLat("startLat"));
  applyStep("arcStartLng", () => globe.arcStartLng("startLng"));
  applyStep("arcEndLat", () => globe.arcEndLat("endLat"));
  applyStep("arcEndLng", () => globe.arcEndLng("endLng"));
  applyStep("arcColor", () => globe.arcColor("color"));
  applyStep("arcStroke", () => globe.arcStroke(0.85));
  applyStep("arcDashLength", () => globe.arcDashLength(0.42));
  applyStep("arcDashGap", () => globe.arcDashGap(0.18));
  applyStep("arcDashAnimateTime", () => globe.arcDashAnimateTime(3200));
  applyStep("ringLat", () => globe.ringLat("lat"));
  applyStep("ringLng", () => globe.ringLng("lng"));
  applyStep("ringColor", () => globe.ringColor(() => receiverColor));
  applyStep("ringMaxRadius", () => globe.ringMaxRadius(4.2));
  applyStep("ringPropagationSpeed", () => globe.ringPropagationSpeed(2.6));
  applyStep("ringRepeatPeriod", () => globe.ringRepeatPeriod(1300));
  applyStep("htmlLat", () => globe.htmlLat("lat"));
  applyStep("htmlLng", () => globe.htmlLng("lng"));
  applyStep("htmlAltitude", () => globe.htmlAltitude("altitude"));
  applyStep("htmlElement", () => globe.htmlElement((marker) => buildSatelliteEmojiMarker(marker.sat)));
  applyStep("rendererConfig", () => {
    const controls = globe.controls();
    controls.enablePan = false;
    controls.minDistance = 180;
    controls.maxDistance = 420;
    controls.rotateSpeed = 0.9;
    controls.zoomSpeed = 0.85;
  });
  applyStep("pointOfView", () => globe.pointOfView({ lat: 0, lng: 0, altitude: 1.15 }, 0));
  window.addEventListener("resize", resizeGlobe);
}

try {
  initGlobe();
} catch (error) {
  console.error(error);
  globeError = `globo indispon\u00edvel neste navegador: ${error.message}`;
}

satelliteTooltipClose.addEventListener("click", closeSatelliteTooltip);
document.addEventListener("click", (event) => {
  if (satelliteTooltip.hidden) return;
  if (satelliteTooltip.contains(event.target)) return;
  if (event.target.closest(".satellite-emoji-marker")) return;
  closeSatelliteTooltip();
});

refresh();
