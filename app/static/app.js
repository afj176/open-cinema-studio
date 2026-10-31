// Open Cinema Studio — Story → Shots → Edit → Screen.
// Edits a project, queues renders, polls progress. The studio re-tints to each film's look.
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const api = async (path, opts = {}) => {
  const res = await fetch(path, opts);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
};
const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body || {}) });
const escapeHtml = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const store = {  // per-viewer conveniences only; the page works without them
  get(k) { try { return localStorage.getItem("oc." + k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem("oc." + k, v); } catch { /* private mode */ } },
};

const CAMERA_ANIM = {
  "Static": "", "Dolly in": "dollyin 2.4s ease-in-out infinite alternate", "Dolly out": "dollyout 2.4s ease-in-out infinite alternate",
  "Push in (slow)": "dollyin 4s ease-in-out infinite alternate", "Crash zoom": "crashzoom 1.6s ease-in infinite",
  "Truck left": "truckl 2.4s ease-in-out infinite alternate", "Truck right": "truckr 2.4s ease-in-out infinite alternate",
  "Pan left": "truckl 2.4s linear infinite alternate", "Pan right": "truckr 2.4s linear infinite alternate",
  "Tilt up": "tiltu 2.4s ease-in-out infinite alternate", "Tilt down": "tiltd 2.4s ease-in-out infinite alternate",
  "Crane up": "tiltu 2.4s ease-in-out infinite alternate, dollyout 2.4s ease-in-out infinite alternate",
  "Crane down": "tiltd 2.4s ease-in-out infinite alternate", "Orbit left": "orbit 2.4s ease-in-out infinite alternate-reverse",
  "Orbit right": "orbit 2.4s ease-in-out infinite alternate", "Handheld follow": "shake 1.2s ease-in-out infinite",
  "Whip pan": "whip 1.4s ease-in-out infinite", "Drone flyover": "dollyin 3s linear infinite",
  "FPV dive": "tiltd 1s ease-in infinite, dollyin 1s ease-in infinite", "Dolly zoom (vertigo)": "vertigo 2.4s ease-in-out infinite alternate",
  "Bullet time": "orbit 4s linear infinite alternate", "Snorricam": "spin 1.6s ease-in-out infinite alternate",
};
const FACE = { fraunces: "Fraunces", barlow: "Barlow Condensed", manrope: "Manrope" };
const TRANSITIONS = ["cut", "dissolve", "continue"];
const JOINT = { cut: "│", dissolve: "◇", continue: "∞" };
const JOINT_NAME = { cut: "Cut", dissolve: "Dissolve", continue: "One take" };

let presets, project, projects = [], jobs = [], saveTimer, selected = null;
let stage = store.get("stage") || "story", view = "film", screen = "master";
const media = name => name ? `/media/${project.id}/${encodeURIComponent(name)}` : "";
const shotIndex = id => project.shots.findIndex(s => s.id === id);
const active = j => j.state === "queued" || j.state === "running";
const busyFor = test => jobs.find(j => j.project === project.id && active(j) && test(j));

// ---------------------------------------------------------------- boot
async function init() {
  presets = await api("/api/presets");
  projects = await api("/api/projects");
  const remembered = store.get("project");
  const first = projects.find(p => p.id === remembered) || projects[0];
  if (first) await openProject(first.id); else await createProject();
  setStage(stage);
  setInterval(poll, 1500);
  poll();
}

async function openProject(id) {
  project = await api(`/api/projects/${id}`);
  store.set("project", id);
  selected = project.shots[0]?.id || null;
  renderAll();
}

async function createProject() {
  project = await post("/api/projects", { title: "Untitled film" });
  projects = await api("/api/projects");
  store.set("project", project.id);
  selected = project.shots[0]?.id || null;
  renderAll();
  setStage("story");
  $("#title").focus(); $("#title").select();
}

function setStage(next) {
  stage = next; store.set("stage", next);
  document.body.dataset.stage = next;
  for (const s of ["story", "shots", "edit", "screen"]) $("#" + s).hidden = s !== next;
  $$(".stages button").forEach(b => b.classList.toggle("on", b.dataset.stage === next));
  $$("video").forEach(v => { if (!v.closest(".stage:not([hidden])") && !v.closest(".card")) v.pause(); });
  requestAnimationFrame(() => growAll($("#" + next)));
  if (next === "edit") renderEdit();
  if (next === "screen") renderScreen();
  window.scrollTo({ top: 0 });
}

function renderAll() {
  applyTheme();
  renderHeader();
  renderStory();
  renderBoard();
  renderInspector();
  renderEdit();
  renderScreen();
}

// ---------------------------------------------------------------- theme & header
function luminance(hex) {
  const [r, g, b] = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function effectivePalette() {
  // [ink, accent, glow, bg, face] — the look's, with the film's custom colours on top
  const base = presets.palettes?.[project.look] || ["#f4f4f2", "#e2a43a", "#ffd27a", "#0a0a0b", "fraunces"];
  const c = project.palette;
  return c && c.accent ? [c.ink, c.accent, c.glow, c.bg, base[4]] : base;
}

function applyTheme() {
  const palette = effectivePalette();
  const root = document.documentElement.style;
  root.setProperty("--accent", palette[1]);
  root.setProperty("--accent-ink", luminance(palette[1]) > 0.45 ? "#120e0a" : "#fbfaf7");
  const key = project.title_shot?.keyframe || project.shots.find(s => s.keyframe)?.keyframe || project.reference;
  const amb = $("#ambient");
  if (key) { amb.style.backgroundImage = `url("${media(key)}")`; amb.classList.add("on"); }
  else amb.classList.remove("on");
  $("#lookSwatches").innerHTML = [palette[3], palette[0], palette[1], palette[2]].map(c => `<span style="background:${c}"></span>`).join("");
  paintPalette();
}

function paintPalette() {
  const [ink, accent, glow, bg, face] = effectivePalette();
  const values = { bg, ink, accent, glow };
  $$("[data-pal]").forEach(i => { if (document.activeElement !== i) i.value = values[i.dataset.pal]; });
  const sample = $("#paletteSample").style;
  sample.setProperty("--ps-bg", bg); sample.setProperty("--ps-ink", ink);
  sample.setProperty("--ps-accent", accent); sample.setProperty("--ps-glow", glow);
  sample.setProperty("--ps-face", FACE[face] || "Manrope");
  $("#psTitle").textContent = project.title || "Untitled film";
  const custom = !!(project.palette && project.palette.accent);
  $("#paletteSource").textContent = custom ? "Custom colours for this film" : `From the ${project.look} look`;
  $("#paletteReset").hidden = !custom;
}

function renderHeader() {
  $("#projectTitle").textContent = project.title || "Untitled film";
  document.title = `${project.title || "Untitled film"} · Open Cinema`;
  const n = project.shots.length, rendered = project.shots.filter(s => s.video).length;
  const mastered = project.film && project.master && project.master_of === project.film;
  const st = (id, text, done) => { const el = $(id); el.textContent = text; el.classList.toggle("done", done); };
  st("#stStory", project.scene && project.reference ? "✓" : "", !!(project.scene && project.reference));
  st("#stShots", `${rendered}/${n}`, rendered === n && n > 0);
  st("#stEdit", project.film ? "✓" : "", !!project.film);
  st("#stScreen", mastered ? "1080p" : "", !!mastered);
}

function renderProjectMenu() {
  $("#projectList").innerHTML = projects.map(p => `<li><button data-id="${p.id}" class="${p.id === project.id ? "current" : ""}">
    <span>${escapeHtml(p.title)}</span><small>${p.shots} shots</small></button></li>`).join("");
  $$("#projectList button").forEach(b => b.onclick = async () => { $("#projectMenu").hidden = true; await flush(); openProject(b.dataset.id); });
}

function renderStatus() {
  const mine = jobs.filter(active);
  const running = mine.find(j => j.state === "running");
  $("#comfyDot").className = "dot " + (presets.comfy === false ? "" : running ? "busy" : "ok");
  $("#statusText").textContent = running ? `${running.label} · ${Math.round(running.elapsed)}s${mine.length > 1 ? ` · +${mine.length - 1}` : ""}`
    : presets.comfy === false ? "ComfyUI offline" : "Ready";
  const filmBusy = jobs.some(j => j.project === project.id && active(j));
  $("#renderFilm").disabled = filmBusy;
  $("#jobs").innerHTML = jobs.filter(j => j.project === project.id).slice().reverse().slice(0, 40).map(j => `<li class="${j.state}">
    <span>${escapeHtml(j.label)}</span><small>${j.state === "running" || j.state === "done" ? Math.round(j.elapsed) + "s · " : ""}${j.state}</small>
    ${j.error ? `<span class="err">${escapeHtml(j.error)}</span>` : ""}</li>`).join("") || `<li><span class="hint">Nothing rendered yet</span></li>`;
}

// ---------------------------------------------------------------- story
function renderStory() {
  $("#title").value = project.title;
  $("#idea").value = project.idea || "";
  $("#logline").value = project.logline || "";
  $("#scene").value = project.scene;
  $("#cast").value = project.cast || "";
  $("#continuity").value = project.continuity || "";
  paintPortrait();
  requestAnimationFrame(() => growAll($("#story")));
  const grid = $("#looks");
  grid.innerHTML = "";
  for (const look of presets.looks) {
    const [ink, accent, glow, bg, face] = presets.palettes[look];
    const score = (presets.score_styles?.[look] || "").split(" with ")[0].replace(/^(an?|the) /, "");
    const b = document.createElement("button");
    b.type = "button"; b.className = "look" + (look === project.look ? " on" : "");
    b.style.setProperty("--look", accent); b.style.setProperty("--ink", ink);
    b.innerHTML = `<div class="look-top"><span class="look-sample" style="font-family:${FACE[face] || "Manrope"};font-weight:${face === "manrope" ? 800 : 900}">Aa</span>
      <span class="look-swatches">${[bg, ink, accent, glow].map(c => `<i style="background:${c}"></i>`).join("")}</span></div>
      <span class="look-name">${escapeHtml(look)}</span><span class="look-score">${escapeHtml(score)}</span>`;
    b.onclick = () => {  // picking a look brings its colours; tune them afterwards in Colours
      project.look = look; project.palette = null;
      $$(".look", grid).forEach(x => x.classList.toggle("on", x === b)); applyTheme(); renderEditPanel(); save();
    };
    b.title = presets.score_styles?.[look] || look;
    grid.appendChild(b);
  }
  const aspects = $("#aspects");
  aspects.innerHTML = presets.aspects.map(a => `<button type="button" class="${a === project.aspect ? "on" : ""}">${a}</button>`).join("");
  $$("button", aspects).forEach(b => b.onclick = () => { project.aspect = b.textContent; $$("button", aspects).forEach(x => x.classList.toggle("on", x === b)); save(); });
}

function paintPortrait() {
  const img = $("#refImg");
  img.hidden = !project.reference;
  if (project.reference && img.dataset.src !== project.reference) { img.src = media(project.reference); img.dataset.src = project.reference; }
  $("#refEmpty").hidden = !!project.reference;
  const job = busyFor(j => j.kind === "cast");
  $("#castBusy").hidden = !job;
  if (job) $("#castBusy").textContent = job.state === "running" ? `Casting · ${Math.round(job.elapsed)}s` : "Casting · queued";
  $("#castBtn").textContent = project.reference ? "Re-cast from description" : "Cast from description";
  paintLeadAI();
}

const STORY_TARGET_FIELDS = {
  everything: ["titleField", "loglineField", "worldField", "lookField", "castField", "continuityField", "sparkField"],
  title: ["titleField"], logline: ["loglineField"], world: ["worldField"], look: ["lookField"],
};
const AI_FIELDS = ["titleField", "loglineField", "worldField", "lookField", "castField", "continuityField", "sparkField"];

function paintLeadAI() {
  const job = busyFor(j => j.kind === "write_lead" || j.kind === "write_story");
  const status = job ? (job.state === "running" ? `${job.label}… ${Math.round(job.elapsed)}s` : `${job.label} · queued`) : "";
  let writing = [];
  if (job?.kind === "write_story") writing = STORY_TARGET_FIELDS[job.target] || [];
  if (job?.kind === "write_lead") writing = job.mode === "continuity" ? ["continuityField"] : ["castField", "continuityField"];
  for (const id of AI_FIELDS) {
    const el = $("#" + id), on = writing.includes(id);
    el.classList.toggle("writing", on);
    el.dataset.status = on && (id === writing[0] || id === "lookField") && id !== "sparkField" ? status : "";
  }
  $$("[data-ai], #aiLead, #aiPhoto, #aiContinuity, #aiEverything").forEach(b => { b.disabled = !!job; });
  $("#aiEverything").textContent = job?.target === "everything" ? `Writing… ${Math.round(job.elapsed || 0)}s` : "✨ Generate the whole story";
  $("#aiLead").textContent = (project.cast || "").trim() ? "✨ Refine" : "✨ Write with AI";
  $("#aiLead").title = (project.cast || "").trim() ? "Keep your details and make them camera-ready" : "Cast a lead who belongs in this world";
  $("#aiPhoto").hidden = !project.reference;
  $("#aiUndo").hidden = !(project.story_history || []).length;
}

async function writeStory(target) {
  await flush();
  await post(`/api/projects/${project.id}/write-story`, { target });
  poll();
}

async function writeLead(mode) {
  await flush();
  await post(`/api/projects/${project.id}/write-lead`, { mode });
  poll();
}

function flash(id) { const el = $("#" + id); el.classList.remove("fresh"); void el.offsetWidth; el.classList.add("fresh"); }

function adoptStory(fresh) {
  const text = [["title", "titleField"], ["logline", "loglineField"], ["scene", "worldField"], ["cast", "castField"],
    ["continuity", "continuityField"]];
  for (const [key, field] of text) {
    if ((project[key] || "") === (fresh[key] || "")) continue;
    project[key] = fresh[key] || "";
    const el = $("#" + key); el.value = project[key]; if (el.tagName === "TEXTAREA") grow(el);
    flash(field);
  }
  const lookChanged = project.look !== fresh.look || JSON.stringify(project.palette || null) !== JSON.stringify(fresh.palette || null);
  project.look = fresh.look; project.palette = fresh.palette;
  if (lookChanged) {
    $$(".look").forEach(b => b.classList.toggle("on", $(".look-name", b).textContent === project.look));
    flash("lookField"); renderEditPanel();
  }
  renderHeader(); applyTheme();
}

// ---------------------------------------------------------------- shots: storyboard
function renderBoard() {
  const board = $("#board");
  const rendered = project.shots.filter(s => s.video).length;
  $("#shotsHeading").textContent = `${project.shots.length} shots · ${rendered} rendered`;
  board.innerHTML = "";
  project.shots.forEach((shot, i) => {
    const card = document.createElement("article");
    card.className = "card" + (shot.id === selected ? " selected" : "");
    card.dataset.id = shot.id;
    card.tabIndex = 0;
    card.innerHTML = `<div class="media"><img alt="" hidden><video muted loop playsinline preload="none" hidden></video>
      <div class="empty">No frame yet</div><div class="busy" hidden></div>
      <span class="num">${String(i + 1).padStart(2, "0")}</span><span class="badges"></span></div>
      <div class="meta"><p class="action"></p><div class="facts"><span class="mini-cam"><span class="cam-scene"><span></span></span></span>
      <span class="move"></span><span>·</span><span class="size"></span><span>·</span><span class="secs"></span></div></div>`;
    card.onclick = () => select(shot.id);
    card.onkeydown = e => { if (e.key === "Enter") select(shot.id); };
    const vid = $("video", card);
    card.onmouseenter = () => { if (shot.video) { if (!vid.src) vid.src = media(shot.video); vid.play().catch(() => {}); } };
    card.onmouseleave = () => vid.pause();
    board.appendChild(card);
    paintCard(card, shot, i);
  });
  const add = document.createElement("button");
  add.className = "add-card"; add.type = "button"; add.textContent = "+ Add shot";
  add.onclick = addShot;
  board.appendChild(add);
}

function paintCard(card, shot, i) {
  const img = $("img", card), vid = $("video", card);
  img.hidden = !shot.keyframe;
  if (shot.keyframe && img.dataset.src !== shot.keyframe) { img.src = media(shot.keyframe); img.dataset.src = shot.keyframe; }
  vid.hidden = !shot.video;
  if (shot.video && vid.dataset.src !== shot.video) { vid.dataset.src = shot.video; vid.removeAttribute("src"); }
  $(".empty", card).hidden = !!shot.keyframe;
  const action = $(".action", card);
  action.textContent = shot.action || "Describe what happens…";
  action.classList.toggle("empty", !shot.action);
  $(".move", card).textContent = shot.camera_move;
  $(".size", card).textContent = shot.shot_size;
  $(".secs", card).textContent = `${shot.seconds}s`;
  $(".cam-scene", card).style.animation = CAMERA_ANIM[shot.camera_move] || "";
  const badges = [];
  if (i > 0 && shot.transition !== "cut") badges.push(`<span class="badge">${JOINT_NAME[shot.transition].toUpperCase()}</span>`);
  if (shot.lead === false) badges.push(`<span class="badge">NO LEAD</span>`);
  if (shot.video) badges.push(`<span class="badge accent">▶</span>`);
  const last = jobs.filter(j => j.project === project.id && j.shot === shot.id).at(-1);
  if (last?.state === "failed") badges.push(`<span class="badge fail" title="${escapeHtml(last.error)}">FAILED</span>`);
  $(".badges", card).innerHTML = badges.join("");
  const job = busyFor(j => j.shot === shot.id);
  const busy = $(".busy", card);
  busy.hidden = !job;
  if (job) busy.textContent = job.state === "running" ? `${job.label}\n${Math.round(job.elapsed)}s` : `${job.label} · queued`;
}

function paintBoard() {
  $$(".card", $("#board")).forEach(card => {
    const i = shotIndex(card.dataset.id);
    if (i >= 0) paintCard(card, project.shots[i], i);
  });
}

function select(id) {
  selected = id;
  $$(".card").forEach(c => c.classList.toggle("selected", c.dataset.id === id));
  renderInspector();
  if (window.innerWidth <= 1240) $("#inspector").scrollIntoView({ behavior: "smooth", block: "start" });
}

// ---------------------------------------------------------------- shots: inspector
function renderInspector() {
  const ins = $("#inspector");
  const i = shotIndex(selected);
  if (i < 0) { ins.innerHTML = `<p class="hint">Select a shot to direct it.</p>`; return; }
  const shot = project.shots[i];
  const opts = (list, cur) => list.map(o => `<option${o === cur ? " selected" : ""}>${escapeHtml(o)}</option>`).join("");
  ins.innerHTML = `
    <div class="ins-head"><div><p class="eyebrow">Shot ${String(i + 1).padStart(2, "0")}</p><span class="serif">${escapeHtml(shot.camera_move)}</span></div>
      <div class="row-actions"><button class="ghost small" data-act="dup" title="Duplicate">Duplicate</button>
      <button class="ghost small danger" data-act="del" title="Delete">Delete</button></div></div>
    <div class="ins-media"></div>
    <div class="strips"></div>
    <label>What happens<textarea class="grow" data-k="action" rows="3" placeholder="Describe the action, as you'd see it">${escapeHtml(shot.action)}</textarea></label>
    <div class="cam-field"><label>Camera move<select data-k="camera_move">${opts(presets.camera_moves, shot.camera_move)}</select></label>
      <div class="cam-preview" title="Camera move preview"><div class="cam-scene"><span></span></div></div></div>
    <div class="field-row"><label>Shot size<select data-k="shot_size">${opts(presets.shot_sizes, shot.shot_size)}</select></label>
      <label>Seconds<input data-k="seconds" type="number" min="2" max="10" step="1" value="${shot.seconds}"></label></div>
    <label>Sound<input data-k="sound" value="${escapeHtml(shot.sound)}" placeholder="What we hear: wind, waves, footsteps…"></label>
    <div class="field-row" style="align-items:center">
      <label class="switch"><input type="checkbox" data-k="lead" ${shot.lead !== false ? "checked" : ""}><span></span>Lead in shot</label>
      <div class="seg" role="group" aria-label="Transition in">${TRANSITIONS.map(t =>
        `<button type="button" data-tr="${t}" class="${(shot.transition || "cut") === t ? "on" : ""}" ${i === 0 && t !== "cut" ? "disabled" : ""}>${JOINT_NAME[t]}</button>`).join("")}</div>
    </div>
    <div class="ins-actions">
      <button class="ghost" data-act="keyframe" ${shot.transition === "continue" && i > 0 ? "disabled" : ""}>New frame</button>
      <label class="button ghost">Upload frame<input type="file" accept="image/*" hidden data-act="upload"></label>
      <button class="primary" data-act="video">Render shot</button>
    </div>
    <details class="prompts"><summary>Prompts the models receive</summary><div class="prompt-body"></div></details>`;
  $(".cam-scene", ins).style.animation = CAMERA_ANIM[shot.camera_move] || "";
  requestAnimationFrame(() => growAll(ins));
  for (const field of $$("[data-k]", ins)) {
    const key = field.dataset.k;
    field.addEventListener(field.tagName === "SELECT" || field.type === "checkbox" ? "change" : "input", () => {
      shot[key] = field.type === "checkbox" ? field.checked : field.type === "number" ? Number(field.value) : field.value;
      if (key === "camera_move") { $(".cam-scene", ins).style.animation = CAMERA_ANIM[shot.camera_move] || ""; $(".ins-head .serif", ins).textContent = shot.camera_move; }
      const card = $(`.card[data-id="${shot.id}"]`);
      if (card) paintCard(card, shot, i);
      save();
    });
  }
  $$("[data-tr]", ins).forEach(b => b.onclick = () => { shot.transition = b.dataset.tr; save(true); });
  $('[data-act="keyframe"]', ins).onclick = () => queueShot(shot, "keyframe");
  $('[data-act="video"]', ins).onclick = () => queueShot(shot, "video");
  $('[data-act="upload"]', ins).onchange = e => uploadKeyframe(shot, e.target.files[0]);
  $('[data-act="dup"]', ins).onclick = () => {
    project.shots.splice(i + 1, 0, { ...shot, id: undefined, keyframe: null, video: null, takes: undefined, seed: undefined });
    save(true).then(() => select(project.shots[i + 1].id));
  };
  $('[data-act="del"]', ins).onclick = () => {
    if (project.shots.length > 1 && confirm(`Delete shot ${i + 1}?`)) {
      project.shots.splice(i, 1); selected = project.shots[Math.max(0, i - 1)].id; save(true);
    }
  };
  paintInspector();
}

function paintInspector() {
  const ins = $("#inspector"), i = shotIndex(selected);
  if (i < 0 || !$(".ins-media", ins)) return;
  const shot = project.shots[i], box = $(".ins-media", ins);
  const want = shot.video ? `v:${shot.video}` : shot.keyframe ? `k:${shot.keyframe}` : "none";
  if (box.dataset.sig !== want) {
    box.dataset.sig = want;
    box.innerHTML = shot.video ? `<video src="${media(shot.video)}" controls loop playsinline></video>`
      : shot.keyframe ? `<img src="${media(shot.keyframe)}" alt="">` : `<div class="empty">Render film or press New frame</div>`;
  }
  const job = busyFor(j => j.shot === shot.id);
  let busy = $(".busy", box);
  if (job && !busy) { busy = document.createElement("div"); busy.className = "busy"; box.appendChild(busy); }
  if (busy) { busy.hidden = !job; if (job) busy.textContent = job.state === "running" ? `${job.label} · ${Math.round(job.elapsed)}s` : `${job.label} · queued`; }
  // take filmstrips
  const takes = shot.takes || {}, frames = takes.keyframe || [];
  const vids = (takes.video || []).filter(t => t.keyframe === shot.keyframe);
  const strips = $(".strips", ins);
  const sig = JSON.stringify([frames.map(t => t.name), vids.map(t => t.name), shot.keyframe, shot.video]);
  if (strips.dataset.sig !== sig) {
    strips.dataset.sig = sig;
    const strip = (label, list, kind, current) => list.length < 2 ? "" : `<div><div class="strip-label">${label}</div><div class="filmstrip">${
      list.map((t, n) => `<button class="take ${t.name === current ? "on" : ""}" data-kind="${kind}" data-name="${escapeHtml(t.name)}" title="${t.seed ? "seed " + t.seed : ""}">
        ${kind === "video" ? `<video src="${media(t.name)}#t=0.5" muted preload="metadata"></video>` : `<img src="${media(t.name)}" alt="">`}
        <span>${kind === "video" ? "S" : "K"}${n + 1}</span></button>`).join("")}</div></div>`;
    strips.innerHTML = strip("Frame takes", frames, "keyframe", shot.keyframe) + strip("Shot takes", vids, "video", shot.video);
    $$(".take", strips).forEach(b => b.onclick = async () =>
      mergeServer(await post(`/api/projects/${project.id}/shots/${shot.id}/take`, { kind: b.dataset.kind, name: b.dataset.name }), true));
  }
  const kp = frames.find(t => t.name === shot.keyframe)?.prompt || shot.keyframe_prompt;
  const mp = vids.find(t => t.name === shot.video)?.prompt || shot.motion_prompt;
  const pb = $(".prompt-body", ins);
  const psig = (kp || "") + "|" + (mp || "");
  if (pb.dataset.sig !== psig) {
    pb.dataset.sig = psig;
    pb.innerHTML = (kp ? `<div class="strip-label">Frame</div><p>${escapeHtml(kp)}</p>` : "") +
      (mp ? `<div class="strip-label">Motion &amp; sound</div><p>${escapeHtml(mp)}</p>` : "") ||
      `<p class="hint">Prompts appear after the first render.</p>`;
  }
}

// ---------------------------------------------------------------- edit
function motionState() {
  const m = project.motion || {};
  return {
    title: { on: m.title?.on ?? true, subtitle: m.title?.subtitle ?? "A film made with open models",
             style: m.title?.style ?? "kinetic", material: m.title?.material ?? "" },
    stamps: { on: m.stamps?.on ?? false },
    credits: { on: m.credits?.on ?? true, lines: m.credits?.lines ?? "" },
    trailer: { lines: m.trailer?.lines ?? "" },
  };
}

function renderEdit() {
  renderViewer();
  renderEditPanel();
  renderTimeline();
  $("#finish").checked = !!project.finish;
}

function renderViewer() {
  $$("#viewerTabs button").forEach(b => { b.classList.toggle("on", b.dataset.view === view); b.disabled = b.dataset.view === "trailer" && !project.trailer; });
  const src = view === "trailer" ? project.trailer : project.film;
  const v = $("#viewer");
  if (src && v.dataset.src !== src) { v.src = media(src); v.dataset.src = src; }
  v.hidden = !src;
  $("#viewerEmpty").hidden = !!src;
  const total = project.shots.reduce((s, x) => s + Number(x.seconds || 0), 0);
  const done = project.shots.filter(s => s.video).length;
  $("#viewerInfo").textContent = src ? (view === "trailer" ? "Trailer · score composed by LTX" : `${project.shots.length} shots · about ${total}s`)
    : `${done}/${project.shots.length} shots rendered`;
  const cutting = busyFor(j => j.kind === "stitch");
  $("#stitch").disabled = !!cutting;
  $("#stitch").textContent = cutting ? (cutting.state === "running" ? "Cutting…" : "Queued…") : project.film ? "Re-cut film" : "Cut film";
}

function renderEditPanel() {
  const m = motionState(), d = project.motion_defaults || {};
  $("#mTitle").checked = m.title.on;
  setIfIdle($("#mSubtitle"), m.title.subtitle);
  setIfIdle($("#mMaterial"), m.title.material);
  $("#mMaterial").placeholder = d.material || "Material";
  $$("[data-style]").forEach(b => b.classList.toggle("on", b.dataset.style === m.title.style));
  $(".title-kinetic").hidden = m.title.style === "inworld";
  $(".title-inworld").hidden = m.title.style !== "inworld";
  $("#mStamps").checked = m.stamps.on;
  $("#mCredits").checked = m.credits.on;
  setIfIdle($("#mCreditsLines"), m.credits.lines);
  $("#mCreditsLines").placeholder = d.credits || "";
  setIfIdle($("#mTrailerLines"), m.trailer.lines);
  $("#mTrailerLines").placeholder = d.trailer || "";
  const sample = project.shots[Math.min(2, project.shots.length - 1)] || {};
  $("#stampSample").innerHTML = `SHOT ${String(Math.min(3, project.shots.length)).padStart(2, "0")} · ${escapeHtml((sample.shot_size || "").toUpperCase())} · <mark>${escapeHtml((sample.camera_move || "").toUpperCase())}</mark>`;
  const img = $("#mPreviewImg");
  img.hidden = !project.motion_preview;
  if (project.motion_preview && img.dataset.src !== project.motion_preview) { img.src = media(project.motion_preview); img.dataset.src = project.motion_preview; }
  paintTitleShot();
  $("#newScore").hidden = !project.trailer_score;
  const trailerJob = busyFor(j => j.kind === "trailer");
  $("#cutTrailer").disabled = $("#newScore").disabled = !!trailerJob;
  $("#cutTrailer").textContent = trailerJob ? (trailerJob.state === "running" ? `${trailerJob.label} · ${Math.round(trailerJob.elapsed)}s` : "Queued…") : project.trailer ? "Re-cut trailer" : "Cut trailer";
}

function setIfIdle(el, value) { if (document.activeElement !== el) el.value = value; }

function paintTitleShot() {
  const unit = project.title_shot || {}, img = $("#titleFrame"), vid = $("#titleShot");
  img.hidden = !unit.keyframe || !!unit.video;
  vid.hidden = !unit.video;
  if (unit.keyframe && img.dataset.src !== unit.keyframe) { img.src = media(unit.keyframe); img.dataset.src = unit.keyframe; }
  if (unit.video && vid.dataset.src !== unit.video) { vid.src = media(unit.video); vid.dataset.src = unit.video; vid.play().catch(() => {}); }
  $("#rerollTitleMotion").hidden = !unit.keyframe;
  const box = $("#titleTakes"), takes = unit.takes || {};
  const frames = takes.keyframe || [], vids = (takes.video || []).filter(t => t.keyframe === unit.keyframe);
  const sig = JSON.stringify([frames.map(t => t.name), vids.map(t => t.name), unit.keyframe, unit.video]);
  if (box.dataset.sig !== sig) {
    box.dataset.sig = sig; box.innerHTML = "";
    const chip = (label, kind, take, on) => {
      const b = document.createElement("button");
      b.textContent = label; b.type = "button"; b.classList.toggle("on", on);
      b.onclick = async () => mergeServer(await post(`/api/projects/${project.id}/title-shot/take`, { kind, name: take.name }));
      box.appendChild(b);
    };
    if (frames.length > 1) { box.append("Frame"); frames.forEach((t, n) => chip(`K${n + 1}`, "keyframe", t, t.name === unit.keyframe)); }
    if (vids.length > 1) { const s = document.createElement("span"); s.className = "sep"; box.append(s, "Motion"); vids.forEach((t, n) => chip(`S${n + 1}`, "video", t, t.name === unit.video)); }
  }
  const busy = busyFor(j => j.kind.startsWith("title_"));
  $("#makeTitle").disabled = $("#rerollTitleMotion").disabled = !!busy;
  $("#makeTitle").textContent = busy ? (busy.state === "running" ? `${busy.label} · ${Math.round(busy.elapsed)}s` : "Queued…")
    : unit.keyframe ? "New title frame" : "Make in-world title";
}

function saveMotion() {
  const style = $("[data-style].on")?.dataset.style || "kinetic";
  project.motion = {
    title: { on: $("#mTitle").checked, subtitle: $("#mSubtitle").value, style, material: $("#mMaterial").value },
    stamps: { on: $("#mStamps").checked },
    credits: { on: $("#mCredits").checked, lines: $("#mCreditsLines").value },
    trailer: { lines: $("#mTrailerLines").value },
  };
  renderTimeline();
  save();
}

let dragId = null;
function renderTimeline() {
  const m = motionState(), shots = project.shots;
  const inworld = m.title.on && m.title.style === "inworld" && project.title_shot?.video;
  const pic = $("#pictureTrack"), titles = $("#titlesTrack"), sound = $("#soundTrack");
  pic.innerHTML = ""; titles.innerHTML = ""; sound.innerHTML = `<div class="wave"></div>`;
  const clip = (grow, html, cls, bg) => {
    const el = document.createElement("div");
    el.className = "clip " + cls; el.style.flexGrow = grow; el.innerHTML = html;
    if (bg) el.style.backgroundImage = `url("${bg}")`;
    return el;
  };
  const layer = (grow, text, on) => {
    const el = document.createElement("div");
    el.className = "layer " + (text ? (on ? "on" : "off") : "gap"); el.style.flexGrow = grow; el.textContent = text || ".";
    titles.appendChild(el);
  };
  if (inworld) {
    pic.appendChild(clip(4, `<b>TITLE</b><small>in-world · 4s</small>`, "", media(project.title_shot.keyframe)));
    pic.appendChild(Object.assign(document.createElement("button"), { className: "joint dissolve", textContent: JOINT.dissolve, title: "Dissolve", disabled: true }));
    layer(4, "IN-WORLD TITLE", true);
  }
  shots.forEach((shot, i) => {
    if (i > 0) {
      const t = shot.transition || "cut";
      const j = document.createElement("button");
      j.className = "joint " + t; j.textContent = JOINT[t]; j.title = `${JOINT_NAME[t]} — click to change`;
      j.onclick = () => { shot.transition = TRANSITIONS[(TRANSITIONS.indexOf(t) + 1) % 3]; renderTimeline(); paintBoard(); if (selected === shot.id) renderInspector(); save(); };
      pic.appendChild(j);
    }
    const c = clip(shot.seconds, `<b>${String(i + 1).padStart(2, "0")}</b><small>${escapeHtml(shot.camera_move)} · ${shot.seconds}s</small>`,
      shot.video ? "" : "pending", shot.keyframe ? media(shot.keyframe) : "");
    c.draggable = true; c.dataset.id = shot.id; c.title = "Drag to reorder · click to open";
    c.ondragstart = e => { dragId = shot.id; c.classList.add("dragging"); e.dataTransfer.effectAllowed = "move"; };
    c.ondragend = () => { dragId = null; c.classList.remove("dragging"); $$(".clip.drop-before").forEach(x => x.classList.remove("drop-before")); };
    c.ondragover = e => { if (dragId && dragId !== shot.id) { e.preventDefault(); c.classList.add("drop-before"); } };
    c.ondragleave = () => c.classList.remove("drop-before");
    c.ondrop = e => { e.preventDefault(); reorder(dragId, shot.id); };
    c.onclick = () => { setStage("shots"); select(shot.id); };
    pic.appendChild(c);
    const label = i === 0 && m.title.on && !inworld ? "MAIN TITLE" : i > 0 && m.stamps.on ? `SHOT ${String(i + 1).padStart(2, "0")}` : "";
    layer(shot.seconds, label, true);
  });
  if (m.credits.on) {
    pic.appendChild(Object.assign(document.createElement("button"), { className: "joint cut", textContent: JOINT.cut, disabled: true }));
    pic.appendChild(clip(3, `<b>CREDITS</b><small>${(m.credits.lines || project.motion_defaults?.credits || "").split("\n").filter(Boolean).length} cards</small>`, ""));
    layer(3, "CREDITS", true);
  }
}

function reorder(fromId, beforeId) {
  const from = shotIndex(fromId);
  if (from < 0 || fromId === beforeId) return;
  const [shot] = project.shots.splice(from, 1);
  project.shots.splice(shotIndex(beforeId), 0, shot);
  if (project.shots[0].transition !== "cut") project.shots[0].transition = "cut";
  save(true);
  toast("Shots reordered — re-cut the film to apply");
}

// ---------------------------------------------------------------- screen
function renderScreen() {
  const mastered = project.film && project.master && project.master_of === project.film;
  const sources = { master: mastered ? project.master : null, film: project.film, trailer: project.trailer };
  if (!sources[screen]) screen = ["master", "film", "trailer"].find(k => sources[k]) || "master";
  $$("#screenTabs button").forEach(b => { b.classList.toggle("on", b.dataset.screen === screen); b.disabled = !sources[b.dataset.screen]; });
  const src = sources[screen], v = $("#screenVideo");
  if (src && v.dataset.src !== src) { v.src = media(src); v.dataset.src = src; }
  v.hidden = !src;
  $("#screenEmpty").hidden = !!src;
  $("#screenEmpty").textContent = project.film ? "" : "Nothing to screen yet — render the shots and cut the film.";
  $("#screenTitle").textContent = project.title;
  const total = project.shots.reduce((s, x) => s + Number(x.seconds || 0), 0);
  $("#screenInfo").textContent = { master: "1080p master · SeedVR2", film: `${project.shots.length} shots · about ${total}s · 1280×704`,
    trailer: "Trailer · score composed by LTX" }[screen] + (project.finish ? " · film finish" : "");
  const dl = $("#download");
  dl.hidden = !src; dl.href = media(src); dl.download = `${project.title}${screen === "film" ? "" : " " + screen}.mp4`;
  const masterJob = busyFor(j => j.kind === "master");
  $("#master").hidden = !project.film || !!mastered;
  $("#master").disabled = !!masterJob;
  $("#master").textContent = masterJob ? (masterJob.state === "running" ? `${masterJob.label} · ${Math.round(masterJob.elapsed)}s` : "Queued…") : "Master in 1080p";
}

function grow(el) {
  if (!el.offsetParent) return;  // hidden stages measure zero; they re-grow when shown
  el.style.height = "auto"; el.style.height = el.scrollHeight + 2 + "px";
}
function growAll(root = document) { $$("textarea.grow", root).forEach(grow); }
document.addEventListener("input", e => { if (e.target.matches?.("textarea.grow")) grow(e.target); });

// ---------------------------------------------------------------- persistence
function save(rerender) {
  clearTimeout(saveTimer);
  const doSave = async () => mergeServer(await post(`/api/projects/${project.id}`, project), rerender);
  if (rerender) return doSave();
  saveTimer = setTimeout(doSave, 400);
  return Promise.resolve();
}

async function flush() { clearTimeout(saveTimer); mergeServer(await post(`/api/projects/${project.id}`, project)); }

function mergeServer(fresh, rerender) {
  const sameShots = fresh.shots.length === project.shots.length && fresh.shots.every((s, i) => !project.shots[i].id || s.id === project.shots[i].id);
  if (rerender || !sameShots) {
    project = fresh;
    if (shotIndex(selected) < 0) selected = project.shots[0]?.id || null;
    renderBoard(); renderInspector(); renderTimeline(); renderViewer(); renderEditPanel(); renderScreen(); renderHeader(); applyTheme();
    return;
  }
  // keep what the user is typing; take generated media from the server
  fresh.shots.forEach((s, i) => Object.assign(project.shots[i], { id: s.id, keyframe: s.keyframe, video: s.video, takes: s.takes, seed: s.seed }));
  for (const k of ["film", "master", "master_of", "trailer", "motion_preview", "motion_defaults", "title_shot", "trailer_score", "reference"]) project[k] = fresh[k];
  if ((fresh.story_history || []).length !== (project.story_history || []).length) adoptStory(fresh);  // the AI (or undo) changed the page
  project.story_history = fresh.story_history;
  paintBoard(); paintInspector(); paintPortrait(); renderViewer(); renderEditPanel(); renderTimeline(); renderScreen(); renderHeader(); applyTheme();
}

async function queueShot(shot, kind) { await flush(); await post(`/api/projects/${project.id}/shots/${shot.id}/${kind}`); toast(kind === "video" ? "Shot queued" : "New frame queued"); poll(); }

async function uploadKeyframe(shot, file) {
  if (!file) return;
  await flush();
  mergeServer(await api(`/api/projects/${project.id}/shots/${shot.id}/keyframe-upload`,
    { method: "POST", body: file, headers: { "X-Filename": encodeURIComponent(file.name) } }), true);
}

async function uploadReference(file) {
  if (!file) return;
  await flush();
  mergeServer(await api(`/api/projects/${project.id}/reference`,
    { method: "POST", body: file, headers: { "X-Filename": encodeURIComponent(file.name) } }));
}

function addShot() {
  const last = project.shots.at(-1) || {};
  project.shots.push({ action: "", shot_size: "Medium", camera_move: "Static", seconds: 4, sound: last.sound || "", transition: "cut", lead: true });
  save(true).then(() => select(project.shots.at(-1).id));
}

let toastTimer;
function toast(text) {
  const t = $("#toast"); t.textContent = text; t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, 2600);
}

let lastSignature = "";
async function poll() {
  try {
    jobs = await api("/api/jobs");
    presets.comfy = true;
    const sig = jobs.filter(j => j.project === project.id).map(j => j.id + j.state).join();
    if (sig !== lastSignature) {
      lastSignature = sig;
      mergeServer(await api(`/api/projects/${project.id}`));
      projects = await api("/api/projects");
    } else {
      paintBoard(); paintInspector(); paintPortrait();
      if (stage === "edit") { renderViewer(); paintTitleShot(); }
      if (stage === "screen") renderScreen();
    }
    renderStatus();
  } catch { presets.comfy = false; renderStatus(); }
}

// ---------------------------------------------------------------- wiring
$$(".stages button").forEach(b => b.onclick = () => setStage(b.dataset.stage));
$$("[data-goto]").forEach(b => b.onclick = () => setStage(b.dataset.goto));
$("#projectBtn").onclick = e => { e.stopPropagation(); renderProjectMenu(); $("#projectMenu").hidden = !$("#projectMenu").hidden; };
$("#newProject").onclick = async () => { $("#projectMenu").hidden = true; await flush(); createProject(); };
$("#statusPill").onclick = e => { e.stopPropagation(); $("#queue").hidden = !$("#queue").hidden; };
document.addEventListener("click", e => {
  if (!e.target.closest("#projectMenu, #projectBtn")) $("#projectMenu").hidden = true;
  if (!e.target.closest("#queue, #statusPill")) $("#queue").hidden = true;
});
document.addEventListener("keydown", e => { if (e.key === "Escape") { $("#projectMenu").hidden = true; $("#queue").hidden = true; } });
$("#cancelAll").onclick = () => post("/api/cancel").then(poll);
$("#renderFilm").onclick = async () => { await flush(); await post(`/api/projects/${project.id}/render`); toast("Rendering everything that's missing"); poll(); };

for (const id of ["title", "idea", "logline", "scene", "continuity", "cast"]) $("#" + id).oninput = e => {
  project[id] = e.target.value;
  if (id === "title") { renderHeader(); paintPalette(); }
  if (id === "cast") paintLeadAI();
  save();
};
$("#castBtn").onclick = async () => {
  if (!project.cast?.trim()) { $("#cast").focus(); toast("Describe the lead first"); return; }
  await flush(); await post(`/api/projects/${project.id}/cast`); poll();
};
for (const input of [$("#refInput"), $("#refInput2")]) input.onchange = e => uploadReference(e.target.files[0]);
const drop = $("#refDrop");
drop.ondragover = e => { e.preventDefault(); drop.classList.add("drag"); };
drop.ondragleave = () => drop.classList.remove("drag");
drop.ondrop = e => { e.preventDefault(); drop.classList.remove("drag"); uploadReference(e.dataTransfer.files[0]); };
$("#addShot").onclick = addShot;
$("#aiLead").onclick = () => writeLead((project.cast || "").trim() ? "refine" : "write");
$("#aiPhoto").onclick = () => writeLead("from photo");
$("#aiContinuity").onclick = () => writeLead("continuity");
$("#aiUndo").onclick = async () => { clearTimeout(saveTimer); mergeServer(await post(`/api/projects/${project.id}/undo-story`)); };
$("#aiEverything").onclick = () => writeStory("everything");
$$("[data-ai]").forEach(b => b.onclick = () => writeStory(b.dataset.ai));
$("#idea").onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); writeStory("everything"); } };
$$("[data-pal]").forEach(input => input.oninput = () => {
  const [ink, accent, glow, bg] = effectivePalette();
  project.palette = { bg, ink, accent, glow, ...(project.palette || {}), [input.dataset.pal]: input.value.toUpperCase() };
  applyTheme(); save();
});
$("#paletteReset").onclick = () => { delete project.palette; project.palette = null; applyTheme(); save(); };

