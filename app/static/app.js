// Open Cinema Studio front end: edits a project, queues renders, polls progress.
const $ = (s, el = document) => el.querySelector(s);
const api = async (path, opts = {}) => {
  const res = await fetch(path, opts);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
};
const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body || {}) });

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

let presets, project, saveTimer, jobs = [];
const media = (name) => name ? `/media/${project.id}/${encodeURIComponent(name)}` : "";

async function init() {
  presets = await api("/api/presets");
  setComfy(presets.comfy);
  const list = await api("/api/projects");
  if (list.length) await openProject(list[0].id, list); else await createProject();
  setInterval(poll, 1500);
}

function setComfy(ok) {
  $("#comfyStatus").classList.toggle("ok", ok);
  $("#comfyLabel").textContent = ok ? "ComfyUI connected" : "ComfyUI offline";
}

async function refreshPicker(list) {
  list = list || await api("/api/projects");
  const sel = $("#projectSelect");
  sel.innerHTML = list.map(p => `<option value="${p.id}">${escapeHtml(p.title)} · ${p.shots} shots</option>`).join("");
  sel.value = project.id;
}

async function openProject(id, list) {
  project = await api(`/api/projects/${id}`);
  await refreshPicker(list);
  renderAll();
}

async function createProject(seed) {
  project = await post("/api/projects", seed || { title: "Untitled film" });
  await refreshPicker();
  renderAll();
}

function chips(el, items, current, onPick) {
  el.innerHTML = "";
  for (const item of items) {
    const b = document.createElement("button");
    b.textContent = item; b.type = "button";
    b.classList.toggle("on", item === current);
    b.onclick = () => { onPick(item); [...el.children].forEach(c => c.classList.toggle("on", c === b)); };
    el.appendChild(b);
  }
}

function renderAll() {
  $("#title").value = project.title;
  $("#scene").value = project.scene;
  $("#continuity").value = project.continuity || "";
  $("#cast").value = project.cast || "";
  $("#finish").checked = !!project.finish;
  chips($("#looks"), presets.looks, project.look, v => { project.look = v; save(); renderMotion(); });
  chips($("#aspects"), presets.aspects, project.aspect, v => { project.aspect = v; save(); renderShots(); });
  const ref = $("#refImg");
  ref.src = media(project.reference); ref.classList.toggle("on", !!project.reference);
  $("#refText").textContent = project.reference ? "Cast reference set · click to replace" :
    "Drop a photo of your lead, or cast one from the description. Every shot keeps this face.";
  renderShots();
  renderFilm();
  renderMotion();
}

function ratio() { const [w, h] = project.aspect.split(":").map(Number); return `${w}/${h}`; }

function renderShots() {
  const ol = $("#shots");
  ol.innerHTML = "";
  project.shots.forEach((shot, i) => {
    const li = $("#shotTpl").content.firstElementChild.cloneNode(true);
    li.dataset.id = shot.id;
    $(".num", li).textContent = String(i + 1).padStart(2, "0");
    li.classList.toggle("continue", shot.transition === "continue" && i > 0);
    $(".frame", li).style.aspectRatio = ratio();
    for (const field of li.querySelectorAll("[data-k]")) {
      const key = field.dataset.k;
      if (field.tagName === "SELECT") {
        const opts = key === "shot_size" ? presets.shot_sizes : presets.camera_moves;
        field.innerHTML = opts.map(o => `<option>${o}</option>`).join("");
      }
      if (field.type === "checkbox") field.checked = shot[key] ?? true;
      else field.value = shot[key] ?? "";
      field.oninput = () => {
        shot[key] = field.type === "checkbox" ? field.checked
          : field.type === "number" ? Number(field.value) : field.value;
        if (key === "camera_move") camPreview(li, shot);
        save();
      };
    }
    camPreview(li, shot);
    for (const b of li.querySelectorAll("[data-tr]")) {
      b.classList.toggle("on", b.dataset.tr === (shot.transition || "cut"));
      b.disabled = i === 0 && b.dataset.tr !== "cut";
      b.onclick = () => { shot.transition = b.dataset.tr; save(); renderShots(); };
    }
    li.querySelector('[data-act="keyframe"]').disabled = shot.transition === "continue" && i > 0;
    li.querySelector('[data-act="keyframe"]').onclick = () => queueShot(shot, "keyframe");
    li.querySelector('[data-act="video"]').onclick = () => queueShot(shot, "video");
    li.querySelector('[data-act="upload"]').onchange = e => uploadKeyframe(shot, e.target.files[0]);
    li.querySelector('[data-act="up"]').onclick = () => move(i, -1);
    li.querySelector('[data-act="down"]').onclick = () => move(i, 1);
    li.querySelector('[data-act="dup"]').onclick = () => {
      project.shots.splice(i + 1, 0, { ...shot, id: undefined, keyframe: null, video: null }); save(true);
    };
    li.querySelector('[data-act="del"]').onclick = () => {
      if (project.shots.length > 1 && confirm(`Delete shot ${i + 1}?`)) { project.shots.splice(i, 1); save(true); }
    };
    paintMedia(li, shot);
    ol.appendChild(li);
  });
  renderTimeline();
}

