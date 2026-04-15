const appState = {
  catalog: null,
  fixtures: [],
  selectedFixtureId: null,
  sceneId: "intro_ambient",
  masterIntensity: 0.82,
  masterSpeed: 1.0,
  blackout: false,
  runtimeSnapshot: null,
  wsStatus: "connecting",
};

const elements = {};

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

function uid(prefix) {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
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
  const rgb = hexToRgb(hex);
  return `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${alpha})`;
}

async function loadCatalog() {
  const response = await fetch("/api/mock/catalog");
  if (!response.ok) {
    throw new Error("Failed to load mock catalog");
  }
  appState.catalog = await response.json();
}

async function loadRuntimeSnapshot() {
  try {
    const response = await fetch("/api/live/state");
    if (!response.ok) {
      return;
    }
    appState.runtimeSnapshot = await response.json();
    updateRuntimeSummary();
  } catch {
    // Runtime data is optional for the mock visualizer.
  }
}

function templateBySlug(slug) {
  return appState.catalog.fixture_templates.find((item) => item.slug === slug);
}

function sceneById(sceneId) {
  return appState.catalog.scene_templates.find((item) => item.scene_id === sceneId)
    || appState.catalog.scene_templates[0];
}

function createFixture(templateSlug, labelOverride = null) {
  const template = templateBySlug(templateSlug);
  if (!template) {
    return null;
  }

  const sameTypeCount = appState.fixtures.filter((fixture) => fixture.type === template.type).length;
  const defaults = structuredClone(template.defaults);
  defaults.x = clamp(defaults.x + sameTypeCount * 0.07, 0.08, 0.92);
  defaults.address = defaults.address + sameTypeCount * 20;

  return {
    id: uid(template.slug),
    templateSlug: template.slug,
    type: template.type,
    label: labelOverride || `${template.label} ${sameTypeCount + 1}`,
    ...defaults,
    phaseOffset: Math.random() * Math.PI * 2,
  };
}

function bootstrapDefaultRig() {
  appState.fixtures = appState.catalog.default_rig
    .map((entry) => createFixture(entry.template, entry.label))
    .filter(Boolean);
  appState.selectedFixtureId = appState.fixtures[0]?.id || null;
}

function selectedFixture() {
  return appState.fixtures.find((fixture) => fixture.id === appState.selectedFixtureId) || null;
}

