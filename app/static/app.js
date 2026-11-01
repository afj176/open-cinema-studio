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
const shotLabel = id => { const i = shotIndex(id); return i < 0 ? "a deleted shot" : `Shot ${String(i + 1).padStart(2, "0")}`; };

// ---------------------------------------------------------------- lineage: what each frame is made from
const recipeOf = shot => (shot.takes?.keyframe || []).find(t => t.name === shot.keyframe)?.recipe || null;
const leadIn = shot => shot.lead !== false && !!project.reference;
const plateOf = () => project.world?.plate || null;
const plateTake = () => (project.world?.takes || []).find(t => t.name === plateOf()) || null;
const worldNow = () => ({ scene: project.scene || "", look: project.look || "", aspect: project.aspect || "" });
const plateStale = () => !!plateTake() && JSON.stringify(plateTake().of) !== JSON.stringify(worldNow());

function plannedRecipe(shot, i) {  // what the next New frame will be made from (mirrors studio._run_keyframe)
  if (i > 0 && shot.transition === "continue") return { kind: "continue", from: project.shots[i - 1].id, steps: [`Last frame of shot ${i}`] };
  const drawn = shot.sketch && !sketchStale(shot);
  return { kind: "shot", world: plateOf(), lead: leadIn(shot) ? project.reference : null, sketch: drawn ? shot.sketch : null,
    steps: [...(plateOf() && !plateStale() ? [] : [`HiDream-O1 · paints ${plateOf() ? "a new" : "the"} world plate first`]),
      ...(drawn ? [] : [`Qwen-Image-Edit 2511 · ${shot.sketch ? "redraws" : "draws"} the storyboard first`]),
      "Qwen-Image-Edit 2511 · the world + the lead + the storyboard · 4 steps"] };
}

function staleness(shot) {  // why the current frame no longer matches the film ("" when it does)
  const r = recipeOf(shot);
  if (!shot.keyframe || !r || r.kind !== "shot") return "";
  if (leadIn(shot) && r.lead !== project.reference) return r.lead ? "Lead changed" : "Made before the lead";
  if (r.world !== plateOf()) return "World changed";
  if (r.action !== undefined && r.action !== (shot.action || "")) return "Action changed";
  if (r.shot_size !== undefined && (r.shot_size !== shot.shot_size || r.camera_move !== shot.camera_move)) return "Framing changed";
  return "";
}
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
  const [aw, ah] = (project.aspect || "16:9").split(":").map(Number);
  root.setProperty("--frame", `${aw} / ${ah || 1}`);  // storyboard frames take the film's aspect
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
  $("#projectList").innerHTML = projects.map(p => `<li class="film-row" data-id="${p.id}">
    <button type="button" class="film-open ${p.id === project.id ? "current" : ""}"><span>${escapeHtml(p.title)}</span><small>${p.shots} shot${p.shots === 1 ? "" : "s"}</small></button>
    <button type="button" class="film-del" title="Delete this film" aria-label="Delete ${escapeHtml(p.title)}"><svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/></svg></button></li>`).join("");
  $$("#projectList .film-row").forEach(row => {
    const id = row.dataset.id, film = projects.find(p => p.id === id);
    $(".film-open", row).onclick = async () => { $("#projectMenu").hidden = true; await flush(); openProject(id); };
    $(".film-del", row).onclick = e => {  // confirm inline: embedded browsers silently answer confirm() with "no"
      e.stopPropagation();
      row.classList.add("confirming");
      row.innerHTML = `<span class="film-ask">Delete “${escapeHtml(film.title)}” for good?</span>
        <button type="button" class="film-yes">Delete</button><button type="button" class="film-no">Cancel</button>`;
      $(".film-no", row).onclick = ev => { ev.stopPropagation(); renderProjectMenu(); };
      $(".film-yes", row).onclick = ev => { ev.stopPropagation(); deleteFilm(film); };
      $(".film-no", row).focus();
    };
  });
}

async function deleteFilm(film) {
  if (film.id === project.id) clearTimeout(saveTimer);  // don't write the deleted film back
  const res = await fetch(`/api/projects/${film.id}/delete`, { method: "POST" });
  const body = await res.json();
  if (!res.ok) { toast(body.error || "Couldn't delete this film"); renderProjectMenu(); return; }
  projects = body;
  if (film.id === project.id) {
    $("#projectMenu").hidden = true;
    if (projects.length) await openProject(projects[0].id); else await createProject();
  } else renderProjectMenu();
  toast(`“${film.title}” deleted`);
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
  renderBeats();
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
  $$("button", aspects).forEach(b => b.onclick = () => { project.aspect = b.textContent; $$("button", aspects).forEach(x => x.classList.toggle("on", x === b)); applyTheme(); save(); });
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
  paintLeadUsage();
  paintWorld();
  // Gemma's description of the portrait: the words every frame and shot prompt carries about this face
  const describing = busyFor(j => j.kind === "describe_lead" || (j.kind === "cast" && j.state === "running"));
  const note = project.lead_identity_of === project.reference ? project.lead_identity : "";
  $("#identityNote").hidden = !project.reference;
  $("#identityText").textContent = describing ? "Looking at the portrait…" : note || "Not described yet. Render film describes it first, or press Describe again.";
  $("#identityText").classList.toggle("pending", !note || !!describing);
  $("#redescribe").disabled = !!describing;
}

const STORY_TARGET_FIELDS = {
  everything: ["titleField", "loglineField", "worldField", "lookField", "castField", "continuityField", "sparkField", "beatsField"],
  title: ["titleField"], logline: ["loglineField"], world: ["worldField"], look: ["lookField"], trailer: ["trailerField"],
  beats: ["beatsField"],
};
const AI_FIELDS = ["titleField", "loglineField", "worldField", "lookField", "castField", "continuityField", "sparkField",
  "trailerField", "beatsField"];

function paintLeadAI() {
  const job = busyFor(j => j.kind === "write_lead" || j.kind === "write_story");
  const status = job ? (job.state === "running" ? `${job.label}… ${Math.round(job.elapsed)}s` : `${job.label} · queued`) : "";
  let writing = [];
  if (job?.kind === "write_story") writing = STORY_TARGET_FIELDS[job.target] || [];
  paintBeatGhosts(job?.kind === "write_story" ? job : null);
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
  $("#trailerUndo").hidden = !!job || !("motion" in ((project.story_history || []).at(-1) || {}));
}

async function writeStory(target, count) {
  await flush();
  await post(`/api/projects/${project.id}/write-story`, { target, count });
  poll();
}