function camPreview(li, shot) { $(".cam-scene", li).style.animation = CAMERA_ANIM[shot.camera_move] || ""; }

function paintTakes(li, shot) {
  const box = $(".takes", li), takes = shot.takes || {};
  const keys = takes.keyframe || [], vids = (takes.video || []).filter(t => t.keyframe === shot.keyframe);
  const signature = JSON.stringify([keys.map(t => t.name), vids.map(t => t.name), shot.keyframe, shot.video]);
  if (box.dataset.sig === signature) return;
  box.dataset.sig = signature;
  box.innerHTML = "";
  const chip = (label, kind, take, on) => {
    const b = document.createElement("button");
    b.textContent = label; b.classList.toggle("on", on);
    b.title = take.seed ? `seed ${take.seed}` : take.name;
    b.onclick = async () => mergeServer(await post(`/api/projects/${project.id}/shots/${shot.id}/take`, { kind, name: take.name }), true);
    box.appendChild(b);
  };
  if (keys.length > 1) {
    box.append("Frame");
    keys.forEach((t, i) => chip(`K${i + 1}`, "keyframe", t, t.name === shot.keyframe));
  }
  if (vids.length > 1) {
    const sep = document.createElement("span"); sep.className = "sep"; box.append(sep, "Shot");
    vids.forEach((t, i) => chip(`S${i + 1}`, "video", t, t.name === shot.video));
  }
}

function paintMedia(li, shot) {
  paintTakes(li, shot);
  const img = $(".frame img", li), vid = $(".frame video", li);
  img.classList.toggle("on", !!shot.keyframe && !shot.video);
  if (shot.keyframe && img.dataset.src !== shot.keyframe) { img.src = media(shot.keyframe); img.dataset.src = shot.keyframe; }
  vid.classList.toggle("on", !!shot.video);
  if (shot.video && vid.dataset.src !== shot.video) { vid.src = media(shot.video); vid.dataset.src = shot.video; vid.play().catch(() => {}); }
  $(".frame .empty", li).style.display = shot.keyframe || shot.video ? "none" : "";
  const job = jobs.find(j => j.shot === shot.id && (j.state === "running" || j.state === "queued"));
  const busy = $(".frame .busy", li);
  busy.classList.toggle("on", !!job);
  if (job) busy.textContent = job.state === "running" ? `${job.label} · ${Math.round(job.elapsed)}s` : `${job.label} · queued`;
  const failed = jobs.filter(j => j.shot === shot.id).at(-1);
  li.title = failed && failed.state === "failed" ? `Last attempt failed: ${failed.error}` : "";
}