function renderSceneBank() {
  elements.sceneBank.innerHTML = "";
  appState.catalog.scene_templates.forEach((scene) => {
    const button = document.createElement("button");
    button.className = `scene-button${scene.scene_id === appState.sceneId ? " active" : ""}`;
    button.innerHTML = `<strong>${scene.label}</strong><span>${scene.palette.join(" · ")}</span>`;
    button.addEventListener("click", () => {
      appState.sceneId = scene.scene_id;
      renderSceneBank();
      updateRuntimeSummary();
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
    button.addEventListener("click", () => {
      const fixture = createFixture(template.slug);
      if (!fixture) {
        return;
      }
      appState.fixtures.push(fixture);
      appState.selectedFixtureId = fixture.id;
      renderFixtureList();
      renderInspector();
      renderMonitor();
      updateMetrics();
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
    row.querySelector('[data-action="remove"]').addEventListener("click", () => {
      appState.fixtures = appState.fixtures.filter((item) => item.id !== fixture.id);
      if (appState.selectedFixtureId === fixture.id) {
        appState.selectedFixtureId = appState.fixtures[0]?.id || null;
      }
      renderFixtureList();
      renderInspector();
      renderMonitor();
      updateMetrics();
    });
    elements.fixtureList.appendChild(row);
  });
}

function updateFixture(id, key, value) {
  const fixture = appState.fixtures.find((item) => item.id === id);
  if (!fixture) {
    return;
  }
  fixture[key] = value;
  renderFixtureList();
  renderInspector();
  renderMonitor();
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
      <p>${safeText(fixture.type)} fixture</p>
    </div>
    ${[...commonFields, ...typeFields].join("")}
    <button type="button" class="danger" id="duplicate-fixture">Duplicate Fixture</button>
  `;

  elements.fixtureInspector.querySelectorAll("input").forEach((input) => {
    input.addEventListener("input", (event) => {
      const target = event.currentTarget;
      const key = target.dataset.key;
      let value = target.value;
      if (target.type === "number" || target.type === "range") {
        value = Number(value);
      }
      updateFixture(fixture.id, key, value);
    });
  });

  elements.fixtureInspector.querySelector("#duplicate-fixture").addEventListener("click", () => {
    const clone = structuredClone(fixture);
    clone.id = uid(fixture.templateSlug);
    clone.label = `${fixture.label} Copy`;
    clone.x = clamp(Number(fixture.x) + 0.05, 0.05, 0.95);
    clone.address = Number(fixture.address) + 10;
    appState.fixtures.push(clone);
    appState.selectedFixtureId = clone.id;
    renderFixtureList();
    renderInspector();
    renderMonitor();
    updateMetrics();
  });
}

function computeSceneMix(scene, timeSeconds) {
  return 0.55 + Math.sin(timeSeconds * scene.speed_multiplier * 2.0) * scene.pulse * 0.35;
}

function fixtureOutput(fixture, timeSeconds) {
  const scene = sceneById(appState.sceneId);
  const mix = computeSceneMix(scene, timeSeconds);
  const phase = timeSeconds * appState.masterSpeed * scene.speed_multiplier + fixture.phaseOffset;
  const baseIntensity = fixture.intensity * appState.masterIntensity * mix;
  const intensity = appState.blackout ? 0 : clamp(baseIntensity, 0, 1);
  const color = fixture.color;

  if (fixture.type === "laser") {
    return {
      type: "laser",
      color,
      intensity,
      sweep: Math.sin(phase) * fixture.swing,
      spread: fixture.spread,
      beamCount: Number(fixture.beam_count),
      channels: [
        ["Dim", Math.round(intensity * 255)],
        ["Color", Math.round((hexToRgb(color).g / 255) * 255)],
        ["Pattern", 160 + Math.round((Math.sin(phase) + 1) * 20)],
        ["Scan", Math.round((0.2 + fixture.swing * 0.8) * 255)],
      ],
    };
  }

  if (fixture.type === "moving_head") {
    return {
      type: "moving_head",
      color,
      intensity,
      pan: fixture.pan + Math.sin(phase) * fixture.pan_range,
      tilt: fixture.tilt + Math.cos(phase * 0.8) * fixture.tilt_range,
      beamWidth: fixture.beam_width,
      channels: [
        ["Dim", Math.round(intensity * 255)],
        ["Pan", Math.round(((Math.sin(phase) * 0.5) + 0.5) * 255)],
        ["Tilt", Math.round(((Math.cos(phase * 0.8) * 0.5) + 0.5) * 255)],
        ["Color", Math.round((hexToRgb(color).r / 255) * 255)],
      ],
    };
  }

  if (fixture.type === "wash") {
    return {
      type: "wash",
      color,
      intensity,
      radius: fixture.radius * (0.9 + mix * 0.2),
      channels: [
        ["Dim", Math.round(intensity * 255)],
        ["Red", hexToRgb(color).r],
        ["Green", hexToRgb(color).g],
        ["Blue", hexToRgb(color).b],
      ],
    };
  }

  return {
    type: "led_bar",
    color,
    intensity,
    width: fixture.width,
    pixelCount: Number(fixture.pixel_count),
    chase: (Math.sin(phase * 1.6) + 1) * 0.5,
    channels: [
      ["Dim", Math.round(intensity * 255)],
      ["Pixels", Math.round(clamp(fixture.pixel_count, 0, 16))],
      ["Chase", Math.round(((Math.sin(phase * 1.6) + 1) * 0.5) * 255)],
      ["Color", Math.round((hexToRgb(color).b / 255) * 255)],
    ],
  };
}

function drawBackground(ctx, width, height) {
  const sky = ctx.createLinearGradient(0, 0, 0, height);
  sky.addColorStop(0, "#09121f");
  sky.addColorStop(0.65, "#162335");
  sky.addColorStop(1, "#35261d");
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

  ctx.fillStyle = "rgba(255,255,255,0.06)";
  ctx.fillRect(60, 72, width - 120, 8);

  ctx.beginPath();
  ctx.ellipse(width / 2, height - 76, width * 0.42, 70, 0, 0, Math.PI * 2);
  ctx.fillStyle = "rgba(255, 214, 153, 0.12)";
  ctx.fill();
}

function drawLaser(ctx, fixture, output, width, height) {
  const originX = fixture.x * width;
  const originY = fixture.y * height;
  const count = Math.max(1, output.beamCount);
  for (let index = 0; index < count; index += 1) {
    const centered = count === 1 ? 0 : (index / (count - 1)) - 0.5;
    const spread = centered * output.spread * width;
    const sweep = output.sweep * width * 0.18;
    const targetX = clamp(originX + spread + sweep, 90, width - 90);
    const targetY = height - 92 - Math.abs(centered) * 40;
    const beam = ctx.createLinearGradient(originX, originY, targetX, targetY);
    beam.addColorStop(0, rgba(output.color, 0.0));
    beam.addColorStop(0.12, rgba(output.color, output.intensity * 0.22));
    beam.addColorStop(1, rgba(output.color, output.intensity * 0.85));
    ctx.strokeStyle = beam;
    ctx.lineWidth = 2.2;
    ctx.beginPath();
    ctx.moveTo(originX, originY);
    ctx.lineTo(targetX, targetY);
    ctx.stroke();

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
  ctx.fillStyle = "rgba(250, 248, 241, 0.85)";
  ctx.fillRect(x - 9, y - 9, 18, 18);
  ctx.strokeStyle = "rgba(0,0,0,0.35)";
  ctx.strokeRect(x - 9, y - 9, 18, 18);
}

function renderStage(timeMillis) {
  const canvas = elements.stageCanvas;
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  const seconds = timeMillis / 1000;

  drawBackground(ctx, width, height);

  appState.fixtures.forEach((fixture) => {
    const output = fixtureOutput(fixture, seconds);
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
  window.requestAnimationFrame(renderStage);
}

function renderMonitor() {
  elements.dmxMonitor.innerHTML = "";
  const now = performance.now() / 1000;

  appState.fixtures.forEach((fixture) => {
    const output = fixtureOutput(fixture, now);
    const row = document.createElement("div");
    row.className = "monitor-row";
    row.innerHTML = `
      <div class="monitor-header">
        <div>
          <strong>${fixture.label}</strong>
          <p class="monitor-meta">U${fixture.universe} · ${fixture.address} · ${fixture.type}</p>
        </div>
        <div>${Math.round(output.intensity * 100)}%</div>
      </div>
      <div class="channels">
        ${output.channels.map(([label, value]) => `
          <div class="channel">
            <small>${label}</small>
            <strong>${value}</strong>
          </div>
        `).join("")}
      </div>
    `;
    elements.dmxMonitor.appendChild(row);
  });
}

function updateMetrics() {
  qs("fixture-count").textContent = String(appState.fixtures.length);
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

  qs("runtime-summary").textContent = parts.join(" · ");
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
  });
  socket.addEventListener("close", () => {
    appState.wsStatus = "reconnecting";
    qs("ws-status").textContent = "reconnecting";
    window.setTimeout(connectWebSocket, 1500);
  });
}

function bindControls() {
  qs("master-intensity").addEventListener("input", (event) => {
    appState.masterIntensity = Number(event.currentTarget.value);
    updateMetrics();
    renderMonitor();
  });

  qs("master-speed").addEventListener("input", (event) => {
    appState.masterSpeed = Number(event.currentTarget.value);
    updateMetrics();
    renderMonitor();
  });

  qs("blackout-toggle").addEventListener("click", () => {
    appState.blackout = !appState.blackout;
    updateMetrics();
    updateRuntimeSummary();
    renderMonitor();
  });
}

async function boot() {
  elements.sceneBank = qs("scene-bank");
  elements.fixtureLibrary = qs("fixture-library");
  elements.fixtureList = qs("fixture-list");
  elements.fixtureInspector = qs("fixture-inspector");
  elements.dmxMonitor = qs("dmx-monitor");
  elements.stageCanvas = qs("stage-canvas");

  await loadCatalog();
  await loadRuntimeSnapshot();

  bootstrapDefaultRig();
  bindControls();
  renderSceneBank();
  renderFixtureLibrary();
  renderFixtureList();
  renderInspector();
  renderMonitor();
  updateMetrics();
  updateRuntimeSummary();
  connectWebSocket();
  window.requestAnimationFrame(renderStage);
}

window.addEventListener("DOMContentLoaded", () => {
  boot().catch((error) => {
    console.error(error);
    qs("runtime-summary").textContent = "Failed to load mock visualizer.";
  });
});