$$("#viewerTabs button").forEach(b => b.onclick = () => { view = b.dataset.view; renderViewer(); });
$("#finish").onchange = e => { project.finish = e.target.checked; save(); };
$("#stitch").onclick = async () => { await flush(); await post(`/api/projects/${project.id}/stitch`); view = "film"; poll(); };
for (const id of ["mTitle", "mStamps", "mCredits"]) $("#" + id).onchange = saveMotion;
for (const id of ["mSubtitle", "mMaterial", "mCreditsLines", "mTrailerLines"]) $("#" + id).oninput = saveMotion;
$$("[data-style]").forEach(b => b.onclick = () => {
  $$("[data-style]").forEach(x => x.classList.toggle("on", x === b));
  $(".title-kinetic").hidden = b.dataset.style === "inworld"; $(".title-inworld").hidden = b.dataset.style !== "inworld";
  saveMotion();
});
const queueTitle = frame => async () => { await flush(); await post(`/api/projects/${project.id}/title-shot`, { frame }); poll(); };
$("#makeTitle").onclick = queueTitle(true);
$("#rerollTitleMotion").onclick = queueTitle(false);
$("#mPreview").onclick = async () => { await flush(); await post(`/api/projects/${project.id}/motion-preview`); poll(); };
const cutTrailer = reroll => async () => { await flush(); await post(`/api/projects/${project.id}/trailer`, { reroll }); view = "trailer"; poll(); };
$("#cutTrailer").onclick = cutTrailer(false);
$("#newScore").onclick = cutTrailer(true);

$$("#screenTabs button").forEach(b => b.onclick = () => { screen = b.dataset.screen; renderScreen(); });
$("#master").onclick = async () => { await post(`/api/projects/${project.id}/master`); toast("Mastering in 1080p — about 5 minutes per shot"); poll(); };

init();