function openBeatMenu(anchor, fromAdd) {  // ✨ Beats and + Add beat: continue the story with Gemma, or by hand
  const menu = $("#beatMenu"), n = beatsOf().length;
  const auto = project.auto_render !== false;
  menu.innerHTML = `<p class="bm-title">Continue the story</p>
    <p class="hint">Gemma writes the next beats after beat ${n}, following on from the story so far${auto ? ", then their shots and videos" : ", then you write their shots"}.</p>
    <div class="bm-counts">${[1, 2, 3, 5].map(c => `<button type="button" class="ai" data-more="${c}">+ ${c} beat${c > 1 ? "s" : ""}</button>`).join("")}</div>
    <div class="bm-foot">${fromAdd ? `<button type="button" class="link" data-own>Write one myself</button>`
      : `<button type="button" class="link" data-redo title="Gemma writes a new set of beats; shots keep their numbers">Rewrite all beats</button>`}
      <button type="button" class="link" data-close>Cancel</button></div>`;
  menu.hidden = false;
  const box = anchor.getBoundingClientRect(), card = $("#beatsField").getBoundingClientRect();
  menu.style.top = `${box.bottom - card.top + 8}px`;
  menu.style.left = `${Math.max(12, Math.min(box.left - card.left, card.width - 340))}px`;
  $$("[data-more]", menu).forEach(b => b.onclick = () => { menu.hidden = true; writeStory("more beats", Number(b.dataset.more)); });
  $("[data-own]", menu)?.addEventListener("click", () => {
    menu.hidden = true; project.beats = [...beatsOf(), ""]; renderBeats(); $$("#beats .beat-text").at(-1)?.focus();
  });
  $("[data-redo]", menu)?.addEventListener("click", () => { menu.hidden = true; writeStory("beats"); });
  $("[data-close]", menu).onclick = () => { menu.hidden = true; };
  $("[data-more]", menu).focus();
}

function paintBeatGhosts(job) {  // placeholder rows while Gemma continues the story
  const list = $("#beats"), want = job?.target === "more beats" ? Number(job.count || 1) : 0;
  $$(".beat.ghost", list).forEach((g, n) => { if (n >= want) g.remove(); });
  for (let n = $$(".beat.ghost", list).length; n < want; n++) {
    const li = document.createElement("li");
    li.className = "beat ghost";
    li.innerHTML = `<span class="beat-num">${beatsOf().length + n + 1}</span><div class="beat-main"><p class="line"></p><p class="line short"></p></div>`;
    list.appendChild(li);
  }
  const first = $(".beat.ghost .line", list);
  if (first) first.textContent = job.state === "running" ? `${job.label} · ${Math.round(job.elapsed)}s` : `${job.label} · queued`;
  $("#addBeat").disabled = !!want;
}

// ---------------------------------------------------------------- the storyboard as a comic strip
let beatView = store.get("beatView") === "strip" ? "strip" : "beats";

function setBeatView(view) {
  beatView = view; store.set("beatView", view);
  $$("#beatView button").forEach(b => b.classList.toggle("on", b.dataset.view === view));
  $("#beats").hidden = view === "strip";
  $("#addBeat").hidden = view === "strip";
  $("#strip").hidden = view !== "strip";
  paintStrip();
}

