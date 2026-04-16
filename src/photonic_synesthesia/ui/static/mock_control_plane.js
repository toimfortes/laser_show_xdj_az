const appState = {
  catalog: null,
  fixtures: [],
  selectedFixtureId: null,
  selectedUniverse: 1,
  sceneId: "intro_ambient",
  masterIntensity: 0.82,
  masterSpeed: 1.0,
  blackout: false,
  runtimeSnapshot: null,
  universeSnapshot: null,
  playback: null,
  wsStatus: "connecting",
  dragFixtureId: null,
};

const elements = {};
const fixturePatchTimers = new Map();
let masterPatchTimer = null;
let universeRefreshTimer = null;
let playbackRefreshTimer = null;
let playbackPollActive = false;
let fixtureActivityRenderedAt = 0;
let fixtureActivitySignature = "";

const PLAYBACK_POLL_MS = 250;
const PLAYBACK_STALE_MS = 900;

function qs(id) {
  return document.getElementById(id);
}

function safeText(value, fallback = "n/a") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function round(value, digits = 2) {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

function titleCaseWords(value) {
  return safeText(value, "")
    .replaceAll("_", " ")
    .split(" ")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function pathValue(source, dottedPath, fallback = undefined) {
  if (!source || !dottedPath) {
    return fallback;
  }
  return dottedPath.split(".").reduce((current, key) => {
    if (current && typeof current === "object" && key in current) {
      return current[key];
    }
    return undefined;
  }, source) ?? fallback;
}

function hexToRgb(hex) {
  const normalized = hex.replace("#", "");
  const expanded = normalized.length === 3
    ? normalized.split("").map((char) => char + char).join("")
    : normalized;
  const int = Number.parseInt(expanded, 16);
  return {
    r: (int >> 16) & 255,
    g: (int >> 8) & 255,
    b: int & 255,
  };
}

function rgba(hex, alpha) {
  const rgb = colorObject(hex);
  return `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${alpha})`;
}

function rgbString(rgb, alpha = 1) {
  return `rgba(${Math.round(rgb.r)}, ${Math.round(rgb.g)}, ${Math.round(rgb.b)}, ${alpha})`;
}

function colorObject(color) {
  return typeof color === "string" ? hexToRgb(color) : color;
}

function mixColor(colorA, colorB, mix) {
  const a = colorObject(colorA);
  const b = colorObject(colorB);
  const t = clamp(mix, 0, 1);
  return {
    r: a.r + ((b.r - a.r) * t),
    g: a.g + ((b.g - a.g) * t),
    b: a.b + ((b.b - a.b) * t),
  };
}

function shiftColor(hex, shifts = {}) {
  const rgb = hexToRgb(hex);
  return {
    r: clamp(rgb.r + Number(shifts.r || 0), 0, 255),
    g: clamp(rgb.g + Number(shifts.g || 0), 0, 255),
    b: clamp(rgb.b + Number(shifts.b || 0), 0, 255),
  };
}

async function api(path, options = {}) {
  const request = {
    method: options.method || "GET",
    headers: {
      "Accept": "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
  };

  const response = await fetch(path, request);
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      if (payload.detail) {
        detail = String(payload.detail);
      }
    } catch {
      // Keep the HTTP detail.
    }
    throw new Error(detail);
  }

  if (response.status === 204) {
    return null;
  }
  return response.json();
}

async function loadCatalog() {
  appState.catalog = await api("/api/mock/catalog");
}

async function loadMockState() {
  const state = await api("/api/mock/state");
  applyMockState(state, { preserveSelection: false });
}

async function loadRuntimeSnapshot() {
  try {
    appState.runtimeSnapshot = await api("/api/live/state");
    updateRuntimeSummary();
  } catch {
    // Runtime data is optional for the mock visualizer.
  }
}

function playbackRenderKey(playback) {
  if (!playback || !playback.available) {
    return "none";
  }
  return `${playback.session_id || "no-session"}|${playback.audio_url}`;
}

function applyPlaybackState(playback) {
  const nextRevision = Number(playback?.transport_revision || 0);
  const currentRevision = Number(appState.playback?.transport_revision || 0);
  const currentSession = appState.playback?.session_id || null;
  const nextSession = playback?.session_id || null;

  if (
    appState.playback?.available
    && playback?.available
    && currentSession === nextSession
    && nextRevision < currentRevision
  ) {
    return false;
  }

  appState.playback = playback;
  appState.playbackAnchorReceivedAt = performance.now();
  return true;
}

function playbackAnchorAgeMs() {
  if (!appState.playback?.available || appState.playbackAnchorReceivedAt === undefined) {
    return Number.POSITIVE_INFINITY;
  }
  return performance.now() - appState.playbackAnchorReceivedAt;
}

function playbackTransportIsFresh() {
  const playback = appState.playback;
  if (!playback?.available || !playback.playing || playback.finished || !playback.realtime) {
    return true;
  }
  return playbackAnchorAgeMs() <= PLAYBACK_STALE_MS;
}

async function loadPlaybackState() {
  const playback = await api("/api/mock/playback");
  applyPlaybackState(playback);
  renderPlayback();
}

async function refreshPlaybackState() {
  const previousKey = playbackRenderKey(appState.playback);
  const playback = await api("/api/mock/playback");
  if (!applyPlaybackState(playback)) {
    return;
  }
  const nextKey = playbackRenderKey(playback);

  if (previousKey !== nextKey) {
    renderPlayback();
    return;
  }

  syncPlaybackAudio();
  updatePlaybackStatus();
  drawPlaybackWaveform();
  updateShowEditorActiveState();
}

async function refreshUniverseSnapshot() {
  appState.universeSnapshot = await api("/api/mock/universes");
  const universe = appState.universeSnapshot.universes.find(
    (entry) => entry.universe === appState.selectedUniverse,
  );
  if (!universe) {
    appState.selectedUniverse = appState.universeSnapshot.universes[0]?.universe || 1;
  }
  renderMonitor();
}

function applyMockState(state, { preserveSelection = true } = {}) {
  const previousSelection = appState.selectedFixtureId;
  appState.fixtures = state.fixtures || [];
  appState.sceneId = state.scene_id;
  appState.masterIntensity = Number(state.master_intensity);
  appState.masterSpeed = Number(state.master_speed);
  appState.blackout = Boolean(state.blackout);

  if (preserveSelection) {
    const hasSelection = appState.fixtures.some((fixture) => fixture.id === previousSelection);
    appState.selectedFixtureId = hasSelection ? previousSelection : appState.fixtures[0]?.id || null;
  } else {
    appState.selectedFixtureId = appState.fixtures[0]?.id || null;
  }
}

function renderPlayback() {
  if (!elements.playbackPanel) {
    return;
  }

  const playback = appState.playback;
  if (!playback || !playback.available) {
    elements.playbackPanel.className = "playback-panel empty";
    elements.playbackPanel.textContent = "Start a file-backed session with web mode to expose the current track here.";
    return;
  }

  elements.playbackPanel.className = "playback-panel";
  elements.playbackPanel.innerHTML = `
    <div class="playback-meta">
      <div>
        <strong>${playback.track_title || playback.file_name}</strong>
        <span>${playback.track_artist ? `${playback.track_artist} · ` : ""}${playback.duration_seconds.toFixed(1)}s</span>
      </div>
      <span>${(playback.show_sections || []).length} sections</span>
    </div>
    <div class="playback-artifacts">
      <span>Autosave ${safeText(playback.show_plan_path, "pending")}</span>
      ${playback.ilda_export_url ? `<a class="playback-export" href="${playback.ilda_export_url}">Download ${safeText(playback.ilda_transport_type, "ILDA").toUpperCase()}</a>` : "<span>No ILDA export yet</span>"}
    </div>
    <div class="playback-controls">
      <button type="button" id="sync-audio">Sync To Live</button>
      <span id="playback-status">Waiting for browser audio…</span>
    </div>
    <audio id="track-audio" controls preload="metadata" src="${playback.audio_url}"></audio>
    <canvas id="waveform-canvas" width="640" height="96"></canvas>
    <div id="show-editor" class="show-editor"></div>
  `;

  const audio = elements.playbackPanel.querySelector("#track-audio");
  const waveformCanvas = elements.playbackPanel.querySelector("#waveform-canvas");
  const syncButton = elements.playbackPanel.querySelector("#sync-audio");

  elements.playbackAudio = audio;
  elements.waveformCanvas = waveformCanvas;
  elements.playbackStatus = elements.playbackPanel.querySelector("#playback-status");
  elements.playbackSyncButton = syncButton;
  elements.showEditor = elements.playbackPanel.querySelector("#show-editor");

  syncButton.addEventListener("click", async () => {
    const target = playbackTargetTime();
    if (Number.isFinite(target)) {
      audio.currentTime = target;
    }
    try {
      await audio.play();
    } catch (error) {
      console.error(error);
    }
    syncPlaybackAudio(true);
  });

  audio.addEventListener("play", () => {
    syncPlaybackAudio(true);
  });
  audio.addEventListener("timeupdate", () => {
    updatePlaybackStatus();
    drawPlaybackWaveform();
  });
  audio.addEventListener("loadedmetadata", () => {
    syncPlaybackAudio(true);
    updatePlaybackStatus();
    drawPlaybackWaveform();
  });
  audio.addEventListener("seeked", () => {
    updatePlaybackStatus();
    drawPlaybackWaveform();
  });
  waveformCanvas.addEventListener("click", (event) => {
    const rect = waveformCanvas.getBoundingClientRect();
    const ratio = clamp((event.clientX - rect.left) / rect.width, 0, 1);
    const duration = Number(playback.duration_seconds || 0);
    seekPlaybackTo(duration * ratio).catch((error) => {
      console.error(error);
    });
  });
  updatePlaybackStatus();
  drawPlaybackWaveform();
  renderShowEditor();
}

async function patchShowSection(sectionId, changes) {
  const playback = await api(`/api/mock/playback/show-sections/${sectionId}`, {
    method: "PATCH",
    body: { changes },
  });
  applyPlaybackState(playback);
  renderPlayback();
}

async function seekPlaybackTo(seconds) {
  const playback = await api("/api/mock/playback/seek", {
    method: "POST",
    body: { seconds },
  });
  applyPlaybackState(playback);
  if (elements.playbackAudio) {
    elements.playbackAudio.currentTime = Number(playback.playhead_seconds || 0);
  }
  updatePlaybackStatus();
  drawPlaybackWaveform();
  updateShowEditorActiveState();
}

function renderShowEditor() {
  if (!elements.showEditor) {
    return;
  }
  const sections = appState.playback?.show_sections || [];
  if (sections.length === 0) {
    elements.showEditor.innerHTML = `
      <div class="show-editor-empty">No imported Rekordbox sections for this track yet.</div>
    `;
    return;
  }

  const activeSection = currentShowSection();
  const patternSummary = (section) => {
    const families = [
      section.laser_enabled ? "lasers" : null,
      section.movers_enabled ? "movers" : null,
      section.washes_enabled ? "washes" : null,
      section.leds_enabled ? "LEDs" : null,
    ].filter(Boolean);
    const familyText = families.length > 0 ? families.join(", ") : "all fixtures muted";
    const strobeProfile = sectionVariant(section, "strobe_profile");
    const laserExpression = sectionVariant(section, "laser_expression");
    const strobeText = safeText(strobeProfile.label, section.strobe_level > 0.2 ? "strong strobe accents" : section.strobe_level > 0 ? "light strobe accents" : "no strobes");
    return `${section.fixture_mode.replaceAll("_", " ")} · scene ${safeText(sceneById(section.scene_id)?.label, section.scene_id)} · ${safeText(laserExpression.content_family, "beam")} / ${safeText(laserExpression.geometry_family, "fan")} · ${safeText(laserExpression.target_strategy, "wide_zone_sweep")} · laser ${safeText(section.laser_expression?.label || section.laser_variant?.label, section.laser_pattern)} · mover ${safeText(section.mover_variant?.label, section.mover_pattern)} · wash ${safeText(section.wash_variant?.label, section.wash_pattern)} · led ${safeText(section.led_variant?.label, section.led_pattern)} · ${familyText} · intensity ${Number(section.intensity_multiplier).toFixed(2)} · motion ${Number(section.motion_multiplier).toFixed(2)} · ${strobeText}`;
  };
  const sceneOptions = appState.catalog.scene_templates
    .map((scene) => `<option value="${scene.scene_id}">${scene.label}</option>`)
    .join("");
  const modeOptions = [
    ["intro", "Intro"],
    ["breakdown", "Breakdown"],
    ["rebuild", "Rebuild"],
    ["peak_return", "Peak Return"],
    ["outro", "Outro"],
  ]
    .map(([value, label]) => `<option value="${value}">${label}</option>`)
    .join("");
  const laserPatternOptions = [
    ["fan", "Fan"],
    ["thin_scan", "Thin Scan"],
    ["vertical_rake", "Vertical Rake"],
    ["burst_fan", "Burst Fan"],
    ["liquid_sky", "Liquid Sky"],
    ["crisscross", "Crisscross"],
    ["starburst", "Starburst"],
    ["wave", "Wave"],
    ["rotor", "Rotor"],
    ["alternating_beam_groups", "Alternating Groups"],
    ["shutter_hits", "Shutter Hits"],
    ["cone", "Cone"],
    ["tunnel", "Tunnel"],
  ].map(([value, label]) => `<option value="${value}">${label}</option>`).join("");
  const moverPatternOptions = [
    ["hold", "Hold"],
    ["drift", "Drift"],
    ["rise", "Rise"],
    ["cross_sweep", "Cross Sweep"],
    ["circle", "Circle"],
    ["figure_eight", "Figure Eight"],
    ["leaf", "Leaf"],
    ["mirror_fan", "Mirror Fan"],
    ["square", "Square"],
    ["diamond", "Diamond"],
    ["line_bounce", "Line Bounce"],
    ["ping_pong_tilt", "Ping Pong Tilt"],
    ["snap_hits", "Snap Hits"],
  ].map(([value, label]) => `<option value="${value}">${label}</option>`).join("");
  const washPatternOptions = [
    ["ambient", "Ambient"],
    ["bloom", "Bloom"],
    ["breath", "Breath"],
    ["punch", "Punch"],
    ["downbeat_hit", "Downbeat Hit"],
    ["gradient_roll", "Gradient Roll"],
    ["center_out", "Center Out"],
    ["outside_in", "Outside In"],
    ["breakdown_glow", "Breakdown Glow"],
    ["build_ramp", "Build Ramp"],
    ["drop_slam", "Drop Slam"],
    ["white_peak", "White Peak"],
    ["fade", "Fade"],
  ].map(([value, label]) => `<option value="${value}">${label}</option>`).join("");
  const ledPatternOptions = [
    ["pulse", "Pulse"],
    ["chase", "Chase"],
    ["sparkle", "Sparkle"],
    ["ramp", "Ramp"],
    ["snake", "Snake"],
    ["fizzle", "Fizzle"],
    ["vertical_build", "Vertical Build"],
    ["vertical_offset", "Vertical Offset"],
    ["horizontal_lines", "Horizontal Lines"],
    ["horizontal_ramp", "Horizontal Ramp"],
    ["rotating_line", "Rotating Line"],
    ["audio_spectrum", "Audio Spectrum"],
    ["fade", "Fade"],
  ].map(([value, label]) => `<option value="${value}">${label}</option>`).join("");
  const laserContentOptions = [
    ["beam", "Beam"],
    ["abstract", "Abstract"],
    ["transition", "Transition"],
  ].map(([value, label]) => `<option value="${value}">${label}</option>`).join("");
  const laserTargetBiasOptions = [
    ["crowd", "Crowd"],
    ["mid_air", "Mid Air"],
    ["ceiling", "Ceiling"],
  ].map(([value, label]) => `<option value="${value}">${label}</option>`).join("");
  const targetStrategyOptions = [
    ["wide_zone_sweep", "Wide Zone Sweep"],
    ["drop_launch_fan", "Drop Launch Fan"],
    ["split_zone_hits", "Split Zone Hits"],
    ["depth_chase", "Depth Chase"],
    ["cross_room_fans", "Cross Room Fans"],
    ["vertical_pressure", "Vertical Pressure"],
    ["aerial_hold", "Aerial Hold"],
    ["ceiling_bloom", "Ceiling Bloom"],
    ["line_sweep", "Line Sweep"],
    ["spiral_air_wrap", "Spiral Air Wrap"],
  ].map(([value, label]) => `<option value="${value}">${label}</option>`).join("");
  const blankingStrategyOptions = [
    ["open_groove", "Open Groove"],
    ["impact_gates", "Impact Gates"],
    ["alternating_groups", "Alternating Groups"],
    ["breathing_aperture", "Breathing Aperture"],
    ["cross_cutting", "Cross Cutting"],
    ["riser_chops", "Riser Chops"],
    ["soft_air", "Soft Air"],
    ["soft_sweep", "Soft Sweep"],
    ["tight_slice", "Tight Slice"],
    ["rolling_draw", "Rolling Draw"],
  ].map(([value, label]) => `<option value="${value}">${label}</option>`).join("");
  const colorStrategyOptions = [
    ["slow_palette_drift", "Slow Palette Drift"],
    ["white_accent_launch", "White Accent Launch"],
    ["contrast_flips", "Contrast Flips"],
    ["center_pull_morph", "Center Pull Morph"],
    ["dual_cycle_contrast", "Dual Cycle Contrast"],
    ["narrowing_palette", "Narrowing Palette"],
    ["harmonic_morph", "Harmonic Morph"],
    ["halo_morph", "Halo Morph"],
    ["single_hue_focus", "Single Hue Focus"],
    ["evolving_multicolor", "Evolving Multicolor"],
  ].map(([value, label]) => `<option value="${value}">${label}</option>`).join("");

  elements.showEditor.innerHTML = `
    <div class="subhead">
      <h3>Agentic Show</h3>
      <p>Imported from Rekordbox and editable per section.</p>
    </div>
    <div class="show-segment-strip">
      ${sections.map((section) => `
        <button type="button" class="show-segment-chip${activeSection?.id === section.id ? " active" : ""}" data-jump-section="${section.id}">
          <strong>${section.label}</strong>
          <span>${section.start_seconds.toFixed(1)}s</span>
        </button>
      `).join("")}
    </div>
    <div class="show-section-list">
      ${sections.map((section) => `
        <div class="show-section-card${activeSection?.id === section.id ? " active" : ""}" data-section-id="${section.id}">
          <div class="show-section-header">
            <strong>${section.label}</strong>
            <span>${section.start_seconds.toFixed(1)}s - ${section.end_seconds.toFixed(1)}s</span>
          </div>
          <p class="show-pattern-summary">${patternSummary(section)}</p>
          <div class="show-section-grid">
            <label>
              <span>Scene</span>
              <select data-field="scene_id">${sceneOptions}</select>
            </label>
            <label>
              <span>Mode</span>
              <select data-field="fixture_mode">${modeOptions}</select>
            </label>
            <label>
              <span>Intensity</span>
              <input data-field="intensity_multiplier" type="range" min="0" max="1.4" step="0.05" value="${section.intensity_multiplier}" />
            </label>
            <label>
              <span>Motion</span>
              <input data-field="motion_multiplier" type="range" min="0.1" max="2.2" step="0.05" value="${section.motion_multiplier}" />
            </label>
            <label>
              <span>Strobe</span>
              <input data-field="strobe_level" type="range" min="0" max="1" step="0.05" value="${section.strobe_level}" />
            </label>
            <label>
              <span>Laser Pattern</span>
              <select data-field="laser_pattern">${laserPatternOptions}</select>
            </label>
            <label>
              <span>Mover Pattern</span>
              <select data-field="mover_pattern">${moverPatternOptions}</select>
            </label>
            <label>
              <span>Wash Pattern</span>
              <select data-field="wash_pattern">${washPatternOptions}</select>
            </label>
            <label>
              <span>LED Pattern</span>
              <select data-field="led_pattern">${ledPatternOptions}</select>
            </label>
            <label>
              <span>Laser Family</span>
              <select data-field="laser_expression.content_family">${laserContentOptions}</select>
            </label>
            <label>
              <span>Target Bias</span>
              <select data-field="laser_expression.target_bias">${laserTargetBiasOptions}</select>
            </label>
            <label>
              <span>Target Strategy</span>
              <select data-field="laser_expression.target_strategy">${targetStrategyOptions}</select>
            </label>
            <label>
              <span>Blanking</span>
              <select data-field="laser_expression.blanking_strategy">${blankingStrategyOptions}</select>
            </label>
            <label>
              <span>Color Strategy</span>
              <select data-field="laser_expression.color_strategy">${colorStrategyOptions}</select>
            </label>
            <label>
              <span>Launch</span>
              <input data-field="laser_expression.phrase_envelope.launch_intensity" type="range" min="0" max="1.4" step="0.05" value="${pathValue(section, "laser_expression.phrase_envelope.launch_intensity", 1)}" />
            </label>
            <label>
              <span>Sustain</span>
              <input data-field="laser_expression.phrase_envelope.sustain_intensity" type="range" min="0" max="1.4" step="0.05" value="${pathValue(section, "laser_expression.phrase_envelope.sustain_intensity", 0.7)}" />
            </label>
            <label>
              <span>Release</span>
              <input data-field="laser_expression.phrase_envelope.release_intensity" type="range" min="0" max="1.4" step="0.05" value="${pathValue(section, "laser_expression.phrase_envelope.release_intensity", 0.4)}" />
            </label>
            <label class="show-variation-plan">
              <span>Variation Plan</span>
              <textarea data-field="laser_expression.variation_plan" rows="3">${(pathValue(section, "laser_expression.variation_plan", []) || []).join("\n")}</textarea>
            </label>
            <div class="show-toggle-row">
              <label><input data-field="laser_enabled" type="checkbox" ${section.laser_enabled ? "checked" : ""} />Lasers</label>
              <label><input data-field="movers_enabled" type="checkbox" ${section.movers_enabled ? "checked" : ""} />Movers</label>
              <label><input data-field="washes_enabled" type="checkbox" ${section.washes_enabled ? "checked" : ""} />Washes</label>
              <label><input data-field="leds_enabled" type="checkbox" ${section.leds_enabled ? "checked" : ""} />LEDs</label>
            </div>
          </div>
        </div>
      `).join("")}
    </div>
  `;

  elements.showEditor.querySelectorAll(".show-section-card").forEach((card, index) => {
    const section = sections[index];
    if (!section) {
      return;
    }
    card.querySelectorAll("select,input,textarea").forEach((input) => {
      const eventName = input.type === "range" ? "input" : "change";
      if (input.dataset.field === "scene_id") {
        input.value = section.scene_id;
      }
      if (input.dataset.field === "fixture_mode") {
        input.value = section.fixture_mode;
      }
      if (
        input.dataset.field === "laser_pattern"
        || input.dataset.field === "mover_pattern"
        || input.dataset.field === "wash_pattern"
        || input.dataset.field === "led_pattern"
      ) {
        input.value = section[input.dataset.field];
      }
      if (input.dataset.field?.startsWith("laser_expression.") && input.tagName !== "TEXTAREA") {
        input.value = pathValue(section, input.dataset.field, input.value);
      }
      input.addEventListener(eventName, (event) => {
        const target = event.currentTarget;
        const field = target.dataset.field;
        let value = target.type === "checkbox" ? target.checked : target.value;
        if (target.type === "range") {
          value = Number(value);
        } else if (target.tagName === "TEXTAREA") {
          value = String(value);
        }
        patchShowSection(section.id, { [field]: value }).catch((error) => {
          console.error(error);
        });
      });
    });
  });

  elements.showEditor.querySelectorAll("[data-jump-section]").forEach((button) => {
    button.addEventListener("click", () => {
      const section = sections.find((item) => item.id === button.dataset.jumpSection);
      if (!section) {
        return;
      }
      seekPlaybackTo(Number(section.start_seconds)).catch((error) => {
        console.error(error);
      });
    });
  });
}

function updateShowEditorActiveState() {
  const activeSection = currentShowSection();
  if (!elements.showEditor) {
    return;
  }
  elements.showEditor.querySelectorAll(".show-section-card").forEach((card) => {
    card.classList.toggle("active", activeSection?.id === card.dataset.sectionId);
  });
  elements.showEditor.querySelectorAll(".show-segment-chip").forEach((chip) => {
    chip.classList.toggle("active", activeSection?.id === chip.dataset.jumpSection);
  });
}

function playbackTargetTime() {
  const playback = appState.playback;
  if (!playback || !playback.available) {
    return 0;
  }

  let target = Number(playback.playhead_seconds || 0);
  if (playback.playing && playback.realtime && !playback.finished && playbackTransportIsFresh()) {
    const elapsedSeconds = playbackAnchorAgeMs() / 1000;
    target += elapsedSeconds * Number(playback.speed || 1);
  }
  return clamp(target, 0, Number(playback.duration_seconds || target || 0));
}

function drawPlaybackWaveform() {
  if (!elements.waveformCanvas || !appState.playback?.available) {
    return;
  }

  const waveformCanvas = elements.waveformCanvas;
  const ctx = waveformCanvas.getContext("2d");
  const waveform = Array.isArray(appState.playback.waveform) ? appState.playback.waveform : [];
  const width = waveformCanvas.width;
  const height = waveformCanvas.height;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "rgba(9, 18, 31, 0.88)";
  ctx.fillRect(0, 0, width, height);

  ctx.strokeStyle = "rgba(255,255,255,0.08)";
  ctx.beginPath();
  ctx.moveTo(0, height / 2);
  ctx.lineTo(width, height / 2);
  ctx.stroke();

  if (waveform.length > 0) {
    const barWidth = width / waveform.length;
    ctx.fillStyle = "rgba(18, 216, 255, 0.75)";
    waveform.forEach((value, index) => {
      const amplitude = Math.max(2, value * (height * 0.42));
      const x = index * barWidth;
      ctx.fillRect(x, (height / 2) - amplitude, Math.max(1, barWidth - 1), amplitude * 2);
    });
  }

  const sections = appState.playback?.show_sections || [];
  sections.forEach((section, index) => {
    const duration = Number(appState.playback.duration_seconds || 0);
    if (duration <= 0) {
      return;
    }
    const startX = clamp((Number(section.start_seconds) / duration) * width, 0, width);
    const endX = clamp((Number(section.end_seconds) / duration) * width, startX + 1, width);
    const stripeColor = index % 2 === 0 ? "rgba(255,255,255,0.05)" : "rgba(255,255,255,0.10)";
    ctx.fillStyle = stripeColor;
    ctx.fillRect(startX, 0, Math.max(1, endX - startX), 12);
    ctx.fillStyle = "rgba(255,255,255,0.78)";
    ctx.font = "600 10px Trebuchet MS";
    ctx.fillText(section.kind.toUpperCase(), Math.min(startX + 4, width - 52), 10);
    ctx.strokeStyle = "rgba(255,255,255,0.22)";
    ctx.beginPath();
    ctx.moveTo(startX, 0);
    ctx.lineTo(startX, height);
    ctx.stroke();
  });

  const duration = Number(appState.playback.duration_seconds || 0);
  const audio = elements.playbackAudio;
  const visualTime = audio && !audio.paused ? audio.currentTime : playbackTargetTime();
  const progress = duration > 0 ? clamp(visualTime / duration, 0, 1) : 0;
  ctx.fillStyle = "rgba(248, 94, 0, 0.95)";
  ctx.fillRect(progress * width, 0, 2, height);
}

function updatePlaybackStatus() {
  if (!elements.playbackStatus || !appState.playback?.available) {
    return;
  }
  const audio = elements.playbackAudio;
  const target = playbackTargetTime();
  const browserTime = audio ? Number(audio.currentTime || 0) : 0;
  const drift = browserTime - target;
  const section = currentShowSection(target);
  const stateLabel = appState.playback.finished
    ? "finished"
    : !playbackTransportIsFresh()
      ? "sync stale"
    : appState.playback.playing
      ? "live"
      : "idle";
  const staleText = playbackTransportIsFresh() ? "" : ` · stale ${(playbackAnchorAgeMs() / 1000).toFixed(2)}s`;
  const sectionText = section ? ` · ${section.label}` : "";
  elements.playbackStatus.textContent = `${stateLabel}${sectionText} · server ${target.toFixed(2)}s · browser ${browserTime.toFixed(2)}s · drift ${drift.toFixed(3)}s${staleText}`;
}

function syncPlaybackAudio(force = false) {
  const playback = appState.playback;
  const audio = elements.playbackAudio;
  if (!playback || !playback.available || !audio) {
    return;
  }

  const target = playbackTargetTime();
  const current = Number(audio.currentTime || 0);
  const drift = target - current;

  if (playback.finished) {
    audio.playbackRate = 1;
    if (Math.abs(drift) > 0.02) {
      audio.currentTime = target;
    }
    if (!audio.paused) {
      audio.pause();
    }
    updatePlaybackStatus();
    drawPlaybackWaveform();
    return;
  }

  if (!playback.realtime || !playback.playing) {
    audio.playbackRate = 1;
    if ((force || audio.paused) && Math.abs(drift) > 0.05) {
      audio.currentTime = target;
    }
    updatePlaybackStatus();
    drawPlaybackWaveform();
    return;
  }

  if (!playbackTransportIsFresh()) {
    audio.playbackRate = 1;
    if (!audio.paused) {
      audio.pause();
    }
    updatePlaybackStatus();
    drawPlaybackWaveform();
    return;
  }

  if (force || Math.abs(drift) > 0.12) {
    audio.currentTime = target;
    audio.playbackRate = 1;
  } else if (Math.abs(drift) > 0.015) {
    audio.playbackRate = clamp(1 + drift * 0.45, 0.95, 1.05);
  } else {
    audio.playbackRate = 1;
  }

  if (audio.paused && Math.abs(drift) > 0.05) {
    audio.currentTime = target;
  }

  updatePlaybackStatus();
  drawPlaybackWaveform();
}

function templateBySlug(slug) {
  return appState.catalog.fixture_templates.find((item) => item.slug === slug);
}

function sceneById(sceneId) {
  return appState.catalog.scene_templates.find((item) => item.scene_id === sceneId)
    || appState.catalog.scene_templates[0];
}

function currentPlaybackSeconds() {
  const audio = elements.playbackAudio;
  if (audio && !audio.paused && Number.isFinite(audio.currentTime)) {
    return Number(audio.currentTime);
  }
  return playbackTargetTime();
}

function currentShowSection(seconds = currentPlaybackSeconds()) {
  const sections = appState.playback?.show_sections || [];
  if (sections.length === 0) {
    return null;
  }
  const clamped = Math.max(0, seconds);
  return sections.find((section) => clamped >= section.start_seconds && clamped < section.end_seconds)
    || sections[sections.length - 1];
}

function activeStageScene(playbackSeconds = currentPlaybackSeconds()) {
  const showSection = currentShowSection(playbackSeconds);
  if (showSection?.scene_id) {
    return sceneById(showSection.scene_id);
  }
  const runtimeSceneId = appState.runtimeSnapshot?.active_scene_id;
  if (runtimeSceneId) {
    return sceneById(runtimeSceneId);
  }
  return sceneById(appState.sceneId);
}

function beatPulseFromPhase(phase) {
  const wrapped = ((phase % 1) + 1) % 1;
  const distance = Math.min(Math.abs(wrapped - 0.08), 1 - Math.abs(wrapped - 0.08));
  return clamp(1 - (distance / 0.18), 0, 1) ** 2;
}

function triangleWave(value) {
  const wrapped = ((value % 1) + 1) % 1;
  return 1 - Math.abs((wrapped * 2) - 1);
}

function sectionVariant(section, key) {
  return section && typeof section[key] === "object" ? section[key] : {};
}

function modulatedStrobeLevel(section, visualBase) {
  const baseLevel = clamp(Number(section?.strobe_level ?? visualBase ?? 0), 0, 1);
  const profile = sectionVariant(section, "strobe_profile");
  const floor = clamp(Number(profile.floor ?? baseLevel), 0, 1);
  const ceiling = clamp(Number(profile.ceiling ?? baseLevel), floor, 1);
  const rate = clamp(Number(profile.rate_multiplier ?? 1), 0.2, 4);
  const shape = safeText(profile.shape, "pulse");
  const mode = safeText(profile.mode, "pulse");
  const progress = clamp(Number(section?.__sectionProgress ?? 0), 0, 1);
  const beatPulse = clamp(Number(section?.__beatPulse ?? 0), 0, 1);
  const energy = clamp(Number(section?.__energy ?? 0), 0, 1);

  let envelope = beatPulse;
  if (mode === "riser") {
    envelope = clamp((progress * 0.8) + beatPulse * 0.45, 0, 1);
  } else if (mode === "impact") {
    const launch = progress < 0.12 ? 1 - progress * 4.2 : 0;
    const settle = progress > 0.2 ? Math.max(0, 0.55 - ((progress - 0.2) * 0.9)) : 0.55;
    envelope = clamp(Math.max(beatPulse, launch, settle * beatPulse) * (0.88 + energy * 0.2), 0, 1);
  } else if (mode === "burst") {
    const burstWindow = triangleWave((progress * 3.2) + 0.18) > 0.7 ? 1 : 0.38;
    envelope = clamp(((triangleWave((progress * 4 + beatPulse) * rate) * 0.6) + beatPulse * 0.55) * burstWindow, 0, 1);
  } else if (mode === "restraint") {
    envelope = clamp(beatPulse * 0.35, 0, 0.4);
  }

  if (shape === "swell") {
    envelope = clamp(envelope * (0.45 + progress * 0.85), 0, 1);
  } else if (shape === "gated") {
    envelope = triangleWave((progress + beatPulse) * rate) > 0.55 ? envelope : envelope * 0.18;
  } else if (shape === "burst") {
    envelope = clamp(Math.max(envelope, beatPulse * 1.1), 0, 1);
  }

  return clamp(floor + (ceiling - floor) * envelope, 0, 1);
}

function dropSectionEnvelope(structure, fixtureMode, sectionProgress, beatPhase, beatPulse) {
  const dropLike = structure === "drop" || fixtureMode === "peak_return";
  if (!dropLike) {
    return {
      intensity: 1,
      accent: 1,
    };
  }

  const launch = sectionProgress < 0.16
    ? 1.06 + ((0.16 - sectionProgress) / 0.16) * 0.18
    : 0;
  const sustain = 0.68 + triangleWave(sectionProgress * 3.4 + beatPhase * 0.35) * 0.12;
  const grooveBreath = 0.92 + Math.sin((sectionProgress * 6.5 + beatPhase) * Math.PI * 2) * 0.06;
  const intensity = clamp(Math.max(launch, sustain) * grooveBreath + beatPulse * 0.08, 0.58, 1.2);
  const accent = sectionProgress < 0.18
    ? 1
    : triangleWave(sectionProgress * 4.1 + beatPhase * 0.6) > 0.76
      ? 1
      : 0.52;
  return { intensity, accent };
}

function laserPatternFamily(pattern) {
  if (["burst_fan", "starburst", "alternating_beam_groups", "shutter_hits"].includes(pattern)) {
    return "burst";
  }
  if (["vertical_rake", "liquid_sky", "cone"].includes(pattern)) {
    return "vertical";
  }
  if (["tunnel", "crisscross", "rotor"].includes(pattern)) {
    return "tunnel";
  }
  if (["thin_scan", "wave"].includes(pattern)) {
    return "scan";
  }
  return "fan";
}

function moverPatternFamily(pattern) {
  if (["hold"].includes(pattern)) return "hold";
  if (["rise", "ping_pong_tilt"].includes(pattern)) return "rise";
  if (["cross_sweep", "mirror_fan", "line_bounce"].includes(pattern)) return "cross";
  if (["circle", "figure_eight", "leaf", "square", "diamond"].includes(pattern)) return "shape";
  if (["snap_hits"].includes(pattern)) return "hits";
  return "drift";
}

function washPatternFamily(pattern) {
  if (["fade", "breakdown_glow"].includes(pattern)) return "fade";
  if (["bloom", "build_ramp", "center_out", "outside_in", "gradient_roll"].includes(pattern)) return "bloom";
  if (["punch", "downbeat_hit", "drop_slam", "white_peak"].includes(pattern)) return "punch";
  if (["breath"].includes(pattern)) return "breath";
  return "ambient";
}

function ledPatternFamily(pattern) {
  if (["chase", "snake", "rotating_line"].includes(pattern)) return "chase";
  if (["sparkle", "fizzle", "audio_spectrum"].includes(pattern)) return "sparkle";
  if (["ramp", "vertical_build", "vertical_offset", "horizontal_ramp", "horizontal_lines"].includes(pattern)) return "ramp";
  if (["fade"].includes(pattern)) return "fade";
  return "pulse";
}

function describeLaserBehavior(output, visual) {
  const parts = [];
  if (output.dropMode && visual.strobeActive) {
    parts.push("drop strobe hits");
  } else if (output.dropMode) {
    parts.push("drop fan");
  } else if (visual.section?.fixture_mode === "rebuild") {
    parts.push("riser sweep");
  } else {
    parts.push("texture sweep");
  }

  if (output.geometryFamily === "sky" || output.geometryFamily === "helix") {
    parts.push("aerial sweep");
  } else if (output.geometryFamily === "grouped" || output.geometryFamily === "burst") {
    parts.push("crowd punch");
  } else if (output.geometryFamily === "lattice") {
    parts.push("cross lattice");
  }

  if (Math.abs(output.verticalSweep || 0) > 0.24) {
    parts.push("up/down rake");
  }
  if (Math.abs(output.rotation || 0) > 0.55) {
    parts.push("rotating fan");
  }
  if (output.beamCount >= 6) {
    parts.push(`${output.beamCount} beams`);
  }
  return parts.join(" · ");
}

function describeMoverBehavior(output, visual) {
  const family = moverPatternFamily(output.pattern);
  if (family === "hold") {
    return "held focus look";
  }
  if (family === "hits") {
    return visual.beatPulse > 0.45 ? "snap hits on beat" : "waiting for hit";
  }
  if (family === "cross") {
    return "wide cross sweeps";
  }
  if (family === "shape") {
    return "figure motion across stage";
  }
  if (family === "rise") {
    return "lifting tilt arc";
  }
  return "slow pan/tilt drift";
}

function describeWashBehavior(output) {
  const family = washPatternFamily(output.pattern);
  if (family === "punch") {
    return "punching downbeat blooms";
  }
  if (family === "bloom") {
    return "expanding color bloom";
  }
  if (family === "fade") {
    return "fading atmosphere";
  }
  if (family === "breath") {
    return "breathing wash";
  }
  return "steady ambient fill";
}

function describeLedBehavior(output) {
  const family = ledPatternFamily(output.pattern);
  if (family === "chase") {
    return "traveling chase";
  }
  if (family === "sparkle") {
    return "sparkle accents";
  }
  if (family === "ramp") {
    return "building ramp";
  }
  if (family === "fade") {
    return "soft static glow";
  }
  return "pulse engine";
}

function describeFixtureActivity(fixture, output, visual) {
  const sectionLabel = titleCaseWords(visual.section?.label || visual.section?.kind || visual.structure || "live");
  const intensityText = `${Math.round(clamp(output.intensity || 0, 0, 1) * 100)}%`;
  let behavior;
  if (fixture.type === "laser") {
    behavior = describeLaserBehavior(output, visual);
  } else if (fixture.type === "moving_head") {
    behavior = describeMoverBehavior(output, visual);
  } else if (fixture.type === "wash") {
    behavior = describeWashBehavior(output, visual);
  } else {
    behavior = describeLedBehavior(output, visual);
  }
  return {
    typeLabel: titleCaseWords(fixture.type),
    patternLabel: safeText(output.expressionLabel || output.variantLabel, titleCaseWords(output.pattern || "idle")),
    sectionLabel,
    behavior,
    intensityText,
    muted: (output.intensity || 0) <= 0.02,
  };
}

function laserBeamColor(baseColor, laserExpression, output, visual) {
  const mode = safeText(laserExpression.color_mode, "static");
  const whiteAccent = clamp(Number(laserExpression.white_accent || 0), 0, 1);
  const cycleRate = Number(laserExpression.color_cycle_rate || 1) * (0.75 + visual.colorDrive * 0.85);
  const phase = Number(output.phase || 0);

  if (mode === "white_hits") {
    const mix = clamp(
      (visual.beatPulse * 0.55)
        + (visual.strobeActive ? 0.28 : 0)
        + whiteAccent * 0.18
        + visual.laserAggression * 0.2
        + visual.timbralHarshness * 0.14,
      0,
      1,
    );
    return mixColor(baseColor, "#ffffff", mix);
  }
  if (mode === "morph") {
    const target = shiftColor(baseColor, {
      r: 15 + visual.pitchHeight * 55,
      g: -45 + visual.harmonicChange * 30,
      b: 35 + visual.melodicSmoothness * 45,
    });
    const mix = ((Math.sin(phase * cycleRate) + 1) * 0.5) * (0.45 + visual.colorDrive * 0.6);
    return mixColor(baseColor, target, mix);
  }
  if (mode === "dual_cycle") {
    const alt = shiftColor(baseColor, {
      r: -30 + visual.timbralHarshness * 35,
      g: 35 + visual.melodicSmoothness * 45,
      b: 20 + visual.pitchSalience * 65,
    });
    const mix = triangleWave(phase * cycleRate * 0.8) * (0.35 + visual.colorDrive * 0.7);
    return mixColor(baseColor, alt, mix);
  }
  return hexToRgb(baseColor);
}

function laserDynamicTargetBias(targetBias, visual, dropMode) {
  if (dropMode && visual.laserAggression > 0.58) {
    return "crowd";
  }
  if (!dropMode && visual.melodicSmoothness > 0.7 && visual.tonalStability > 0.6) {
    return "ceiling";
  }
  if (visual.melodicSmoothness > visual.laserAggression + 0.12) {
    return "mid_air";
  }
  return targetBias;
}

function runtimeVisualState(timeSeconds) {
  const playbackSeconds = currentPlaybackSeconds();
  const showSection = currentShowSection(playbackSeconds);
  const scene = activeStageScene(playbackSeconds);
  const semantic = appState.runtimeSnapshot?.semantic_frame || {};
  const director = appState.runtimeSnapshot?.director_summary || {};
  const beatConfidence = clamp(Number(semantic.beat_confidence ?? 0), 0, 1);
  const harmonicRatio = clamp(Number(semantic.harmonic_ratio ?? 0.5), 0, 1);
  const percussiveRatio = clamp(Number(semantic.percussive_ratio ?? (1 - harmonicRatio)), 0, 1);
  const tonalStability = clamp(Number(semantic.tonal_stability ?? 0.5), 0, 1);
  const harmonicChange = clamp(Number(semantic.harmonic_change ?? 0.0), 0, 1);
  const pitchSalience = clamp(Number(semantic.pitch_salience ?? 0.0), 0, 1);
  const pitchHeight = clamp(Number(semantic.pitch_height ?? 0.0), 0, 1);
  const timbralHarshness = clamp(Number(semantic.timbral_harshness ?? 0.0), 0, 1);
  const melodicSmoothness = clamp(Number(director.melodic_smoothness ?? ((harmonicRatio * 0.55) + (tonalStability * 0.45))), 0, 1);
  const laserAggression = clamp(Number(director.laser_aggression ?? ((percussiveRatio * 0.55) + (timbralHarshness * 0.45))), 0, 1);
  const colorDrive = clamp(Number(director.color_drive ?? ((harmonicChange * 0.6) + (pitchSalience * 0.4))), 0, 1);
  const sectionIntensity = clamp(Number(showSection?.intensity_multiplier ?? 1), 0, 1.6);
  const energy = clamp(Number(director.energy_level ?? scene.pulse ?? 0.4) * Math.max(0.45, sectionIntensity), 0, 1);
  const beatPhase = clamp(
    Number.isFinite(Number(semantic.beat_phase))
      ? Number(semantic.beat_phase)
      : (timeSeconds * scene.speed_multiplier * 1.4) % 1,
    0,
    1,
  );
  const beatPulse = beatPulseFromPhase(beatPhase) * Math.max(0.2, beatConfidence);
  const structure = safeText(showSection?.kind || semantic.structure, "unknown").toLowerCase();
  const movementStyle = safeText(director.movement_style, "steady").toLowerCase();
  const motionScale = movementStyle === "aggressive"
    ? 1.35 + (laserAggression * 0.35)
    : movementStyle === "sparse"
      ? 0.58 + (melodicSmoothness * 0.12)
      : 0.92 + (colorDrive * 0.15);
  const sectionMotionMultiplier = clamp(Number(showSection?.motion_multiplier ?? 1), 0.15, 2.4);
  const structureBoost = structure === "drop"
    ? 1.0
    : structure === "build" || structure === "buildup"
      ? 0.82
      : structure === "breakdown"
        ? 0.45
        : structure === "intro"
          ? 0.4
          : 0.6;
  const bpm = Number(semantic.bpm || 0);
  const motionRate = bpm > 0
    ? (bpm / 60) * (0.45 + scene.speed_multiplier * 0.35) * motionScale * sectionMotionMultiplier
    : scene.speed_multiplier * motionScale * sectionMotionMultiplier;
  const sectionStart = Number(showSection?.start_seconds ?? 0);
  const sectionEnd = Number(showSection?.end_seconds ?? Math.max(playbackSeconds, 1));
  const sectionSpan = Math.max(0.001, sectionEnd - sectionStart);
  const sectionProgress = clamp((playbackSeconds - sectionStart) / sectionSpan, 0, 1);
  if (showSection) {
    showSection.__sectionProgress = sectionProgress;
    showSection.__beatPulse = beatPulse;
    showSection.__energy = energy;
  }
  const pulseMix = clamp(
    0.25
      + (scene.pulse * 0.24)
      + (energy * 0.36)
      + (beatPulse * 0.34)
      + (structureBoost * 0.18)
      + (colorDrive * 0.12)
      + (semantic.downbeat ? 0.16 : 0),
    0.12,
    1.45,
  );
  const strobeBudget = clamp(Number(director.strobe_budget_hz || 0) / 12, 0, 1);
  const strobeLevel = modulatedStrobeLevel(showSection, scene.strobe ?? 0);
  const dropTransitionHot = (structure === "drop" || showSection?.fixture_mode === "peak_return")
    && sectionProgress <= 0.18;
  const dropEnvelope = dropSectionEnvelope(structure, showSection?.fixture_mode, sectionProgress, beatPhase, beatPulse);
  const strobeActive = (structure === "drop" || showSection?.fixture_mode === "peak_return")
    && strobeLevel > 0.12
    && strobeBudget > 0.1
    && (beatPulse > 0.74 || dropTransitionHot || (dropEnvelope.accent >= 1 && beatPulse > 0.45));

  return {
    scene,
    section: showSection,
    energy,
    beatPhase,
    beatPulse,
    beatConfidence,
    harmonicRatio,
    percussiveRatio,
    tonalStability,
    harmonicChange,
    pitchSalience,
    pitchHeight,
    timbralHarshness,
    melodicSmoothness,
    laserAggression,
    colorDrive,
    structure,
    motionStyle: movementStyle,
    motionRate,
    motionPhase: timeSeconds * motionRate,
    pulseMix,
    sectionProgress,
    strobeLevel,
    strobeActive,
    dropTransitionHot,
    dropIntensityEnvelope: dropEnvelope.intensity,
    dropAccentGate: dropEnvelope.accent,
  };
}

function selectedFixture() {
  return appState.fixtures.find((fixture) => fixture.id === appState.selectedFixtureId) || null;
}

function updateFixtureLocal(id, changes) {
  const fixture = appState.fixtures.find((item) => item.id === id);
  if (!fixture) {
    return;
  }
  Object.assign(fixture, changes);
}

function updateMetrics() {
  qs("fixture-count").textContent = String(appState.fixtures.length);
  qs("master-intensity").value = String(appState.masterIntensity);
  qs("master-speed").value = String(appState.masterSpeed);
  qs("master-intensity-value").textContent = `${Math.round(appState.masterIntensity * 100)}%`;
  qs("master-speed-value").textContent = `${appState.masterSpeed.toFixed(2)}x`;
  qs("blackout-toggle").classList.toggle("active", appState.blackout);
  qs("blackout-toggle").textContent = appState.blackout ? "Blackout On" : "Blackout Off";
}

function updateRuntimeSummary() {
  const runtimeScene = appState.runtimeSnapshot?.active_scene_id || "idle";
  qs("runtime-scene").textContent = runtimeScene;

  const localScene = sceneById(appState.sceneId);
  const parts = [
    `Mock scene: ${localScene.label}`,
    `Runtime scene: ${runtimeScene}`,
    `Blackout: ${appState.blackout ? "yes" : "no"}`,
  ];

  const bpm = appState.runtimeSnapshot?.semantic_frame?.bpm;
  if (typeof bpm === "number" && bpm > 0) {
    parts.push(`BPM ${round(bpm, 1)}`);
  }

  const hardwareWarnings = Array.isArray(appState.playback?.hardware_warnings)
    ? appState.playback.hardware_warnings
    : [];
  if (hardwareWarnings.length > 0) {
    parts.push(`Hardware warning: ${hardwareWarnings[0]}`);
  }

  qs("runtime-summary").textContent = parts.join(" · ");
}

function renderSceneBank() {
  elements.sceneBank.innerHTML = "";
  appState.catalog.scene_templates.forEach((scene) => {
    const button = document.createElement("button");
    const runtimeActive = appState.runtimeSnapshot?.active_scene_id === scene.scene_id;
    button.className = `scene-button${scene.scene_id === appState.sceneId ? " active" : ""}${runtimeActive ? " runtime" : ""}`;
    button.innerHTML = `
      <strong>${scene.label}</strong>
      <span>${scene.palette.join(" · ")}</span>
      ${runtimeActive ? "<small>Runtime live</small>" : ""}
    `;
    button.addEventListener("click", async () => {
      const state = await api("/api/mock/scene", {
        method: "POST",
        body: { scene_id: scene.scene_id },
      });
      applyMockState(state);
      renderSceneBank();
      updateMetrics();
      updateRuntimeSummary();
      await refreshUniverseSnapshot();
    });
    elements.sceneBank.appendChild(button);
  });
}

function renderFixtureLibrary() {
  elements.fixtureLibrary.innerHTML = "";
  appState.catalog.fixture_templates.forEach((template) => {
    const button = document.createElement("button");
    button.className = "fixture-template";
    button.innerHTML = `<strong>${template.label}</strong><span>${template.description}</span>`;
    button.addEventListener("click", async () => {
      const response = await api("/api/mock/fixtures", {
        method: "POST",
        body: { template_slug: template.slug },
      });
      applyMockState(response.state);
      appState.selectedFixtureId = response.fixture.id;
      renderFixtureList();
      renderInspector();
      updateMetrics();
      await refreshUniverseSnapshot();
    });
    elements.fixtureLibrary.appendChild(button);
  });
}

function renderFixtureList() {
  elements.fixtureList.innerHTML = "";
  appState.fixtures.forEach((fixture) => {
    const row = document.createElement("div");
    row.className = `fixture-row${fixture.id === appState.selectedFixtureId ? " selected" : ""}`;
    row.innerHTML = `
      <div>
        <strong>${fixture.label}</strong>
        <p class="fixture-meta">${fixture.type} · U${fixture.universe} · ${fixture.address}</p>
      </div>
      <div class="actions">
        <button type="button" data-action="select">Edit</button>
        <button type="button" data-action="remove">Drop</button>
      </div>
    `;
    row.querySelector('[data-action="select"]').addEventListener("click", () => {
      appState.selectedFixtureId = fixture.id;
      renderFixtureList();
      renderInspector();
    });
    row.querySelector('[data-action="remove"]').addEventListener("click", async () => {
      const response = await api(`/api/mock/fixtures/${fixture.id}`, { method: "DELETE" });
      applyMockState(response.state);
      renderFixtureList();
      renderInspector();
      updateMetrics();
      await refreshUniverseSnapshot();
    });
    elements.fixtureList.appendChild(row);
  });
}

function fieldMarkup({ label, key, type, min, max, step, value }) {
  const attrs = [
    `data-key="${key}"`,
    `type="${type}"`,
    `value="${value}"`,
  ];
  if (min !== undefined) attrs.push(`min="${min}"`);
  if (max !== undefined) attrs.push(`max="${max}"`);
  if (step !== undefined) attrs.push(`step="${step}"`);
  return `
    <div class="field">
      <label for="field-${key}">${label}</label>
      <input id="field-${key}" ${attrs.join(" ")} />
    </div>
  `;
}

function scheduleFixturePatch(fixtureId, changes, delay = 140) {
  const pending = fixturePatchTimers.get(fixtureId);
  if (pending) {
    pending.changes = { ...pending.changes, ...changes };
    window.clearTimeout(pending.timerId);
  }

  const timerId = window.setTimeout(async () => {
    const request = fixturePatchTimers.get(fixtureId);
    fixturePatchTimers.delete(fixtureId);
    if (!request) {
      return;
    }

    const response = await api(`/api/mock/fixtures/${fixtureId}`, {
      method: "PATCH",
      body: { changes: request.changes },
    });
    applyMockState(response.state);
    renderFixtureList();
    renderInspector();
    updateMetrics();
    await refreshUniverseSnapshot();
  }, delay);

  fixturePatchTimers.set(fixtureId, { changes: { ...(pending?.changes || {}), ...changes }, timerId });
}

function renderInspector() {
  const fixture = selectedFixture();
  if (!fixture) {
    elements.fixtureInspector.className = "inspector-empty";
    elements.fixtureInspector.textContent = "Select a fixture to edit its mock parameters.";
    return;
  }

  const commonFields = [
    fieldMarkup({ label: "Label", key: "label", type: "text", value: fixture.label }),
    fieldMarkup({ label: "Color", key: "color", type: "color", value: fixture.color }),
    fieldMarkup({ label: "Intensity", key: "intensity", type: "range", min: 0, max: 1, step: 0.01, value: fixture.intensity }),
    fieldMarkup({ label: "Rig X", key: "x", type: "range", min: 0.05, max: 0.95, step: 0.01, value: fixture.x }),
    fieldMarkup({ label: "Rig Y", key: "y", type: "range", min: 0.05, max: 0.60, step: 0.01, value: fixture.y }),
    fieldMarkup({ label: "Universe", key: "universe", type: "number", min: 1, max: 32, step: 1, value: fixture.universe }),
    fieldMarkup({ label: "Address", key: "address", type: "number", min: 1, max: 512, step: 1, value: fixture.address }),
  ];

  const typeFields = [];
  if (fixture.type === "laser") {
    typeFields.push(
      fieldMarkup({ label: "Spread", key: "spread", type: "range", min: 0.05, max: 0.55, step: 0.01, value: fixture.spread }),
      fieldMarkup({ label: "Beam Count", key: "beam_count", type: "number", min: 1, max: 9, step: 1, value: fixture.beam_count }),
      fieldMarkup({ label: "Swing", key: "swing", type: "range", min: 0, max: 1, step: 0.01, value: fixture.swing }),
    );
  } else if (fixture.type === "moving_head") {
    typeFields.push(
      fieldMarkup({ label: "Beam Width", key: "beam_width", type: "range", min: 0.04, max: 0.25, step: 0.01, value: fixture.beam_width }),
      fieldMarkup({ label: "Pan", key: "pan", type: "range", min: -1, max: 1, step: 0.01, value: fixture.pan }),
      fieldMarkup({ label: "Tilt", key: "tilt", type: "range", min: 0, max: 1, step: 0.01, value: fixture.tilt }),
      fieldMarkup({ label: "Pan Range", key: "pan_range", type: "range", min: 0, max: 1, step: 0.01, value: fixture.pan_range }),
      fieldMarkup({ label: "Tilt Range", key: "tilt_range", type: "range", min: 0, max: 1, step: 0.01, value: fixture.tilt_range }),
    );
  } else if (fixture.type === "wash") {
    typeFields.push(
      fieldMarkup({ label: "Radius", key: "radius", type: "range", min: 0.08, max: 0.4, step: 0.01, value: fixture.radius }),
    );
  } else if (fixture.type === "led_bar") {
    typeFields.push(
      fieldMarkup({ label: "Width", key: "width", type: "range", min: 0.08, max: 0.35, step: 0.01, value: fixture.width }),
      fieldMarkup({ label: "Pixel Count", key: "pixel_count", type: "number", min: 2, max: 16, step: 1, value: fixture.pixel_count }),
    );
  }

  elements.fixtureInspector.className = "inspector-grid";
  elements.fixtureInspector.innerHTML = `
    <div class="subhead">
      <h3>${fixture.label}</h3>
      <p>${safeText(fixture.type)} fixture · drag it on the stage to repatch quickly</p>
    </div>
    ${[...commonFields, ...typeFields].join("")}
    <button type="button" class="danger" id="duplicate-fixture">Duplicate Fixture</button>
  `;

  elements.fixtureInspector.querySelectorAll("input").forEach((input) => {
    const eventName = input.type === "range" || input.type === "color" ? "input" : "change";
    input.addEventListener(eventName, (event) => {
      const target = event.currentTarget;
      const key = target.dataset.key;
      let value = target.value;
      if (target.type === "number" || target.type === "range") {
        value = Number(value);
      }
      updateFixtureLocal(fixture.id, { [key]: value });
      renderFixtureList();
      scheduleFixturePatch(fixture.id, { [key]: value });
    });
  });

  elements.fixtureInspector.querySelector("#duplicate-fixture").addEventListener("click", async () => {
    const response = await api(`/api/mock/fixtures/${fixture.id}/duplicate`, { method: "POST" });
    applyMockState(response.state);
    appState.selectedFixtureId = response.fixture.id;
    renderFixtureList();
    renderInspector();
    updateMetrics();
    await refreshUniverseSnapshot();
  });
}

function fixtureOutput(fixture, visual) {
  const phase = (visual.motionPhase * appState.masterSpeed) + fixture.phaseOffset;
  const section = visual.section;
  const fixtureEnabled = fixture.type === "laser"
    ? section?.laser_enabled !== false
    : fixture.type === "moving_head"
      ? section?.movers_enabled !== false
      : fixture.type === "wash"
        ? section?.washes_enabled !== false
        : section?.leds_enabled !== false;
  const baseIntensity = fixture.intensity
    * appState.masterIntensity
    * (0.24 + visual.pulseMix * 0.76)
    * (0.5 + visual.energy * 0.7);
  const intensityBoost = visual.strobeActive ? 1.22 : 1;
  let sectionGate = 1;
  let motionGate = 1;
  const fixtureMode = String(section?.fixture_mode || "");
  if (fixtureMode === "intro") {
    sectionGate *= 0.45;
    motionGate *= 0.55;
  } else if (fixtureMode === "breakdown") {
    sectionGate *= fixture.type === "wash" || fixture.type === "led_bar" ? 0.55 : 0.12;
    motionGate *= 0.3;
  } else if (fixtureMode === "rebuild") {
    sectionGate *= 0.18 + (visual.sectionProgress * 0.82);
    motionGate *= 0.7 + (visual.sectionProgress * 0.7);
  } else if (fixtureMode === "peak_return") {
    sectionGate *= fixture.type === "wash"
      ? 0.4 + (visual.beatPulse * 0.8)
      : visual.beatPulse > 0.18 || visual.structure === "drop"
        ? 1
        : 0.15;
    sectionGate *= visual.dropIntensityEnvelope;
    motionGate *= 1.15;
  } else if (fixtureMode === "outro") {
    sectionGate *= 0.28;
    motionGate *= 0.45;
  }
  const intensity = appState.blackout || !fixtureEnabled ? 0 : clamp(baseIntensity * intensityBoost * sectionGate, 0, 1);
  const color = fixture.color;

  if (fixture.type === "laser") {
    const dropMode = fixtureMode === "peak_return" || visual.structure === "drop";
    const rebuildMode = fixtureMode === "rebuild" || visual.structure === "build";
    const laserPattern = String(section?.laser_pattern || "fan");
    const laserVariant = sectionVariant(section, "laser_variant");
    const laserExpression = sectionVariant(section, "laser_expression");
    const strobeRate = dropMode
      ? (3.2 + (visual.strobeLevel * 9) + (visual.dropTransitionHot ? 4.2 : 0)) * Number(laserVariant.gate_sharpness || 1)
      : 2.2 + visual.strobeLevel * 6;
    const strobeGate = visual.strobeActive
      ? (triangleWave(phase * strobeRate) > (visual.dropTransitionHot ? 0.62 : 0.45) ? 1 : 0)
      : dropMode
        ? ((triangleWave(phase * (visual.dropTransitionHot ? 1.8 : 0.9)) > 0.14 ? 1 : 0.08) * visual.dropAccentGate)
        : 1;
    const verticalSweep = dropMode
      ? Math.sin(phase * 1.7) * 0.42 + Math.cos(phase * 3.4) * 0.18 + (visual.dropTransitionHot ? Math.sin(phase * 5.2) * 0.16 : 0)
      : rebuildMode
        ? Math.sin(phase * 0.8) * 0.26
        : Math.sin(phase * 0.45) * 0.12;
    const rotation = dropMode
      ? Math.sin(phase * 0.92) * 0.9
      : rebuildMode
        ? Math.sin(phase * 0.55) * 0.35
        : Math.sin(phase * 0.22) * 0.12;
    const beamCount = dropMode
      ? Number(fixture.beam_count) + (visual.beatPulse > 0.72 ? 2 : 0) + (visual.dropTransitionHot ? 2 : 0)
      : Number(fixture.beam_count);
    const patternFamily = laserPatternFamily(laserPattern);
    const patternSpread = patternFamily === "burst"
      ? 2.05
      : patternFamily === "vertical"
        ? 0.62
        : patternFamily === "tunnel"
          ? 1.15
          : patternFamily === "scan"
            ? 0.36
            : 1.0;
    const patternBeamCount = patternFamily === "scan"
      ? Math.min(2, beamCount)
      : patternFamily === "tunnel"
        ? Math.max(6, beamCount)
        : patternFamily === "burst"
          ? Math.max(beamCount, 7)
          : beamCount;
    const variantBeamCount = clamp(Math.round(patternBeamCount * Number(laserVariant.beam_density || 1)), 1, 10);
    const patternRotation = patternFamily === "tunnel"
      ? rotation + Math.sin(phase * 1.4) * 1.2
      : patternFamily === "vertical"
        ? rotation * 0.2
        : patternFamily === "scan"
          ? rotation * 0.12
          : rotation;
    const variantRotation = patternRotation * Number(laserVariant.rotation_bias || 1);
    const patternVertical = patternFamily === "vertical"
      ? verticalSweep + Math.sin(phase * 2.4) * 0.34
      : patternFamily === "scan"
        ? verticalSweep * 0.2
        : verticalSweep;
    const variantVertical = patternVertical * Number(laserVariant.vertical_bias || 1);
    const patternSweep = patternFamily === "scan"
      ? Math.sin(phase * 4.2 * Number(laserVariant.sweep_rate || 1)) * fixture.swing * 0.55
      : patternFamily === "tunnel"
        ? Math.sin(phase * 1.2 * Number(laserVariant.sweep_rate || 1)) * fixture.swing * 0.18
        : patternFamily === "vertical"
          ? Math.sin(phase * 0.55 * Number(laserVariant.sweep_rate || 1)) * fixture.swing * 0.14
          : Math.sin(phase * (dropMode ? (visual.dropTransitionHot ? 4.4 : 2.8) : 1.1) * Number(laserVariant.sweep_rate || 1)) * fixture.swing * (0.45 + visual.energy * 1.1) * motionGate;
    const patternIntensity = patternFamily === "burst"
      ? intensity * (0.78 + visual.beatPulse * 0.35 + (visual.dropTransitionHot ? 0.18 : 0))
      : patternFamily === "scan"
        ? intensity * 0.72
        : intensity * strobeGate;
    const expressionGeometry = safeText(laserExpression.geometry_family, "fan");
    const geometrySpread = expressionGeometry === "grouped"
      ? 0.82
      : expressionGeometry === "tunnel"
        ? 0.62
        : expressionGeometry === "rake"
          ? 0.72
          : expressionGeometry === "sky"
            ? 1.15
            : 1;
    const targetBias = laserDynamicTargetBias(safeText(laserExpression.target_bias, "mid_air"), visual, dropMode);
    const targetYBias = targetBias === "crowd"
      ? 0.16 + Number(laserExpression.crowd_bias || 0) * 0.2
      : targetBias === "ceiling"
        ? -0.2 - Number(laserExpression.ceiling_bias || 0) * 0.18
        : -0.02;
    const beamColor = laserBeamColor(color, laserExpression, { phase, intensity: patternIntensity }, visual);
    const melodicSweepBias = 0.72 + visual.melodicSmoothness * 0.45;
    const aggressionSweepBias = 0.75 + visual.laserAggression * 0.5;
    const expressionTargetBias = targetBias === "crowd"
      ? targetYBias + visual.timbralHarshness * 0.05
      : targetBias === "ceiling"
        ? targetYBias - visual.melodicSmoothness * 0.08
        : targetYBias - visual.melodicSmoothness * 0.03 + visual.laserAggression * 0.02;
    const curveDepth = expressionGeometry === "sky"
      ? 0.22 + visual.melodicSmoothness * 0.18
      : expressionGeometry === "helix"
        ? 0.18 + visual.colorDrive * 0.16
        : expressionGeometry === "lattice"
          ? 0.12 + visual.harmonicChange * 0.12
          : expressionGeometry === "grouped"
            ? 0.05
            : 0.08 + visual.pitchSalience * 0.08;
    return {
      type: "laser",
      color: beamColor,
      intensity: patternIntensity * clamp(Number(laserVariant.gate_sharpness || 1), 0.55, 1.75),
      sweep: patternSweep * Number(laserExpression.x_amplitude || 1) * aggressionSweepBias,
      spread: fixture.spread * (dropMode ? 1.85 : rebuildMode ? 1.15 : 0.95) * patternSpread * geometrySpread * Number(laserVariant.spread_scale || 1),
      beamCount: clamp(Math.round(variantBeamCount * Number(laserExpression.sweep_density || 1)), 1, 12),
      shimmer: visual.beatPulse,
      verticalSweep: variantVertical * Number(laserExpression.y_amplitude || 1) * melodicSweepBias,
      rotation: variantRotation * Number(laserExpression.rotation_rate || 1),
      dropMode,
      pattern: laserPattern,
      variantLabel: safeText(laserVariant.label, ""),
      expressionLabel: safeText(laserExpression.label, ""),
      geometryFamily: expressionGeometry,
      targetYBias: expressionTargetBias,
      mirror: Boolean(laserExpression.mirror),
      curveDepth,
      phase,
    };
  }

  if (fixture.type === "moving_head") {
    const motionBias = visual.motionStyle === "sparse" ? 0.55 : visual.motionStyle === "aggressive" ? 1.25 : 1;
    const moverPattern = String(section?.mover_pattern || "drift");
    const moverVariant = sectionVariant(section, "mover_variant");
    const moverPhase = phase * Number(moverVariant.phase_scale || 1);
    const moverFamily = moverPatternFamily(moverPattern);
    const shapePan = moverFamily === "shape"
      ? Math.sin(moverPhase * 0.9) * Math.cos(moverPhase * 0.46)
      : moverFamily === "cross"
        ? Math.sign(Math.sin(moverPhase * 1.15)) * 0.9
        : moverFamily === "hits"
          ? (visual.beatPulse > 0.45 + Number(moverVariant.hit_bias || 0) * 0.2 ? Math.sign(Math.sin(moverPhase * 2.2)) : 0)
          : moverFamily === "hold"
            ? 0
            : Math.sin(moverPhase);
    const shapeTilt = moverFamily === "shape"
      ? Math.cos(moverPhase * 0.7)
      : moverFamily === "rise"
        ? (-0.5 + visual.sectionProgress * 1.5)
        : moverFamily === "hits"
          ? (visual.beatPulse > 0.45 + Number(moverVariant.hit_bias || 0) * 0.2 ? Math.cos(moverPhase * 2.4) : -0.1)
          : moverFamily === "hold"
            ? 0
            : Math.cos(moverPhase * 0.82);
    return {
      type: "moving_head",
      color,
      intensity,
      pan: fixture.pan + shapePan * fixture.pan_range * motionBias * motionGate * Number(moverVariant.pan_scale || 1),
      tilt: fixture.tilt + shapeTilt * fixture.tilt_range * motionBias * motionGate * Number(moverVariant.tilt_scale || 1),
      beamWidth: fixture.beam_width * (moverFamily === "hits" ? 0.78 + Number(moverVariant.hit_bias || 0) * 0.16 : 0.9 + visual.beatPulse * 0.25) * Number(moverVariant.beam_scale || 1),
      pattern: moverPattern,
      variantLabel: safeText(moverVariant.label, ""),
      phase,
    };
  }

  if (fixture.type === "wash") {
    const washPattern = String(section?.wash_pattern || "ambient");
    const washVariant = sectionVariant(section, "wash_variant");
    const washFamily = washPatternFamily(washPattern);
    const washRadius = washFamily === "punch"
      ? fixture.radius * (0.72 + visual.beatPulse * 0.55)
      : washFamily === "bloom"
        ? fixture.radius * (0.68 + visual.sectionProgress * 0.5 + visual.pulseMix * 0.22)
        : washFamily === "fade"
          ? fixture.radius * 0.78
          : washFamily === "breath"
            ? fixture.radius * (0.86 + Math.sin(phase * 0.45) * 0.16)
            : fixture.radius * (0.82 + visual.pulseMix * 0.34 + visual.beatPulse * 0.12);
    const washIntensity = washFamily === "fade"
      ? intensity * (1 - visual.sectionProgress * (0.35 + Number(washVariant.fade_bias || 0) * 0.45))
      : washFamily === "punch"
        ? intensity * (0.3 + visual.beatPulse * (0.55 + Number(washVariant.pulse_depth || 1) * 0.4))
        : intensity * (0.75 + Number(washVariant.pulse_depth || 1) * 0.25);
    return {
      type: "wash",
      color,
      intensity: washIntensity,
      radius: washRadius * Number(washVariant.radius_scale || 1),
      pattern: washPattern,
      variantLabel: safeText(washVariant.label, ""),
      phase,
    };
  }

  const ledPattern = String(section?.led_pattern || "pulse");
  const ledVariant = sectionVariant(section, "led_variant");
  const ledFamily = ledPatternFamily(ledPattern);
  const ledChase = ledFamily === "chase"
    ? (visual.beatPhase + ((Math.sin(phase * 1.2 * Number(ledVariant.chase_rate || 1)) + 1) * 0.22)) % 1
    : ledFamily === "sparkle"
      ? ((Math.sin(phase * 0.35 * Number(ledVariant.chase_rate || 1)) + 1) * 0.5)
      : ledFamily === "ramp"
        ? visual.sectionProgress
        : ledFamily === "fade"
          ? 0.5
          : (visual.beatPhase + ((Math.sin(phase * 0.7 * Number(ledVariant.chase_rate || 1)) + 1) * 0.15)) % 1;
  return {
    type: "led_bar",
    color,
    intensity: intensity * Number(ledVariant.glow_bias || 1),
    width: fixture.width,
    pixelCount: clamp(Math.round(Number(fixture.pixel_count) * Number(ledVariant.density || 1)), 2, 20),
    chase: ledChase,
    pattern: ledPattern,
    variantLabel: safeText(ledVariant.label, ""),
    phase,
  };
}

function renderFixtureActivity(visual, fixtureOutputs) {
  if (!elements.fixtureActivity) {
    return;
  }
  if (fixtureOutputs.length === 0) {
    elements.fixtureActivity.textContent = "Add fixtures to see live patterns and behavior here.";
    return;
  }

  const rows = fixtureOutputs.map(({ fixture, output }) => {
    const activity = describeFixtureActivity(fixture, output, visual);
    return {
      key: `${fixture.id}|${activity.patternLabel}|${activity.behavior}|${activity.intensityText}|${activity.sectionLabel}|${activity.muted}`,
      html: `
        <div class="fixture-activity-row">
          <strong>${fixture.label}</strong>
          <span>${activity.typeLabel} · ${activity.patternLabel} · ${activity.sectionLabel}</span>
          <small>${activity.muted ? "Muted" : activity.behavior} · ${activity.intensityText}</small>
        </div>
      `,
    };
  });

  const signature = rows.map((row) => row.key).join("||");
  const now = performance.now();
  if (signature === fixtureActivitySignature && (now - fixtureActivityRenderedAt) < 160) {
    return;
  }

  fixtureActivitySignature = signature;
  fixtureActivityRenderedAt = now;
  elements.fixtureActivity.innerHTML = rows.map((row) => row.html).join("");
}

function drawBackground(ctx, width, height, visual) {
  const sky = ctx.createLinearGradient(0, 0, 0, height);
  sky.addColorStop(0, "rgba(1, 3, 6, 0.98)");
  sky.addColorStop(0.58, "rgba(4, 7, 12, 0.98)");
  sky.addColorStop(1, "rgba(0, 0, 0, 1)");
  ctx.fillStyle = sky;
  ctx.fillRect(0, 0, width, height);

  ctx.strokeStyle = "rgba(255,255,255,0.08)";
  ctx.lineWidth = 1;
  for (let i = 1; i < 9; i += 1) {
    const y = (height * i) / 10;
    ctx.beginPath();
    ctx.moveTo(40, y);
    ctx.lineTo(width - 40, y);
    ctx.stroke();
  }

  for (let i = 0; i < 12; i += 1) {
    const x = 80 + ((width - 160) / 11) * i;
    ctx.beginPath();
    ctx.moveTo(x, 110);
    ctx.lineTo(x, height - 90);
    ctx.strokeStyle = "rgba(255,255,255,0.035)";
    ctx.stroke();
  }

  ctx.fillStyle = "rgba(255,255,255,0.06)";
  ctx.fillRect(60, 72, width - 120, 8);
  ctx.fillRect(80, height - 104, width - 160, 6);

  ctx.beginPath();
  ctx.ellipse(width / 2, height - 76, width * 0.42, 70, 0, 0, Math.PI * 2);
  ctx.fillStyle = `rgba(255, 255, 255, ${0.03 + visual.beatPulse * 0.05})`;
  ctx.fill();

  if (visual.structure === "drop" || visual.structure === "buildup") {
    const atmosphere = ctx.createRadialGradient(width / 2, height * 0.72, 20, width / 2, height * 0.72, width * 0.45);
    atmosphere.addColorStop(0, `rgba(255, 255, 255, ${0.02 + visual.energy * 0.04})`);
    atmosphere.addColorStop(1, "rgba(255, 255, 255, 0)");
    ctx.fillStyle = atmosphere;
    ctx.fillRect(0, 0, width, height);
  }

  ctx.fillStyle = "rgba(255,255,255,0.6)";
  ctx.font = "600 14px Trebuchet MS";
  ctx.fillText(`Patch surface · ${visual.scene.label}`, 82, 102);
}

function drawLaser(ctx, fixture, output, width, height) {
  if (output.intensity <= 0.01) {
    return;
  }
  const originX = fixture.x * width;
  const originY = fixture.y * height;
  const count = Math.max(1, output.beamCount);
  const rotation = output.rotation || 0;
  const geometryFamily = safeText(output.geometryFamily, "fan");
  for (let index = 0; index < count; index += 1) {
    const centered = count === 1 ? 0 : (index / (count - 1)) - 0.5;
    const mirrored = output.mirror && centered > 0 ? -centered : centered;
    const rotationOffset = mirrored * rotation * width * 0.12;
    const spread = centered * output.spread * width;
    const sweep = output.sweep * width * 0.22;
    const verticalSpread = centered * (output.dropMode ? 120 : 48);
    const targetX = clamp(originX + spread + sweep + rotationOffset, 60, width - 60);
    const targetY = clamp(
      height - 110 - Math.abs(centered) * 28 - verticalSpread - (output.verticalSweep || 0) * height * 0.28 + (output.targetYBias || 0) * height,
      90,
      height - 82,
    );
    const familyCurve = geometryFamily === "sky"
      ? -height * (output.curveDepth || 0.12)
      : geometryFamily === "helix"
        ? Math.sin(output.phase * 1.8 + centered * Math.PI) * height * (output.curveDepth || 0.12)
        : geometryFamily === "lattice"
          ? centered * height * (output.curveDepth || 0.1)
          : geometryFamily === "grouped"
            ? 0
            : geometryFamily === "burst"
              ? -Math.abs(centered) * height * (output.curveDepth || 0.08)
              : -height * (output.curveDepth || 0.08) * 0.4;
    const controlX = clamp(
      (originX + targetX) / 2
        + rotationOffset * 0.4
        + (geometryFamily === "lattice" ? centered * width * 0.08 : 0)
        + (geometryFamily === "helix" ? Math.cos(output.phase * 2.1 + centered * 4) * width * 0.04 : 0),
      40,
      width - 40,
    );
    const controlY = clamp(
      ((originY + targetY) / 2) + familyCurve,
      40,
      height - 60,
    );
    const beam = ctx.createLinearGradient(originX, originY, targetX, targetY);
    beam.addColorStop(0, rgba(output.color, 0));
    beam.addColorStop(0.12, rgba(output.color, output.intensity * (0.18 + output.shimmer * 0.14)));
    beam.addColorStop(1, rgba(output.color, output.intensity * (0.74 + output.shimmer * 0.18)));
    ctx.strokeStyle = beam;
    ctx.lineWidth = output.dropMode ? 2.8 : 2.2;
    ctx.beginPath();
    ctx.moveTo(originX, originY);
    if (geometryFamily === "grouped") {
      ctx.lineTo(targetX, targetY);
    } else {
      ctx.quadraticCurveTo(controlX, controlY, targetX, targetY);
    }
    ctx.stroke();

    if (output.dropMode) {
      ctx.strokeStyle = rgba(output.color, output.intensity * 0.16);
      ctx.lineWidth = 6;
      ctx.beginPath();
      ctx.moveTo(originX, originY);
      if (geometryFamily === "grouped") {
        ctx.lineTo(targetX, targetY);
      } else {
        ctx.quadraticCurveTo(controlX, controlY, targetX, targetY);
      }
      ctx.stroke();
    }

    if (geometryFamily === "lattice" && Math.abs(centered) > 0.12) {
      const crossX = clamp(originX - spread + sweep - rotationOffset, 60, width - 60);
      const crossControlX = clamp((originX + crossX) / 2 - centered * width * 0.08, 40, width - 40);
      ctx.strokeStyle = rgba(output.color, output.intensity * 0.32);
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      ctx.moveTo(originX, originY);
      ctx.quadraticCurveTo(crossControlX, controlY, crossX, targetY);
      ctx.stroke();
    }

    ctx.beginPath();
    ctx.arc(targetX, targetY, 4 + output.intensity * 6, 0, Math.PI * 2);
    ctx.fillStyle = rgba(output.color, output.intensity * 0.3);
    ctx.fill();
  }
}

function drawMovingHead(ctx, fixture, output, width, height) {
  const originX = fixture.x * width;
  const originY = fixture.y * height;
  const targetX = clamp(originX + output.pan * width * 0.22, 80, width - 80);
  const targetY = clamp(originY + height * 0.25 + output.tilt * height * 0.35, 140, height - 100);
  const beamWidth = width * output.beamWidth;

  ctx.beginPath();
  ctx.moveTo(originX - 8, originY + 6);
  ctx.lineTo(originX + 8, originY + 6);
  ctx.lineTo(targetX + beamWidth, targetY);
  ctx.lineTo(targetX - beamWidth, targetY);
  ctx.closePath();
  const cone = ctx.createLinearGradient(originX, originY, targetX, targetY);
  cone.addColorStop(0, rgba(output.color, output.intensity * 0.1));
  cone.addColorStop(1, rgba(output.color, output.intensity * 0.42));
  ctx.fillStyle = cone;
  ctx.fill();

  ctx.beginPath();
  ctx.arc(targetX, targetY, 10 + output.intensity * 22, 0, Math.PI * 2);
  ctx.fillStyle = rgba(output.color, output.intensity * 0.26);
  ctx.fill();
}

function drawWash(ctx, fixture, output, width, height) {
  const centerX = fixture.x * width;
  const centerY = height - 100;
  const radius = output.radius * width;
  const gradient = ctx.createRadialGradient(centerX, centerY, 0, centerX, centerY, radius);
  gradient.addColorStop(0, rgba(output.color, output.intensity * 0.44));
  gradient.addColorStop(1, rgba(output.color, 0));
  ctx.fillStyle = gradient;
  ctx.beginPath();
  ctx.arc(centerX, centerY, radius, 0, Math.PI * 2);
  ctx.fill();
}

function drawLedBar(ctx, fixture, output, width, height) {
  const centerX = fixture.x * width;
  const y = fixture.y * height;
  const totalWidth = output.width * width;
  const pixelWidth = totalWidth / output.pixelCount;

  for (let index = 0; index < output.pixelCount; index += 1) {
    const x = centerX - totalWidth / 2 + index * pixelWidth;
    const chaseWindow = Math.abs(index / Math.max(output.pixelCount - 1, 1) - output.chase);
    const glow = clamp(1 - chaseWindow * 2.5, 0.18, 1) * output.intensity;
    ctx.fillStyle = rgba(output.color, glow);
    ctx.fillRect(x, y, pixelWidth - 4, 12);

    ctx.fillStyle = rgba(output.color, glow * 0.18);
    ctx.fillRect(x, y + 12, pixelWidth - 4, 36 + glow * 26);
  }
}

function drawFixtureBody(ctx, fixture, width, height) {
  const x = fixture.x * width;
  const y = fixture.y * height;
  const selected = fixture.id === appState.selectedFixtureId;
  ctx.fillStyle = selected ? "rgba(255, 255, 255, 0.96)" : "rgba(250, 248, 241, 0.85)";
  ctx.fillRect(x - 9, y - 9, 18, 18);
  ctx.strokeStyle = selected ? "rgba(248, 94, 0, 0.95)" : "rgba(0,0,0,0.35)";
  ctx.lineWidth = selected ? 2 : 1;
  ctx.strokeRect(x - 9, y - 9, 18, 18);

  if (selected) {
    ctx.beginPath();
    ctx.arc(x, y, 18, 0, Math.PI * 2);
    ctx.strokeStyle = "rgba(248, 94, 0, 0.35)";
    ctx.stroke();
  }

  ctx.fillStyle = "rgba(255,255,255,0.85)";
  ctx.font = "600 12px Trebuchet MS";
  ctx.fillText(fixture.label, x + 14, y + 4);
}

function renderStage(timeMillis) {
  const canvas = elements.stageCanvas;
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  const seconds = timeMillis / 1000;
  const visual = runtimeVisualState(seconds);
  const fixtureOutputs = appState.fixtures.map((fixture) => ({
    fixture,
    output: fixtureOutput(fixture, visual),
  }));

  drawBackground(ctx, width, height, visual);

  fixtureOutputs.forEach(({ fixture, output }) => {
    if (fixture.type === "laser") {
      drawLaser(ctx, fixture, output, width, height);
    } else if (fixture.type === "moving_head") {
      drawMovingHead(ctx, fixture, output, width, height);
    } else if (fixture.type === "wash") {
      drawWash(ctx, fixture, output, width, height);
    } else if (fixture.type === "led_bar") {
      drawLedBar(ctx, fixture, output, width, height);
    }
  });

  appState.fixtures.forEach((fixture) => drawFixtureBody(ctx, fixture, width, height));
  renderFixtureActivity(visual, fixtureOutputs);

  if (appState.selectedFixtureId) {
    ctx.fillStyle = "rgba(255,255,255,0.74)";
    ctx.font = "600 13px Trebuchet MS";
    ctx.fillText("Drag fixtures in the stage to change patch position", 78, height - 34);
  }

  window.requestAnimationFrame(renderStage);
}

function renderMonitor() {
  const snapshot = appState.universeSnapshot;
  if (!snapshot || snapshot.universes.length === 0) {
    elements.dmxMonitor.innerHTML = `
      <div class="monitor-empty">
        No active universes yet. Add a mock fixture to generate synthetic DMX output.
      </div>
    `;
    return;
  }

  const activeUniverse = snapshot.universes.find((entry) => entry.universe === appState.selectedUniverse)
    || snapshot.universes[0];
  appState.selectedUniverse = activeUniverse.universe;

  elements.dmxMonitor.innerHTML = `
    <div class="monitor-tabs">
      ${snapshot.universes.map((entry) => `
        <button type="button" class="monitor-tab${entry.universe === activeUniverse.universe ? " active" : ""}" data-universe="${entry.universe}">
          Universe ${entry.universe}
          <small>${entry.active_channel_count} ch</small>
        </button>
      `).join("")}
    </div>
    <div class="monitor-summary">
      <strong>${activeUniverse.fixtures.length} fixtures</strong>
      <span>Scene ${snapshot.scene_id} · ${Math.round(snapshot.master_intensity * 100)}% master</span>
    </div>
    <div class="monitor-channel-grid">
      ${activeUniverse.channels.map((channel) => `
        <div class="channel-cell">
          <small>CH ${channel.channel}</small>
          <strong>${channel.value}</strong>
          <span>${channel.fixture_label} · ${channel.label}</span>
        </div>
      `).join("")}
    </div>
    <div class="monitor-fixture-list">
      ${activeUniverse.fixtures.map((fixture) => `
        <div class="monitor-row">
          <div class="monitor-header">
            <div>
              <strong>${fixture.fixture_label}</strong>
              <p class="monitor-meta">U${activeUniverse.universe} · ${fixture.address} · ${fixture.type}</p>
            </div>
            <div>${Math.round(fixture.intensity * 100)}%</div>
          </div>
          <div class="channels">
            ${fixture.channels.map((channel) => `
              <div class="channel">
                <small>CH ${channel.channel}</small>
                <strong>${channel.value}</strong>
                <span>${channel.label}</span>
              </div>
            `).join("")}
          </div>
        </div>
      `).join("")}
    </div>
  `;

  elements.dmxMonitor.querySelectorAll(".monitor-tab").forEach((button) => {
    button.addEventListener("click", () => {
      appState.selectedUniverse = Number(button.dataset.universe);
      renderMonitor();
    });
  });
}

function canvasCoordinates(event) {
  const rect = elements.stageCanvas.getBoundingClientRect();
  const scaleX = elements.stageCanvas.width / rect.width;
  const scaleY = elements.stageCanvas.height / rect.height;
  return {
    x: (event.clientX - rect.left) * scaleX,
    y: (event.clientY - rect.top) * scaleY,
  };
}

function hitFixture(point) {
  const threshold = 18;
  for (let index = appState.fixtures.length - 1; index >= 0; index -= 1) {
    const fixture = appState.fixtures[index];
    const x = fixture.x * elements.stageCanvas.width;
    const y = fixture.y * elements.stageCanvas.height;
    if (Math.abs(point.x - x) <= threshold && Math.abs(point.y - y) <= threshold) {
      return fixture;
    }
  }
  return null;
}

function bindStageInteractions() {
  const stopDrag = async () => {
    if (!appState.dragFixtureId) {
      return;
    }
    const fixture = selectedFixture();
    const fixtureId = appState.dragFixtureId;
    appState.dragFixtureId = null;
    elements.stageCanvas.classList.remove("dragging");
    if (fixture && fixture.id === fixtureId) {
      scheduleFixturePatch(fixtureId, {
        x: fixture.x,
        y: fixture.y,
      }, 0);
    }
  };

  elements.stageCanvas.addEventListener("pointerdown", (event) => {
    const point = canvasCoordinates(event);
    const fixture = hitFixture(point);
    if (!fixture) {
      return;
    }
    appState.selectedFixtureId = fixture.id;
    appState.dragFixtureId = fixture.id;
    elements.stageCanvas.classList.add("dragging");
    renderFixtureList();
    renderInspector();
  });

  elements.stageCanvas.addEventListener("pointermove", (event) => {
    if (!appState.dragFixtureId) {
      return;
    }
    const point = canvasCoordinates(event);
    const nextX = clamp(point.x / elements.stageCanvas.width, 0.05, 0.95);
    const nextY = clamp(point.y / elements.stageCanvas.height, 0.05, 0.60);
    updateFixtureLocal(appState.dragFixtureId, { x: round(nextX, 3), y: round(nextY, 3) });
  });

  window.addEventListener("pointerup", () => {
    stopDrag().catch((error) => {
      console.error(error);
    });
  });
}

function queueMasterPatch(changes) {
  if (masterPatchTimer) {
    window.clearTimeout(masterPatchTimer.timerId);
    masterPatchTimer.changes = { ...masterPatchTimer.changes, ...changes };
  } else {
    masterPatchTimer = { changes: { ...changes }, timerId: null };
  }

  masterPatchTimer.timerId = window.setTimeout(async () => {
    const request = masterPatchTimer;
    masterPatchTimer = null;
    const state = await api("/api/mock/masters", {
      method: "POST",
      body: request.changes,
    });
    applyMockState(state);
    updateMetrics();
    updateRuntimeSummary();
    await refreshUniverseSnapshot();
  }, 140);
}

function bindControls() {
  qs("master-intensity").addEventListener("input", (event) => {
    appState.masterIntensity = Number(event.currentTarget.value);
    updateMetrics();
    queueMasterPatch({ master_intensity: appState.masterIntensity });
  });

  qs("master-speed").addEventListener("input", (event) => {
    appState.masterSpeed = Number(event.currentTarget.value);
    updateMetrics();
    queueMasterPatch({ master_speed: appState.masterSpeed });
  });

  qs("blackout-toggle").addEventListener("click", () => {
    appState.blackout = !appState.blackout;
    updateMetrics();
    updateRuntimeSummary();
    queueMasterPatch({ blackout: appState.blackout });
  });
}

function connectWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${window.location.host}/ws/live`);
  socket.addEventListener("open", () => {
    appState.wsStatus = "live";
    qs("ws-status").textContent = "live";
  });
  socket.addEventListener("message", (event) => {
    appState.runtimeSnapshot = JSON.parse(event.data);
    updateRuntimeSummary();
    renderSceneBank();
  });
  socket.addEventListener("close", () => {
    appState.wsStatus = "reconnecting";
    qs("ws-status").textContent = "reconnecting";
    window.setTimeout(connectWebSocket, 1500);
  });
}

function startUniversePolling() {
  if (universeRefreshTimer) {
    window.clearInterval(universeRefreshTimer);
  }
  universeRefreshTimer = window.setInterval(() => {
    refreshUniverseSnapshot().catch((error) => {
      console.error(error);
    });
  }, 1000);
}

function startPlaybackPolling() {
  playbackPollActive = true;
  if (playbackRefreshTimer) {
    window.clearTimeout(playbackRefreshTimer);
  }
  const poll = async () => {
    try {
      await refreshPlaybackState();
    } catch (error) {
      console.error(error);
    } finally {
      if (playbackPollActive) {
        playbackRefreshTimer = window.setTimeout(poll, PLAYBACK_POLL_MS);
      }
    }
  };
  playbackRefreshTimer = window.setTimeout(poll, PLAYBACK_POLL_MS);
}

async function boot() {
  elements.sceneBank = qs("scene-bank");
  elements.fixtureLibrary = qs("fixture-library");
  elements.fixtureList = qs("fixture-list");
  elements.fixtureInspector = qs("fixture-inspector");
  elements.dmxMonitor = qs("dmx-monitor");
  elements.stageCanvas = qs("stage-canvas");
  elements.playbackPanel = qs("playback-panel");
  elements.fixtureActivity = qs("fixture-activity");

  await loadCatalog();
  await loadMockState();
  await loadRuntimeSnapshot();
  await refreshUniverseSnapshot();
  await loadPlaybackState();

  bindControls();
  bindStageInteractions();
  renderSceneBank();
  renderFixtureLibrary();
  renderFixtureList();
  renderInspector();
  updateMetrics();
  updateRuntimeSummary();
  connectWebSocket();
  startUniversePolling();
  startPlaybackPolling();
  window.requestAnimationFrame(renderStage);
}

window.addEventListener("DOMContentLoaded", () => {
  boot().catch((error) => {
    console.error(error);
    qs("runtime-summary").textContent = "Failed to load mock visualizer.";
  });
});