function renderTimeline() {
  const tl = $("#timeline");
  tl.innerHTML = "";
  project.shots.forEach((shot, i) => {
    const clip = document.createElement("div");
    clip.className = "clip" + (shot.video ? " rendered" : "") + (shot.transition === "continue" && i ? " joined" : "");
    clip.style.flexGrow = shot.seconds;
    if (shot.keyframe) clip.style.backgroundImage = `url("${media(shot.keyframe)}")`;
    clip.innerHTML = `<b>${i + 1} · ${shot.seconds}s</b>`;
    clip.onclick = () => document.querySelector(`.shot[data-id="${shot.id}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    tl.appendChild(clip);
  });
}

// ---------- titles & motion ----------
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

function renderMotion() {
  const m = motionState(), d = project.motion_defaults || {};
  $("#mTitle").checked = m.title.on;
  $("#mSubtitle").value = m.title.subtitle;
  $("#mMaterial").value = m.title.material;
  $("#mMaterial").placeholder = d.material || "Material";
  paintTitleStyle(m.title.style);
  $("#mStamps").checked = m.stamps.on;
  $("#mCredits").checked = m.credits.on;
  $("#mCreditsLines").value = m.credits.lines;
  $("#mCreditsLines").placeholder = d.credits || "";
  $("#mTrailerLines").value = m.trailer.lines;
  $("#mTrailerLines").placeholder = d.trailer || "";
  const palette = (presets.palettes || {})[project.look] || ["#f4f4f2", "#f5b83d", "#ffd27a", "#111111"];
  $(".motion").style.setProperty("--look-accent", palette[1]);
  $("#lookSwatches").innerHTML = palette.slice(0, 4).map(c => `<span style="background:${c}"></span>`).join("");
  const sample = project.shots[Math.min(2, project.shots.length - 1)] || {};
  const n = Math.min(3, project.shots.length);
  const move = (sample.camera_move || "Tilt up").toUpperCase();
  $("#stampSample").innerHTML = `SHOT ${String(n).padStart(2, "0")} · ${escapeHtml((sample.shot_size || "Low angle").toUpperCase())} · <mark>${escapeHtml(move)}</mark>`;
  paintMotionCards();
  renderMotionMedia();
}

function paintMotionCards() {
  const m = motionState();
  const on = { title: m.title.on, stamps: m.stamps.on, credits: m.credits.on, trailer: !!project.trailer };
  document.querySelectorAll(".mcard[data-part]").forEach(c => c.classList.toggle("on", !!on[c.dataset.part]));
}

function renderMotionMedia() {
  const row = $("#trailerRow"), img = $("#mPreviewImg"), vid = $("#trailer"), dl = $("#downloadTrailer");
  img.hidden = !project.motion_preview;
  if (project.motion_preview && img.dataset.src !== project.motion_preview) {
    img.src = media(project.motion_preview); img.dataset.src = project.motion_preview;
  }
  vid.hidden = dl.hidden = !project.trailer;
  if (project.trailer && vid.dataset.src !== project.trailer) {
    vid.src = media(project.trailer); vid.dataset.src = project.trailer;
  }
  dl.href = media(project.trailer); dl.download = `${project.title} trailer.mp4`;
  row.hidden = !project.trailer && !project.motion_preview;
  paintMotionCards();
}

function paintTitleStyle(style) {
  document.querySelectorAll("[data-style]").forEach(b => b.classList.toggle("on", b.dataset.style === style));
  $(".title-kinetic").hidden = style === "inworld";
  $(".title-inworld").hidden = style !== "inworld";
  renderTitleShot();
}

function renderTitleShot() {
  const unit = project.title_shot || {}, img = $("#titleFrame"), vid = $("#titleShot");
  img.hidden = !unit.keyframe || !!unit.video;
  vid.hidden = !unit.video;
  if (unit.keyframe && img.dataset.src !== unit.keyframe) { img.src = media(unit.keyframe); img.dataset.src = unit.keyframe; }
  if (unit.video && vid.dataset.src !== unit.video) { vid.src = media(unit.video); vid.dataset.src = unit.video; vid.play().catch(() => {}); }
  $("#rerollTitleMotion").hidden = !unit.keyframe;
  $("#makeTitle").textContent = unit.keyframe ? "New title frame" : "Make in-world title";
  const box = $("#titleTakes"), takes = unit.takes || {};
  const frames = takes.keyframe || [], vids = (takes.video || []).filter(t => t.keyframe === unit.keyframe);
  box.innerHTML = "";
  const chip = (label, kind, take, on) => {
    const b = document.createElement("button");
    b.textContent = label; b.classList.toggle("on", on); b.type = "button";
    b.onclick = async () => mergeServer(await post(`/api/projects/${project.id}/title-shot/take`, { kind, name: take.name }));
    box.appendChild(b);
  };
  if (frames.length > 1) { box.append("Frame"); frames.forEach((t, i) => chip(`K${i + 1}`, "keyframe", t, t.name === unit.keyframe)); }
  if (vids.length > 1) {
    const sep = document.createElement("span"); sep.className = "sep"; box.append(sep, "Motion");
    vids.forEach((t, i) => chip(`S${i + 1}`, "video", t, t.name === unit.video));
  }
  const busy = jobs.find(j => j.project === project.id && j.kind.startsWith("title_") && (j.state === "queued" || j.state === "running"));
  $("#makeTitle").disabled = $("#rerollTitleMotion").disabled = !!busy;
  if (busy) $("#makeTitle").textContent = busy.state === "running" ? `${busy.label} · ${Math.round(busy.elapsed)}s` : "Queued…";
}

function saveMotion() {
  const style = document.querySelector("[data-style].on")?.dataset.style || "kinetic";
  project.motion = {
    title: { on: $("#mTitle").checked, subtitle: $("#mSubtitle").value, style, material: $("#mMaterial").value },
    stamps: { on: $("#mStamps").checked },
    credits: { on: $("#mCredits").checked, lines: $("#mCreditsLines").value },
    trailer: { lines: $("#mTrailerLines").value },
  };
  paintMotionCards();
  save();
}

function renderFilm() {
  const film = $("#film"), total = project.shots.reduce((s, x) => s + Number(x.seconds || 0), 0);
  const done = project.shots.filter(s => s.video).length;
  $("#filmTitle").textContent = project.title;
  $("#filmInfo").textContent = project.film
    ? `${project.shots.length} shots · ${total}s · stitched with sound`
    : `${done}/${project.shots.length} shots rendered · ${total}s planned`;
  if (project.film && film.dataset.src !== project.film) { film.src = media(project.film); film.dataset.src = project.film; }
  film.style.display = project.film ? "" : "none";
  film.style.aspectRatio = ratio();
  const dl = $("#download");
  dl.hidden = !project.film; dl.href = media(project.film); dl.download = `${project.title}.mp4`;
  const mastered = project.film && project.master && project.master_of === project.film;
  $("#master").hidden = !project.film || mastered;
  const dm = $("#downloadMaster");
  dm.hidden = !mastered; dm.href = media(project.master); dm.download = `${project.title} 1080p.mp4`;
}

function move(i, delta) {
  const j = i + delta;
  if (j < 0 || j >= project.shots.length) return;
  [project.shots[i], project.shots[j]] = [project.shots[j], project.shots[i]];
  save(true);
}

function save(rerender) {
  clearTimeout(saveTimer);
  const doSave = async () => {
    const fresh = await post(`/api/projects/${project.id}`, project);
    mergeServer(fresh, rerender);
  };
  if (rerender) return doSave();
  saveTimer = setTimeout(doSave, 400);
}

function mergeServer(fresh, rerender) {
  // Keep what the user is typing; take generated media and ids from the server.
  const byId = Object.fromEntries(fresh.shots.map(s => [s.id, s]));
  if (rerender || fresh.shots.length !== project.shots.length) { project = fresh; renderShots(); renderFilm(); refreshPicker(); return; }
  fresh.shots.forEach((s, i) => {
    const local = project.shots[i];
    Object.assign(local, { id: s.id, keyframe: s.keyframe, video: s.video, takes: s.takes });
  });
  project.film = fresh.film; project.master = fresh.master; project.master_of = fresh.master_of;
  project.trailer = fresh.trailer; project.motion_preview = fresh.motion_preview;
  project.motion_defaults = fresh.motion_defaults;
  project.title_shot = fresh.title_shot;
  renderMotionMedia();
  renderTitleShot();
  if (project.reference !== fresh.reference) {
    project.reference = fresh.reference;
    $("#refImg").src = media(project.reference); $("#refImg").classList.toggle("on", !!project.reference);
    $("#refText").textContent = "Cast reference set · click to replace";
  }
  document.querySelectorAll(".shot").forEach((li, i) => { li.dataset.id = project.shots[i].id; paintMedia(li, project.shots[i]); });
  renderTimeline(); renderFilm();
}

async function flush() { clearTimeout(saveTimer); mergeServer(await post(`/api/projects/${project.id}`, project)); }

async function queueShot(shot, kind) {
  await flush();
  await post(`/api/projects/${project.id}/shots/${shot.id}/${kind}`);
  poll();
}

async function uploadKeyframe(shot, file) {
  if (!file) return;
  await flush();
  const fresh = await api(`/api/projects/${project.id}/shots/${shot.id}/keyframe-upload`,
    { method: "POST", body: file, headers: { "X-Filename": encodeURIComponent(file.name) } });
  mergeServer(fresh, true);
}

async function uploadReference(file) {
  if (!file) return;
  await flush();
  project = await api(`/api/projects/${project.id}/reference`,
    { method: "POST", body: file, headers: { "X-Filename": encodeURIComponent(file.name) } });
  renderAll();
}

let lastSignature = "";
async function poll() {
  try {
    jobs = await api("/api/jobs");
    const mine = jobs.filter(j => j.project === project.id);
    const active = jobs.filter(j => j.state === "queued" || j.state === "running");
    $("#queueCount").textContent = active.length;
    $("#jobs").innerHTML = mine.slice().reverse().map(j => `<li class="${j.state}"><span>${escapeHtml(j.label)}
      ${j.error ? `<span class="err">${escapeHtml(j.error)}</span>` : ""}</span>
      <small>${j.state === "running" || j.state === "done" ? Math.round(j.elapsed) + "s " : ""}${j.state}</small></li>`).join("")
      || `<li><span class="sub">Nothing queued yet</span></li>`;
    const signature = mine.map(j => j.id + j.state).join();
    if (signature !== lastSignature) {
      lastSignature = signature;
      mergeServer(await api(`/api/projects/${project.id}`));
    } else {
      document.querySelectorAll(".shot").forEach((li, i) => paintMedia(li, project.shots[i]));
      renderTitleShot();
    }
    $("#renderFilm").disabled = active.some(j => j.project === project.id);
    setComfy(true);
  } catch { setComfy(false); }
}

function escapeHtml(s) { return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

// ---------- wiring ----------
$("#finish").onchange = e => { project.finish = e.target.checked; save(); };
$("#castBtn").onclick = async () => {
  if (!project.cast?.trim()) { $("#cast").focus(); return; }
  await flush(); await post(`/api/projects/${project.id}/cast`); poll();
};
for (const id of ["title", "scene", "continuity", "cast"]) $("#" + id).oninput = e => { project[id] = e.target.value; save(); };
$("#projectSelect").onchange = e => openProject(e.target.value);
$("#newProject").onclick = () => createProject();
$("#addShot").onclick = () => {
  const last = project.shots.at(-1) || {};
  project.shots.push({ action: "", shot_size: "Medium", camera_move: "Static", seconds: 4, sound: last.sound || "", transition: "cut" });
  save(true);
};
$("#renderFilm").onclick = async () => { await flush(); await post(`/api/projects/${project.id}/render`); $("#queue").hidden = false; poll(); };
for (const id of ["mTitle", "mStamps", "mCredits"]) $("#" + id).onchange = saveMotion;
for (const id of ["mSubtitle", "mMaterial", "mCreditsLines", "mTrailerLines"]) $("#" + id).oninput = saveMotion;
document.querySelectorAll("[data-style]").forEach(b => b.onclick = () => { paintTitleStyle(b.dataset.style); saveMotion(); });
const queueTitle = frame => async () => {
  await flush(); await post(`/api/projects/${project.id}/title-shot`, { frame }); $("#queue").hidden = false; poll();
};
$("#makeTitle").onclick = queueTitle(true);
$("#rerollTitleMotion").onclick = queueTitle(false);
$("#mPreview").onclick = async () => { await flush(); await post(`/api/projects/${project.id}/motion-preview`); poll(); };
$("#cutTrailer").onclick = async () => {
  await flush(); await post(`/api/projects/${project.id}/trailer`); $("#queue").hidden = false; poll();
};
$("#master").onclick = async () => { await post(`/api/projects/${project.id}/master`); $("#queue").hidden = false; poll(); };
$("#stitch").onclick =async () => { await post(`/api/projects/${project.id}/stitch`); poll(); };
$("#queueToggle").onclick = () => { $("#queue").hidden = !$("#queue").hidden; };
$("#cancelAll").onclick = () => post("/api/cancel").then(poll);
$("#refInput").onchange = e => uploadReference(e.target.files[0]);
const drop = $("#refDrop");
drop.ondragover = e => { e.preventDefault(); drop.classList.add("drag"); };
drop.ondragleave = () => drop.classList.remove("drag");
drop.ondrop = e => { e.preventDefault(); drop.classList.remove("drag"); uploadReference(e.dataTransfer.files[0]); };

init();