function paintStrip() {
  const strip = $("#strip");
  if (strip.hidden) return;
  const sig = JSON.stringify([beatsOf(), project.shots.map(s => [s.id, s.beat, s.sketch])]);
  if (strip.dataset.sig === sig) return;
  strip.dataset.sig = sig;
  const panels = project.shots.filter(s => s.action?.trim());
  if (!panels.length) { strip.innerHTML = `<p class="hint">No shots yet. Write shots and they're drawn here as a comic strip.</p>`; return; }
  strip.innerHTML = panels.map(s => {  // just the drawings: the words and numbers live in the Beats view
    const i = shotIndex(s.id);
    return `<button type="button" class="panel" data-id="${s.id}" title="Shot ${i + 1}: ${escapeHtml(s.action)}">
      ${s.sketch ? `<img src="${media(s.sketch)}" alt="Storyboard drawing for shot ${i + 1}">` : `<span class="panel-empty">✎ Not drawn yet</span>`}</button>`;
  }).join("");
  $$(".panel", strip).forEach(b => b.onclick = () => { setStage("shots"); select(b.dataset.id); });
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
  if (JSON.stringify(project.beats || []) !== JSON.stringify(fresh.beats || [])) {
    project.beats = fresh.beats || []; renderBeats(); flash("beatsField");
  }
  if (JSON.stringify(project.motion || null) !== JSON.stringify(fresh.motion || null)) {
    project.motion = fresh.motion; $("#mTrailerLines").value = motionState().trailer.lines; flash("trailerField");
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
  paintShotsHeading();
  board.innerHTML = "";
  project.shots.forEach((shot, i) => {
    const card = document.createElement("article");
    card.className = "card" + (shot.id === selected ? " selected" : "");
    card.dataset.id = shot.id;
    card.tabIndex = 0;
    card.innerHTML = `<div class="media"><img alt="" hidden><video muted loop playsinline preload="none" hidden></video>
      <div class="empty">No frame yet</div><div class="busy" hidden></div>
      <span class="num">${String(i + 1).padStart(2, "0")}</span><span class="badges"></span>
      <img class="lead-dot" alt="" title="The lead is in this shot" hidden>
      <button type="button" class="card-pause" hidden></button></div>
      <div class="meta"><span class="beat-chip" hidden></span><p class="action"></p><div class="facts"><span class="mini-cam"><span class="cam-scene"><span></span></span></span>
      <span class="move"></span><span>·</span><span class="size"></span><span>·</span><span class="secs"></span></div></div>`;
    card.onclick = () => select(shot.id);
    $(".card-pause", card).onclick = e => { e.stopPropagation(); pauseShot(project.shots[shotIndex(shot.id)], !project.shots[shotIndex(shot.id)].paused); };
    card.onkeydown = e => { if (e.key === "Enter") select(shot.id); };
    const vid = $("video", card);
    card.onmouseenter = () => { if (shot.video) { if (!vid.src) vid.src = media(shot.video); vid.play().catch(() => {}); } };
    card.onmouseleave = () => vid.pause();
    board.appendChild(card);
    paintCard(card, shot, i);
  });
  const end = document.createElement("div");
  end.className = "add-card";
  end.innerHTML = `<button type="button" class="add-plain">+ Add shot</button>
    <button type="button" class="ai" data-next title="Gemma writes the next moment: the next beat no shot tells yet, or a new beat that continues the story">✨ Next shot</button>`;
  $(".add-plain", end).onclick = addShot;
  $("[data-next]", end).onclick = () => writeShots("next");
  board.appendChild(end);
  paintShotWriter();
}

function paintShotWriter() {  // the ✨ buttons, and placeholder cards while the writer works
  $("#autoRender").checked = project.auto_render !== false;
  const job = busyFor(j => j.kind === "write_shots");
  const status = job ? (job.state === "running" ? `${job.label} · ${Math.round(job.elapsed || 0)}s` : `${job.label} · queued`) : "";
  $("#writeShots").disabled = !!job;
  $("#shotCount").disabled = !!job;
  const plan = writePlan();
  $("#writeShots").textContent = job?.mode === "board" ? `Writing… ${Math.round(job.elapsed || 0)}s` : plan.label;
  $(".write-shots").title = plan.tip;
  $("#shotCount").hidden = plan.byBeat;
  $("#shotsUndo").hidden = !!job || !(project.shots_history || []).length;
  $$("[data-next], [data-act='rewrite']").forEach(b => { b.disabled = !!job; });
  const board = $("#board"), end = $(".add-card", board);
  const blanks = project.shots.filter(s => !isKept(s));
  const ghosts = !job ? 0 : job.mode === "board" ? (plan.byBeat ? plan.missing.length : Number(job.count)) || Number(job.count) : job.mode === "next" ? 1 : 0;
  // the board replaces blank shots and Gemma's unrendered drafts, so hide them while their replacements are written
  $$(".card", board).forEach(c => { c.hidden = ghosts > 0 && job.mode === "board" && blanks.some(s => s.id === c.dataset.id); });
  $$(".card.ghost", board).forEach((g, n) => { if (n >= ghosts) g.remove(); });
  for (let n = $$(".card.ghost", board).length; n < ghosts; n++) {
    const g = document.createElement("article");
    g.className = "card ghost";
    g.innerHTML = `<div class="media"><div class="empty"></div></div><div class="meta"><p class="line"></p><p class="line short"></p></div>`;
    board.insertBefore(g, end);
  }
  $$(".card.ghost .empty", board).forEach((e, n) => { e.textContent = n === 0 ? status : ""; });
  const ins = $("#inspector"), rewriting = job?.mode === "rewrite" && job.shot === selected;
  $(".ins-action", ins)?.classList.toggle("writing", !!rewriting);
  if ($(".ins-action", ins)) $(".ins-action", ins).dataset.status = rewriting ? status : "";
}

const isMade = s => !!(s.keyframe || s.video || (s.takes?.keyframe || []).length);
const isKept = s => isMade(s) || (!!s.action?.trim() && !s.ai);  // mirrors studio._run_write_shots

function writePlan() {  // what ✨ Write shots will do on this board
  const beats = beatsOf(), keep = project.shots.filter(isKept);
  const missing = beats.map((_, n) => n + 1).filter(b => !keep.some(s => s.beat === b));
  if (!keep.length) return { byBeat: !!beats.length, missing, label: "✨ Write shots",
    tip: beats.length ? `Gemma writes one shot for each of the ${beats.length} story beats, then they're drawn as a storyboard` : "Gemma plans the film shot by shot from the story, then the shots are drawn as a storyboard" };
  const drafts = project.shots.filter(s => !isKept(s) && s.action?.trim());
  if (drafts.length) return { byBeat: !!beats.length && !!missing.length, missing, label: "✨ Redraft shots",
    tip: `Gemma rewrites ${drafts.length === 1 ? "the unrendered draft" : `the ${drafts.length} unrendered drafts`}` +
      (beats.length && missing.length ? ` (beat${missing.length > 1 ? "s" : ""} ${missing.join(", ")})` : "") +
      ". Shots you wrote or edited, and rendered shots, stay." };
  if (beats.length && missing.length) return { byBeat: true, missing, label: "✨ Fill in the story",
    tip: `Gemma writes shots for beat${missing.length > 1 ? "s" : ""} ${missing.join(", ")}, which no kept shot tells yet. Your shots and rendered shots stay.` };
  if (beats.length) return { byBeat: false, missing: [], label: "✨ Continue the story",
    tip: "Every beat has a shot. Gemma writes the next moments of the story: new beats added to The story, each with its shot. Your shots stay." };
  return { byBeat: false, missing: [], label: "✨ Continue the film",
    tip: "Gemma continues the film from your last shot and brings it to an ending. Your shots and rendered shots stay." };
}

let seenFailures = null;
function noticeFailures() {  // the writer and the storyboard fail quietly in the queue otherwise
  const failed = jobs.filter(j => j.project === project.id && j.state === "failed" && ["write_shots", "sketch"].includes(j.kind));
  if (seenFailures === null) { seenFailures = new Set(failed.map(j => j.id)); return; }
  const fresh = failed.filter(j => !seenFailures.has(j.id));
  fresh.forEach(j => seenFailures.add(j.id));
  const j = fresh.at(-1);
  if (!j) return;
  if (j.kind === "write_shots") toast(`Gemma couldn't write the shots: ${j.error}`, "Try again", () => writeShots(j.mode, project.shots.find(s => s.id === j.shot)));
  else toast(`Couldn't draw the storyboard: ${j.error}`);
}

async function pauseShot(shot, paused) {
  await flush();
  mergeServer(await post(`/api/projects/${project.id}/shots/${shot.id}/${paused ? "pause" : "resume"}`));
  toast(paused ? `${shotLabel(shot.id)} paused; the rest carry on` : `${shotLabel(shot.id)} resumed`);
  poll();
}

async function writeShots(mode, shot) {
  await flush();
  await post(`/api/projects/${project.id}/write-shots`, { mode, shot: shot?.id, count: Number($("#shotCount").value) });
  poll();
}

async function undoShots() {
  await flush();
  mergeServer(await post(`/api/projects/${project.id}/undo-shots`), true);
  toast("Shots restored");
}

function paintCard(card, shot, i) {
  const img = $("img", card), vid = $("video", card), pic = shot.keyframe || shot.sketch;
  img.hidden = !pic;
  if (pic && img.dataset.src !== pic) { img.src = media(pic); img.dataset.src = pic; }
  card.classList.toggle("is-sketch", !shot.keyframe && !!shot.sketch);
  vid.hidden = !shot.video;
  if (shot.video && vid.dataset.src !== shot.video) { vid.dataset.src = shot.video; vid.removeAttribute("src"); }
  $(".empty", card).hidden = !!pic;
  const beat = shot.beat && beatsOf()[shot.beat - 1];
  const chip = $(".beat-chip", card);
  const loose = !beat && beatsOf().length && shot.action?.trim();
  chip.hidden = !beat && !loose;
  chip.classList.toggle("loose", !!loose);
  if (beat) { chip.textContent = `Beat ${shot.beat}`; chip.title = beat; }
  else if (loose) { chip.textContent = "Not in the story"; chip.title = "Pick a beat in the inspector, or ✨ Add to story"; }
  const action = $(".action", card);
  action.textContent = shot.action || "Describe what happens…";
  action.classList.toggle("empty", !shot.action);
  $(".move", card).textContent = shot.camera_move;
  $(".size", card).textContent = shot.shot_size;
  $(".secs", card).textContent = `${shot.seconds}s`;
  $(".cam-scene", card).style.animation = CAMERA_ANIM[shot.camera_move] || "";
  const badges = [];
  if (i > 0 && shot.transition !== "cut") badges.push(`<span class="badge">${JOINT_NAME[shot.transition].toUpperCase()}</span>`);
  if (shot.paused) badges.push(`<span class="badge warn">PAUSED</span>`);
  if (shot.lead === false) badges.push(`<span class="badge">NO LEAD</span>`);
  if (!shot.keyframe && shot.sketch) badges.push(`<span class="badge" title="The storyboard drawing; the frame will follow it">STORYBOARD</span>`);
  if (shot.ai) badges.push(`<span class="badge ai" title="Written by Gemma. Edit it to make it yours; a new Write shots replaces Gemma's unrendered drafts">✨</span>`);
  const stale = staleness(shot);
  if (stale) badges.push(`<span class="badge warn" title="Press New frame to rebuild it">${stale.toUpperCase()}</span>`);
  if (shot.video) badges.push(`<span class="badge accent">▶</span>`);
  const dot = $(".lead-dot", card);
  dot.hidden = !leadIn(shot);
  if (leadIn(shot) && dot.dataset.src !== project.reference) { dot.src = media(project.reference); dot.dataset.src = project.reference; }
  const last = jobs.filter(j => j.project === project.id && j.shot === shot.id).at(-1);
  if (last?.state === "failed") badges.push(`<span class="badge fail" title="${escapeHtml(last.error)}">FAILED</span>`);
  $(".badges", card).innerHTML = badges.join("");
  const job = busyFor(j => j.shot === shot.id);
  const busy = $(".busy", card);
  busy.hidden = !job && !shot.paused;
  card.classList.toggle("paused", !!shot.paused);
  if (shot.paused) busy.textContent = "Paused";
  else if (job) busy.textContent = job.state === "running" ? `${job.label}\n${Math.round(job.elapsed)}s` : `${job.label} · queued`;
  const pause = $(".card-pause", card);  // only while it has work to stop, or is stopped
  pause.hidden = !job && !shot.paused;
  pause.textContent = shot.paused ? "▶ Resume" : "❚❚ Pause";
  pause.title = shot.paused ? "Render this shot again from whatever changed" : "Stop this shot's rendering; the others carry on";
}

function paintShotsHeading() {
  const n = project.shots.length, rendered = project.shots.filter(s => s.video).length;
  $("#shotsHeading").textContent = `${n} shot${n === 1 ? "" : "s"} · ${rendered} rendered`;
}

function paintBoard() {
  paintShotsHeading();
  paintShotWriter();
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
      <button class="ghost small danger" data-act="del" ${project.shots.length < 2 ? 'disabled title="A film needs at least one shot"' : 'title="Delete"'}>Delete</button></div></div>
    <div class="ins-media"></div>
    <div class="strips"></div>
    <div class="ai-field ins-action"><div class="field-head"><span>What happens</span>
      <button type="button" class="ai small" data-act="rewrite" title="Gemma rewrites this shot to flow from the one before into the one after">✨ ${shot.action?.trim() ? "Rewrite" : "Write"}</button></div>
      <textarea class="grow" data-k="action" rows="3" placeholder="Describe the action, as you'd see it" aria-label="What happens">${escapeHtml(shot.action)}</textarea></div>
    ${beatsOf().length ? `<div class="beat-pick"><label>Story beat<select data-beat>${[`<option value="">Not in the story yet</option>`, ...beatsOf().map((b, n) =>
      `<option value="${n + 1}"${shot.beat === n + 1 ? " selected" : ""}>${n + 1} · ${escapeHtml(b.length > 70 ? b.slice(0, 68) + "…" : b)}</option>`)].join("")}</select></label>
      ${shot.beat ? "" : `<button type="button" class="ai small" data-act="place" title="Gemma writes the beat this shot tells and adds it to the story">✨ Add to story</button>`}</div>` : ""}
    <div class="ins-sketch"><div class="ins-sketch-img"></div><div class="ins-sketch-side"><b>Storyboard</b><span class="hint"></span>
      <button type="button" class="ghost small" data-act="sketch">Draw</button></div></div>
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
      <button class="ghost" data-act="keyframe" ${shot.transition === "continue" && i > 0 ? 'disabled title="One take: this shot starts from the last frame of the shot before"' : ""}>New frame</button>
      <label class="button ghost">Upload frame<input type="file" accept="image/*" hidden data-act="upload"></label>
      <button class="ghost" data-act="pause" hidden>Pause</button>
      <button class="primary" data-act="video">Render shot</button>
    </div>
    <section class="recipe">
      <div class="recipe-head"><span class="strip-label">How it was made</span></div>
      <div class="recipe-body"></div>
      <details class="prompts"><summary>Prompts the models receive</summary><div class="prompt-body"></div></details>
    </section>`;
  $(".cam-scene", ins).style.animation = CAMERA_ANIM[shot.camera_move] || "";
  requestAnimationFrame(() => growAll(ins));
  for (const field of $$("[data-k]", ins)) {
    const key = field.dataset.k;
    field.addEventListener(field.tagName === "SELECT" || field.type === "checkbox" ? "change" : "input", () => {
      shot[key] = field.type === "checkbox" ? field.checked : field.type === "number" ? Number(field.value) : field.value;
      if (key === "action") shot.ai = false;  // edited by you: a new Write shots keeps it
      if (key === "seconds" && !(shot.seconds >= 2 && shot.seconds <= 10)) return;  // wait for a valid length; blur clamps it
      if (key === "camera_move") { $(".cam-scene", ins).style.animation = CAMERA_ANIM[shot.camera_move] || ""; $(".ins-head .serif", ins).textContent = shot.camera_move; }
      const card = $(`.card[data-id="${shot.id}"]`);
      if (card) paintCard(card, shot, i);
      save();
    });
  }
  const secs = $('[data-k="seconds"]', ins);
  secs.onblur = () => {
    const v = Math.min(10, Math.max(2, Math.round(Number(secs.value) || 4)));
    if (secs.value !== String(v) || shot.seconds !== v) { secs.value = v; shot.seconds = v; paintCard($(`.card[data-id="${shot.id}"]`), shot, i); save(); }
  };
  $$("[data-tr]", ins).forEach(b => b.onclick = () => { shot.transition = b.dataset.tr; save(true); });
  $('[data-act="keyframe"]', ins).onclick = () => queueShot(shot, "keyframe");
  $('[data-act="video"]', ins).onclick = () => shot.paused ? pauseShot(shot, false) : queueShot(shot, "video");
  $('[data-act="pause"]', ins).onclick = () => pauseShot(shot, true);
  $('[data-act="upload"]', ins).onchange = e => uploadKeyframe(shot, e.target.files[0]);
  $('[data-act="dup"]', ins).onclick = () => {
    project.shots.splice(i + 1, 0, { ...shot, id: undefined, keyframe: null, video: null, takes: undefined, seed: undefined });
    save(true).then(() => select(project.shots[i + 1].id));
  };
  $('[data-act="rewrite"]', ins).onclick = () => writeShots("rewrite", shot);
  $('[data-act="sketch"]', ins).onclick = async () => { await flush(); await post(`/api/projects/${project.id}/shots/${shot.id}/sketch`); poll(); };
  $('[data-act="place"]', ins)?.addEventListener("click", () => writeShots("beat", shot));
  const beatSel = $("[data-beat]", ins);
  if (beatSel) beatSel.onchange = () => { shot.beat = beatSel.value ? Number(beatSel.value) : null; paintCard($(`.card[data-id="${shot.id}"]`), shot, i); save(true); };
  const del = $('[data-act="del"]', ins);  // no confirm(): embedded browsers silently answer "no"
  del.onclick = () => {
    if (project.shots.length < 2) return;
    if (!del.classList.contains("armed")) {
      del.classList.add("armed"); del.textContent = `Delete shot ${i + 1}?`;
      setTimeout(() => { del.classList.remove("armed"); del.textContent = "Delete"; }, 3000);
      return;
    }
    project.shots.splice(i, 1); selected = project.shots[Math.max(0, i - 1)].id; save(true);
    toast(`Shot ${i + 1} deleted`);
  };
  paintInspector();
}

function paintSketch(shot) {
  const ins = $("#inspector"), box = $(".ins-sketch", ins);
  if (!box) return;
  const job = busyFor(j => j.kind === "sketch" && j.shot === shot.id) ||
    busyFor(j => j.kind === "keyframe" && j.shot === shot.id && j.state === "running" && /storyboard/.test(j.label));
  const stale = shot.sketch && sketchStale(shot);
  const img = $(".ins-sketch-img", box), want = shot.sketch || "";
  if (img.dataset.src !== want) { img.dataset.src = want; img.innerHTML = want ? `<img src="${media(want)}" alt="Storyboard drawing">` : "✎"; }
  $(".hint", box).textContent = job ? (job.state === "running" ? `Drawing · ${Math.round(job.elapsed)}s` : "Drawing · queued")
    : !shot.sketch ? "Drawn from the world and the lead before the first frame, which then follows its composition."
    : stale ? "The shot changed since this was drawn. It's redrawn before the next frame."
    : "The next frame follows this composition and pose.";
  const b = $('[data-act="sketch"]', box);
  b.disabled = !!job || !shot.action?.trim();
  b.textContent = shot.sketch ? "Redraw" : "Draw";
  box.classList.toggle("stale", !!stale);
}

function paintInspector() {
  const ins = $("#inspector"), i = shotIndex(selected);
  if (i < 0 || !$(".ins-media", ins)) return;
  const shot = project.shots[i], box = $(".ins-media", ins);
  paintSketch(shot);
  const working = busyFor(j => j.shot === shot.id);
  $('[data-act="pause"]', ins).hidden = !working || !!shot.paused;
  $('[data-act="video"]', ins).textContent = shot.paused ? "▶ Resume" : "Render shot";
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
  paintRecipe(shot, i);
  const kp = frames.find(t => t.name === shot.keyframe)?.prompt || shot.keyframe_prompt;
  const mp = vids.find(t => t.name === shot.video)?.prompt || shot.motion_prompt;
  const pb = $(".prompt-body", ins);
  const psig = (kp || "") + "|" + (mp || "");
  if (pb.dataset.sig !== psig) {
    pb.dataset.sig = psig;
    const ip = recipeOf(shot)?.identity_prompt;
    pb.innerHTML = (kp ? `<div class="strip-label">Frame</div><p>${escapeHtml(kp)}</p>` : "") +
      (ip ? `<div class="strip-label">Identity pass</div><p>${escapeHtml(ip)}</p>` : "") +
      (mp ? `<div class="strip-label">Motion &amp; sound</div><p>${escapeHtml(mp)}</p>` : "") ||
      `<p class="hint">Prompts appear after the first render.</p>`;
  }
}

function paintRecipe(shot, i) {
  const ins = $("#inspector"), body = $(".recipe-body", ins);
  if (!body) return;
  const made = recipeOf(shot), r = made || (shot.keyframe ? null : plannedRecipe(shot, i));
  const stale = staleness(shot);
  const sig = JSON.stringify([made, r, stale, shot.keyframe, shot.video, shot.seconds, shot.camera_move,
    shot.sound, project.reference, plateOf()]);
  if (body.dataset.sig === sig) return;
  body.dataset.sig = sig;
  if (!r || !["shot", "continue", "upload"].includes(r.kind)) {  // made before the world plate
    body.innerHTML = `<div class="recipe-stale"><span>Made before the world plate. Rebuild it so this shot uses the world and the lead.</span>
      <button type="button" class="ghost small" data-refresh>New frame</button></div>`;
    $("[data-refresh]", body).onclick = () => queueShot(shot, "keyframe");
    return;
  }
  const ing = (src, title, sub, go) => `<button type="button" class="ingredient" data-go="${go}">
    ${src ? `<img src="${src}" alt="">` : `<span class="ing-text">${title === "The world" ? "¶" : title === "The storyboard" ? "✎" : "↺"}</span>`}
    <b>${escapeHtml(title)}</b><small>${escapeHtml(sub)}</small></button>`;
  const inputs = [];
  if (r.kind === "shot") inputs.push(ing(r.world ? media(r.world) : "", "The world", r.world ? "Place, light and grade" : "Painted first", "world"));
  if (r.lead) inputs.push(ing(media(r.lead), "The lead", "Face and wardrobe", "story"));
  if (r.kind === "shot") inputs.push(ing(r.sketch ? media(r.sketch) : "", "The storyboard",
    r.sketch ? "Composition and pose" : made ? "Not used" : "Drawn first", "sketch"));
  if (r.kind === "continue") inputs.push(ing(media(project.shots[shotIndex(r.from)]?.keyframe), shotLabel(r.from), "Its last frame", "shot:" + r.from));
  if (r.kind === "upload") inputs.push(ing(media(shot.keyframe), "Your frame", "Uploaded", ""));
  const steps = [...(r.steps || [])];
  const drawing = r.sketch && (shot.sketches || []).find(t => t.name === r.sketch);
  if (drawing) {  // the storyboard is the first step: what it was drawn from
    const from = [drawing.plain ? "the world in words" : "the world", drawing.of?.reference ? "the lead" : "",
      drawing.before ? `the panel before${drawing.before === project.shots[i - 1]?.sketch ? ` (${shotLabel(project.shots[i - 1].id)})` : ""}` : ""];
    steps.unshift(`Qwen-Image-Edit 2511 · draws the storyboard from ${from.filter(Boolean).join(" + ")} · half size`);
  }
  const video = `LTX 2.5 · ${shot.seconds}s · ${shot.camera_move.toLowerCase()}${shot.sound ? " · with sound" : ""}`;
  body.innerHTML = `
    <p class="recipe-when">${made ? "Made from" : "The next frame will be made from"}</p>
    ${stale ? `<div class="recipe-stale"><span>${stale}: this frame no longer matches the film.</span><button type="button" class="ghost small" data-refresh>New frame</button></div>` : ""}
    <div class="ingredients">${inputs.join("")}</div>
    ${r.identity ? `<p class="recipe-told"><b>Told about the lead:</b> ${escapeHtml(r.identity)}</p>` : ""}
    <ol class="recipe-steps">${steps.map(s => `<li>${escapeHtml(s)}</li>`).join("")}
      <li class="${shot.video ? "" : "next"}">${escapeHtml(video)}${shot.video ? "" : " · press Render shot"}</li></ol>
    ${!leadIn(shot) && shot.lead !== false ? `<p class="hint">No lead portrait yet: cast one on the Story page so every shot keeps the same face.</p>` : ""}`;
  $$("[data-go]", body).forEach(b => b.onclick = () => {
    const go = b.dataset.go;
    if (go === "story") { setStage("story"); $("#refDrop").scrollIntoView({ behavior: "smooth", block: "center" }); }
    else if (go === "world") { setStage("story"); $(".world-plate").scrollIntoView({ behavior: "smooth", block: "center" }); }
    else if (go.startsWith("shot:")) select(go.slice(5));
    else if (go === "sketch") $(".ins-sketch", ins)?.scrollIntoView({ behavior: "smooth", block: "center" });
  });
  const refresh = $("[data-refresh]", body);
  if (refresh) refresh.onclick = () => queueShot(shot, "keyframe");
}

// ---------------------------------------------------------------- story: beats and their storyboard
const beatsOf = () => project.beats || [];

function renderBeats() {
  const list = $("#beats");
  list.innerHTML = "";
  list.dataset.sig = "";  // the rows are new, so their shots must be painted again
  beatsOf().forEach((text, n) => {
    const li = document.createElement("li");
    li.className = "beat";
    li.innerHTML = `<span class="beat-num">${n + 1}</span>
      <div class="beat-main"><textarea class="grow beat-text" rows="1" aria-label="Beat ${n + 1}" placeholder="What happens in this beat?"></textarea>
        <div class="beat-shots"></div></div>
      <button type="button" class="beat-del" title="Remove this beat" aria-label="Remove beat ${n + 1}">×</button>`;
    const area = $("textarea", li);
    area.value = text;
    area.oninput = () => { project.beats[n] = area.value; save(); };
    area.onblur = () => { if (!area.value.trim()) removeBeat(n); };
    $(".beat-del", li).onclick = () => removeBeat(n);
    list.appendChild(li);
  });
  if (!beatsOf().length) list.innerHTML = `<li class="beats-empty hint">No beats yet. ✨ Beats writes them from the logline, or Generate the whole story writes everything.</li>`;
  requestAnimationFrame(() => growAll(list));
  paintBeatShots();
  setBeatView(beatView);
}

function removeBeat(n) {  // shots keep telling the same moment: later beats move up, this beat's shots have none
  project.beats.splice(n, 1);
  for (const s of project.shots) if (s.beat === n + 1) s.beat = null; else if (s.beat > n + 1) s.beat -= 1;
  renderBeats(); save(true);
}

function picture(shot) { return shot.keyframe ? media(shot.keyframe) : shot.sketch ? media(shot.sketch) : ""; }

function paintBeatShots() {  // under each beat, the shots that tell it: frame if there is one, else the drawing
  const sig = JSON.stringify([beatsOf().length, project.shots.map(s => [s.id, s.beat, s.keyframe, s.sketch, !!s.video, !!s.action?.trim()])]);
  const list = $("#beats");
  if (list.dataset.sig === sig) return;
  list.dataset.sig = sig;
  const thumb = s => {  // the drawing always stays; a rendered frame comes after it, never instead of it
    const i = shotIndex(s.id), num = String(i + 1).padStart(2, "0");
    const drawn = s.sketch ? `<span class="beat-pic sketch"><img src="${media(s.sketch)}" alt="Storyboard drawing"><b>${num}</b></span>`
      : `<span class="beat-pic sketch empty"><span>✎</span><b>${num}</b></span>`;
    const made = s.keyframe ? `<span class="beat-arrow" aria-hidden="true">→</span>
      <span class="beat-pic"><img src="${media(s.keyframe)}" alt="Frame">${s.video ? `<i title="Rendered">▶</i>` : ""}</span>` : "";
    return `<button type="button" class="beat-shot" data-id="${s.id}" title="${escapeHtml(s.action || "")}">${drawn}${made}</button>`;
  };
  $$(".beat:not(.loose)", list).forEach((li, n) => {
    const shots = project.shots.filter(s => s.beat === n + 1);
    $(".beat-shots", li).innerHTML = (shots.length > 1 ? `<span class="beat-count">${shots.length} shots</span>` : "") +
      (shots.map(thumb).join("") || `<span class="hint">No shot tells this beat yet</span>`);
  });
  // shots that aren't in the story sit where they are in the film, so the page never shows less film than exists
  $$(".beat.loose", list).forEach(li => li.remove());
  if (beatsOf().length) {
    const rows = [];  // [beat the row follows (0 = before the first), [shots]]
    let after = 0;
    for (const s of project.shots) {
      if (s.beat && s.beat <= beatsOf().length) { after = s.beat; continue; }
      if (!s.action?.trim()) continue;
      const row = rows.at(-1);
      if (row && row[0] === after && row.end === project.shots.indexOf(s) - 1) { row[1].push(s); row.end++; }
      else { const r = [after, [s]]; r.end = project.shots.indexOf(s); rows.push(r); }
    }
    for (const [beat, shots] of rows.reverse()) {
      const li = document.createElement("li");
      li.className = "beat loose";
      li.innerHTML = `<span class="beat-num">·</span><div class="beat-main"><p class="loose-head">Not in the story yet</p>
        <div class="beat-shots">${shots.map(s => `<span class="loose-shot">${thumb(s)}
          <button type="button" class="ai small" data-place="${s.id}" title="Gemma writes the beat this shot tells and adds it to the story">✨ Add to story</button></span>`).join("")}</div></div>`;
      const anchor = $$(".beat:not(.loose)", list)[beat - 1];
      if (anchor) anchor.after(li); else list.prepend(li);
    }
    $$("[data-place]", list).forEach(b => b.onclick = () => writeShots("beat", project.shots[shotIndex(b.dataset.place)]));
  }
  $$(".beat-shot", list).forEach(b => b.onclick = () => { setStage("shots"); select(b.dataset.id); });
  $("#drawBoard").hidden = !project.shots.some(s => s.action?.trim() && !s.sketch) || !!busyFor(j => j.kind === "sketch");
  paintStrip();
}

function sketchStale(shot) {  // mirrors studio._current_sketch: is the drawing from today's shot, world and lead?
  const take = (shot.sketches || []).find(t => t.name === shot.sketch);
  if (!take) return !!shot.sketch;
  const of = take.of || {};
  return of.action !== (shot.action || "") || of.shot_size !== shot.shot_size || of.camera_move !== shot.camera_move
    || of.lead !== (shot.lead !== false) || of.world !== plateOf() || plateStale()
    || of.reference !== (shot.lead !== false ? project.reference || null : null);
}

function paintWorld() {  // the Story page shows the world plate every shot is made in
  const img = $("#worldImg"), plate = plateOf();
  img.hidden = !plate;
  if (plate && img.dataset.src !== plate) { img.src = media(plate); img.dataset.src = plate; }
  $("#worldEmpty").hidden = !!plate;
  const job = busyFor(j => j.kind === "world");
  $("#worldBusy").hidden = !job;
  if (job) $("#worldBusy").textContent = job.state === "running" ? `${job.label} · ${Math.round(job.elapsed)}s` : "Painting · queued";
  $("#worldBtn").disabled = !!job;
  $("#worldBtn").textContent = plate ? "New world plate" : "Paint the world";
  $("#worldStale").hidden = !plateStale();
  const box = $("#worldTakes"), takes = project.world?.takes || [];
  const sig = JSON.stringify([takes.map(t => t.name), plate]);
  if (box.dataset.sig === sig) return;
  box.dataset.sig = sig; box.innerHTML = "";
  if (takes.length < 2) return;
  takes.forEach((t, n) => {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = `W${n + 1}`; b.classList.toggle("on", t.name === plate);
    b.title = t.empty === false ? "Gemma saw someone in this plate" : "Empty";
    b.onclick = async () => mergeServer(await post(`/api/projects/${project.id}/world/take`, { name: t.name }));
    box.appendChild(b);
  });
}

function paintLeadUsage() {  // the Story page shows where the lead appears and which frames are out of date
  const box = $("#leadUsage"), using = project.shots.map((s, i) => ({ s, i })).filter(({ s }) => s.lead !== false);
  const stale = using.filter(({ s }) => staleness(s)).length;
  $("#leadUsageHint").textContent = !project.reference ? "Cast the lead so every shot keeps one face"
    : `In ${using.length} of ${project.shots.length} shot${project.shots.length === 1 ? "" : "s"}` + (stale ? ` · ${stale} need${stale === 1 ? "s" : ""} a new frame` : "");
  box.hidden = !project.reference || !using.length;
  const sig = JSON.stringify(using.map(({ s }) => [s.id, s.keyframe, staleness(s)]));
  if (box.dataset.sig === sig) return;
  box.dataset.sig = sig;
  box.innerHTML = using.map(({ s, i }) => `<button type="button" class="usage ${staleness(s) ? "stale" : ""}" data-id="${s.id}" title="${staleness(s) || "Uses this lead"}">
    ${s.keyframe ? `<img src="${media(s.keyframe)}" alt="">` : `<span></span>`}<small>${String(i + 1).padStart(2, "0")}${staleness(s) ? " · re-frame" : ""}</small></button>`).join("");
  $$(".usage", box).forEach(b => b.onclick = () => { setStage("shots"); select(b.dataset.id); });
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

function posterFrame() {  // the film's opening image, shown before play
  const m = motionState(), title = project.title_shot?.keyframe;
  const frame = m.title.on && m.title.style === "inworld" && title ? title : project.shots[0]?.keyframe;
  return frame ? media(frame) : "";
}

function renderViewer() {
  $$("#viewerTabs button").forEach(b => { b.classList.toggle("on", b.dataset.view === view); b.disabled = b.dataset.view === "trailer" && !project.trailer; });
  const src = view === "trailer" ? project.trailer : project.film;
  const v = $("#viewer");
  if (src && v.dataset.src !== src) { v.src = media(src); v.dataset.src = src; }
  if (v.getAttribute("poster") !== posterFrame()) v.poster = posterFrame();
  v.hidden = !src;
  $("#viewerEmpty").hidden = !!src;
  const total = project.shots.reduce((s, x) => s + Number(x.seconds || 0), 0);
  const done = project.shots.filter(s => s.video).length;
  const length = v.duration > 0 && src ? `${Math.round(v.duration)}s` : `about ${total}s`;  // the cut adds titles and credits
  $("#viewerInfo").textContent = src ? (view === "trailer" ? `Trailer · ${length} · score composed by LTX`
    : `${project.shots.length} shot${project.shots.length === 1 ? "" : "s"} · ${length}`) : `${done}/${project.shots.length} shots rendered`;
  const cutting = busyFor(j => j.kind === "stitch");
  $("#stitch").disabled = !!cutting;
  $("#stitch").textContent = cutting ? (cutting.state === "running" ? "Cutting…" : "Queued…")
    : done < project.shots.length ? "Render & cut" : project.film ? "Re-cut film" : "Cut film";
  $("#stitch").title = done < project.shots.length ? "Renders the missing shots, then cuts the film" : "";
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
  const made = (unit.takes?.keyframe || []).find(t => t.name === unit.keyframe)?.recipe;
  $("#titleStale").hidden = !(unit.keyframe && (!made || made.world !== plateOf()));
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
    const kinetic = i === 0 && m.title.on && m.title.style !== "inworld";  // the cut puts the kinetic title on shot 1
    const label = kinetic ? "MAIN TITLE" : m.stamps.on ? `SHOT ${String(i + 1).padStart(2, "0")}` : "";
    layer(shot.seconds, label, true);
  });
  if (m.credits.on) {
    pic.appendChild(Object.assign(document.createElement("button"), { className: "joint cut", textContent: JOINT.cut, disabled: true }));
    const cards = (m.credits.lines || project.motion_defaults?.credits || "").split("\n").filter(Boolean).length;
    pic.appendChild(clip(3, `<b>CREDITS</b><small>${cards} card${cards === 1 ? "" : "s"}</small>`, ""));
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
  if (v.getAttribute("poster") !== posterFrame()) v.poster = posterFrame();
  v.hidden = !src;
  $("#screenEmpty").hidden = !!src;
  $("#screenEmpty").textContent = project.film ? "" : "Nothing to screen yet — render the shots and cut the film.";
  $("#screenTitle").textContent = project.title;
  $("#screenLogline").textContent = project.logline || "";
  // what is actually playing: its real length and frame size once the video has loaded
  const facts = v.duration > 0 && src ? [`${Math.round(v.duration)}s`, `${v.videoWidth}×${v.videoHeight}`] : [];
  const n = project.shots.length;
  $("#screenInfo").textContent = [{ master: "1080p master · SeedVR2", film: `${n} shot${n === 1 ? "" : "s"}`,
    trailer: "Trailer · score composed by LTX" }[screen], ...facts].join(" · ") + (project.finish && screen !== "trailer" ? " · film finish" : "");
  const dl = $("#download"), safe = (project.title || "Untitled film").replace(/[\\/:*?"<>|]+/g, " ").trim();
  dl.hidden = !src; dl.href = media(src); dl.download = `${safe}${screen === "film" ? "" : " " + screen}.mp4`;
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
  const revised = (fresh.shots_rev || 0) !== (project.shots_rev || 0);
  const wrote = revised && (fresh.shots_history || []).length >= (project.shots_history || []).length;
  if (rerender || !sameShots || revised) {
    if (wrote) {
      const added = fresh.shots.find(s => !project.shots.some(p => p.id === s.id));
      if (added) selected = added.id;
      const grew = (fresh.beats || []).length - (project.beats || []).length;
      toast(grew > 0 ? (!added ? "Added to the story" : grew === 1 ? `Beat ${(fresh.beats || []).length} added to the story, with its shot`
        : `The story grew by ${grew} beats, each with its shot`)
        : added ? "Shots written by Gemma" : "Shot rewritten", "Undo", undoShots);
    }
    project = fresh;
    if (shotIndex(selected) < 0) selected = project.shots[0]?.id || null;
    renderBoard(); renderInspector(); renderTimeline(); renderViewer(); renderEditPanel(); renderScreen(); renderHeader(); applyTheme();
    renderBeats();
    return;
  }
  // keep what the user is typing; take generated media from the server
  fresh.shots.forEach((s, i) => Object.assign(project.shots[i], { id: s.id, keyframe: s.keyframe, video: s.video, takes: s.takes, seed: s.seed,
    sketch: s.sketch, sketches: s.sketches, paused: s.paused }));
  for (const k of ["film", "master", "master_of", "trailer", "motion_preview", "motion_defaults", "title_shot", "trailer_score", "reference",
    "lead_identity", "lead_identity_of", "world"]) project[k] = fresh[k];
  if ((fresh.story_history || []).length !== (project.story_history || []).length) adoptStory(fresh);  // the AI (or undo) changed the page
  project.story_history = fresh.story_history;
  paintBoard(); paintInspector(); paintPortrait(); renderViewer(); renderEditPanel(); renderTimeline(); renderScreen(); renderHeader(); applyTheme();
  paintBeatShots();
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
function toast(text, actionLabel, action) {
  const t = $("#toast"), b = $("button", t);
  $("span", t).textContent = text; t.hidden = false;
  b.hidden = !action; b.textContent = actionLabel || "";
  b.onclick = () => { t.hidden = true; action(); };
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, action ? 6000 : 2600);
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
    noticeFailures();
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
$("#writeShots").onclick = () => writeShots("board");
$("#autoRender").onchange = e => { project.auto_render = e.target.checked; save();
  toast(e.target.checked ? "Shots Gemma writes will render straight away" : "Shots Gemma writes wait for Render film"); };
$("#addBeat").onclick = e => {
  if (!beatsOf().length) { project.beats = [""]; renderBeats(); $$("#beats .beat-text").at(-1)?.focus(); return; }
  e.stopPropagation(); openBeatMenu($("#addBeat"), true);
};
$("#drawBoard").onclick = async () => { await flush(); await post(`/api/projects/${project.id}/storyboard`); toast("Drawing the storyboard"); poll(); };
$("#shotsUndo").onclick = undoShots;
$("#aiLead").onclick = () => writeLead((project.cast || "").trim() ? "refine" : "write");
$("#aiPhoto").onclick = () => writeLead("from photo");
$("#aiContinuity").onclick = () => writeLead("continuity");
$("#trailerUndo").onclick = () => $("#aiUndo").onclick();
$("#aiUndo").onclick = async () => { clearTimeout(saveTimer); mergeServer(await post(`/api/projects/${project.id}/undo-story`)); };
$("#aiEverything").onclick = () => writeStory("everything");
$("#worldBtn").onclick = async () => { await flush(); await post(`/api/projects/${project.id}/world`); poll(); };
$("#redescribe").onclick = async () => { await post(`/api/projects/${project.id}/describe-lead`); poll(); };
$$("[data-ai]").forEach(b => b.onclick = e => {
  if (b.dataset.ai === "beats" && beatsOf().length) { e.stopPropagation(); openBeatMenu(b, false); return; }
  writeStory(b.dataset.ai);
});
$$("#beatView button").forEach(b => b.onclick = () => setBeatView(b.dataset.view));
document.addEventListener("click", e => { if (!e.target.closest("#beatMenu")) $("#beatMenu").hidden = true; });
document.addEventListener("keydown", e => { if (e.key === "Escape") $("#beatMenu").hidden = true; });
$("#idea").onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); writeStory("everything"); } };
$$("[data-pal]").forEach(input => input.oninput = () => {
  const [ink, accent, glow, bg] = effectivePalette();
  project.palette = { bg, ink, accent, glow, ...(project.palette || {}), [input.dataset.pal]: input.value.toUpperCase() };
  applyTheme(); save();
});
$("#paletteReset").onclick = () => { delete project.palette; project.palette = null; applyTheme(); save(); };

$$("#viewerTabs button").forEach(b => b.onclick = () => { view = b.dataset.view; renderViewer(); });
$("#finish").onchange = e => { project.finish = e.target.checked; save(); };
$("#viewer").onloadedmetadata = () => renderViewer();
$("#screenVideo").onloadedmetadata = () => renderScreen();
$("#stitch").onclick = async () => {
  await flush();
  const complete = project.shots.every(s => s.video);  // missing shots render first, then the cut
  await post(`/api/projects/${project.id}/${complete ? "stitch" : "render"}`);
  if (!complete) toast("Rendering the missing shots, then cutting");
  view = "film"; poll();
};
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
