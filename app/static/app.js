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
  const worldReference = ["Wide", "Extreme wide"].includes(shot.shot_size);
  return { kind: "shot", world: plateOf(), lead: leadIn(shot) ? project.reference : null, sketch: drawn ? shot.sketch : null,
    world_reference: worldReference,
    steps: [...(plateOf() && !plateStale() ? [] : [`HiDream-O1 · paints ${plateOf() ? "a new" : "the"} world plate first`]),
      ...(drawn ? [] : [`HiDream-O1 · ${shot.sketch ? "redraws" : "draws"} the pencil storyboard first`]),
      `Qwen-Image-Edit 2511 · the storyboard${leadIn(shot) ? " + the lead" : ""}${worldReference ? " + the world" : ""} · 4 steps`] };
}

function staleness(shot) {  // why the current frame no longer matches the film ("" when it does)
  if (storyStale(shot)) return "Beat changed · review shot";
  if (project.asset_status?.[shot.id]?.frame) return "Frame needs updating";
  if (project.asset_status?.[shot.id]?.video) return "Video needs updating";
  if (project.asset_status?.[shot.id]?.review) return "Video needs review";
  if (Object.values(shot.quality || {}).some(q=>q.status === "needs_review")) return "Candidate needs review";
  const r = recipeOf(shot);
  if (!shot.keyframe || !r || r.kind !== "shot") return "";
  if (leadIn(shot) && r.lead !== project.reference) return r.lead ? "Lead changed" : "Made before the lead";
  if (r.world !== plateOf()) return "World changed";
  if (r.action !== undefined && r.action !== (shot.action || "")) return "Action changed";
  if (r.shot_size !== undefined && (r.shot_size !== shot.shot_size || r.camera_move !== shot.camera_move)) return "Framing changed";
  return "";
}
const storyStale = s => s.beat_source !== undefined && s.beat_source !== (project.beats?.[s.beat - 1] || "");
const needsRender = s => !s.video || storyStale(s) || project.asset_status?.[s.id]?.frame || project.asset_status?.[s.id]?.video;

async function acceptBeat(shot) {
  shot.accept_beat = true;
  await flush();
  delete shot.accept_beat;
  shot.beat_source = project.beats?.[shot.beat - 1] || "";
  paintScript(); renderInspector(); paintBoard();
}
const active = j => j.state === "queued" || j.state === "running";
const busyFor = test => jobs.find(j => j.project === project.id && active(j) && test(j));

// ---------------------------------------------------------------- boot
async function init() {
  [presets, projects, jobs] = await Promise.all([api("/api/presets"), api("/api/projects"), api("/api/jobs")]);
  const remembered = store.get("project");
  const first = projects.find(p => p.id === remembered) || projects[0];
  if (first) await openProject(first.id); else await createProject();
  setStage(stage);
  await checkSetup();
  startJobEvents();
  poll();
}

let setupState, lastSetupCheck=0;
const selectedSetupReady = () => setupState?.modes?.[project?.ai_mode || 'normal']?.film_ready ?? setupState?.ready;
const gigabytes = n => `${(n / 1e9).toFixed(1)} GB`;
async function checkSetup(refresh=false) {
  try {
    const wasReady=selectedSetupReady();
    setupState = await api('/api/setup' + (refresh ? '?refresh=1' : ''));
    lastSetupCheck=Date.now();
    presets.comfy=setupState.connected;
    $('#setupBtn').textContent = selectedSetupReady() ? 'Setup ✓' : 'Setup needed';
    if (!selectedSetupReady() && (wasReady===undefined || wasReady)) $('#setupPanel').hidden = false;
    renderSetup();
    renderStatus();
  } catch (e) { toast('Setup check failed: ' + e.message); }
}
function setupGroup(group, expanded, running) {
  const names={writing:'Standard · 12B at 8-bit',writing_fast:'Fast · E4B (optional)',images:'Stills and storyboards',video:'Video and sound',master:'Optional 1080p mastering'};
  const list=setupState.models.filter(m=>m.group===group), pending=list.filter(m=>!m.installed);
  const size=gigabytes(pending.reduce((n,m)=>n+m.bytes,0));
  const open=expanded.has(group)?expanded.get(group):pending.length>0 && !['master',project.ai_mode==='fast'?'writing':'writing_fast'].includes(group);
  return `<details data-setup-group="${group}" ${open?'open':''}><summary>${names[group]} · ${pending.length?size+' missing':'installed'}</summary>
    <ul>${list.map(m=>{
      const job=setupState.downloads.find(j=>j.id===m.id);
      return `<li><span>${m.installed?'✓':'○'} ${escapeHtml(m.name)} <small>${escapeHtml(m.folder)}/ · ${gigabytes(m.bytes)}</small></span>
        <a href="${m.source}" target="_blank" rel="noopener">Publisher${m.gated?' · access required':''}</a>
        ${job?`<p>${escapeHtml(job.state)} · ${gigabytes(job.done)} / ${gigabytes(job.total)} ${escapeHtml(job.error||'')}</p>`:''}</li>`;
    }).join('')}</ul>
    ${pending.length&&setupState.model_dir?`<button class="ghost small" data-download-group="${group}" ${running?'disabled':''}>Install ${size}</button>`:''}</details>`;
}

function renderSetup() {
  const box=$('#setupPanel'), s=setupState;
  if(!s || box.hidden) return;
  const missing=s.models.filter(m=>!m.installed), total=missing.filter(m=>!['master',project.ai_mode==='fast'?'writing':'writing_fast'].includes(m.group)).reduce((n,m)=>n+m.bytes,0);
  const running=s.downloads.some(j=>['queued','downloading','verifying'].includes(j.state));
  const expanded=new Map($$('details[data-setup-group]',box).map(el=>[el.dataset.setupGroup,el.open]));
  box.innerHTML=`<div class="card-head"><div><h2 class="serif">Set up your local studio</h2><p class="hint">Your films stay on your computer. Models download only when you choose to install them.</p></div><button class="ghost small" data-close-setup>Close</button></div>
    <p>${selectedSetupReady()?'Ready to write and render in '+(project.ai_mode==='fast'?'Fast':'Standard')+' mode.':s.connected?`Missing models for this mode: ${gigabytes(total)}. Install the required groups below, then check again.`:'ComfyUI is not connected. Start it first, then check again.'}</p>
    <p class="hint">ComfyUI: ${escapeHtml(s.comfy_url)} · FFmpeg and FFprobe: ${s.ffmpeg?'ready':'missing — install FFmpeg and add it to PATH'} · Free disk: ${gigabytes(s.free_bytes)}</p>
    ${s.missing_nodes.length?`<p class="quality-findings">Missing nodes: ${s.missing_nodes.map(escapeHtml).join(', ')}. Install the Open Cinema node pack and update ComfyUI, then restart ComfyUI.</p>`:''}
    <p class="hint">${s.model_dir?`Install folder: ${escapeHtml(s.model_dir)}`:'To enable downloads, start the studio with --models-dir pointing to your ComfyUI models folder. You can also use the publisher links and place files in the listed folders.'}</p>
    <p class="hint">LTX downloads require you to review the publisher’s access conditions. If access is denied, approve access on Hugging Face yourself, set HF_TOKEN in the server environment and retry. The studio does not accept terms or collect tokens in this page.</p>
    ${s.connected?['writing','writing_fast','images','video','master'].map(group=>setupGroup(group,expanded,running)).join(''):'<p>Connect ComfyUI first so the studio can check which models are already installed.</p>'}
    <p class="hint">Downloads resume from partial files and are checked against the publisher’s SHA-256 before installation. Existing files are never silently replaced. A supported GPU with about 24 GB VRAM is recommended for the supplied full pipeline.</p>
    <button class="primary" data-check-setup>Check again</button>`;
  $('[data-close-setup]',box).onclick=()=>box.hidden=true;
  $('[data-check-setup]',box).onclick=()=>checkSetup(true);
  $$('[data-download-group]',box).forEach(b=>b.onclick=async()=>{try{
    setupState=await post('/api/setup/download',{ids:s.models.filter(m=>!m.installed&&m.group===b.dataset.downloadGroup).map(m=>m.id)});renderSetup();
  }catch(e){toast(e.message)}});
}
$('#setupBtn').onclick=()=>{ $('#setupPanel').hidden=!$('#setupPanel').hidden; if(!$('#setupPanel').hidden)checkSetup(true); };
setInterval(()=>{if(setupState && (!$('#setupPanel').hidden || Date.now()-lastSetupCheck>15000))checkSetup();},5000);

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
  renderStatus();
}

// ---------------------------------------------------------------- theme & header
function luminance(hex) {
  const [r, g, b] = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function effectivePalette() {
  // [ink, accent, glow, bg, face] — the look's, with the film's custom colours on top
  const base = presets.palettes?.[project.look] || presets.palettes?.None || ["#f4f4f2", "#ff4a1c", "#ff7a45", "#0c0c0d", "barlow"];
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
  $("#paletteSource").textContent = custom ? "Independent colours for this film" : (presets.palettes?.[project.look] ? "Preset colours" : "Default colours");
  $("#paletteReset").hidden = !custom;
  $("#paletteReset").textContent = presets.palettes?.[project.look] ? "Use preset colours" : "Use default colours";
}

function preservePalette() {
  if (!project.palette?.accent) {
    const [ink, accent, glow, bg] = effectivePalette();
    project.palette = { bg, ink, accent, glow };
  }
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

let queueSignature = '';
function latestJobs() {
  const latest = new Map();
  jobs.filter(j=>j.project===project.id).forEach(j=>{
    const key=[j.kind,j.shot,j.target,j.mode,j.prop,j.value].join('|'), previous=latest.get(key);
    if(['cancelled','blocked'].includes(j.state) && previous && ['failed','needs_review','interrupted'].includes(previous.state)) return;
    latest.set(key,j);
  });
  return [...latest.values()];
}
function unresolvedJob(j) {
  if (!['failed','needs_review','interrupted'].includes(j.state)) return false;
  if (j.kind==='plan_continuity' && project.continuity_status==='ready') return false;
  const shot=project.shots.find(s=>s.id===j.shot);
  const kind={sketch:'sketch',keyframe:'keyframe',video:'video',review:'video'}[j.kind];
  const review=shot?.quality?.[kind];
  if(shot && kind && review?.status==='passed' && shot[kind] && !/\bprovisional\b/i.test(review.director_review?.reason||'')) return false;
  return true;
}
function setQueueOpen(open) {
  $('#queue').hidden=!open;
  ['#statusPill','#productionDetails'].forEach(id=>$(id).setAttribute('aria-expanded',String(open)));
}
function jobError(j) {
  const message=(j.error||'').replace('ComfyUI execution failed: ','');
  return message==='unknown'?'Generation stopped without a diagnostic. Your saved work is kept; retry this step.':message;
}
function renderStatus() {
  if(!project) return;
  const current=jobs.filter(j=>j.project===project.id), latest=latestJobs(), pending=current.filter(active);
  const running=pending.find(j=>j.state==='running'), attention=latest.filter(unresolvedJob);
  const blocked=latest.filter(j=>j.state==='blocked' || j.state==='cancelled' && j.error==='an earlier step failed');
  const offline=presets.comfy===false, missing=selectedSetupReady()===false;
  $('#comfyDot').className='dot '+(offline||missing?'':running?'busy':attention.length?'warn':'ok');
  $('#statusText').textContent=offline?'Offline':missing?'Setup needed':pending.length?`Working · ${pending.length} left`:attention.length?`${attention.length} need attention`:blocked.length?'Waiting':'Ready';
  $('#renderFilm').disabled=!!pending.length||offline||missing;
  $('#renderFilm').firstChild.textContent=attention.length||blocked.length?'Resume film ':'Render film ';
  $('#resumeWork').hidden=!(attention.length||blocked.length);
  $('#resumeWork').disabled=!!pending.length||offline||missing;
  $('#cancelAll').disabled=!pending.length;
  const fast=project.ai_mode==='fast';
  $$('[data-ai-mode]').forEach(input=>{input.checked=input.value===(project.ai_mode||'normal');});
  const dimensions={'16:9':[1280,704],'2.39:1':[1536,640],'9:16':[704,1280],'1:1':[960,960]}[project.aspect]||[1280,704];
  $('#aiModeHelp').textContent=fast?'Faster writing and lower-resolution video previews.':'Full-resolution video and more detailed writing.';
  $('#performanceWriting').textContent=fast?'Gemma 4 E4B for quicker writing and review.':'Gemma 4 12B at 8-bit for writing and review.';
  $('#performanceVideo').textContent=fast?`${dimensions[0]/2} × ${dimensions[1]/2} single-stage preview; upscaled only in the cut.`:`${dimensions[0]} × ${dimensions[1]} two-stage video.`;
  $('#aiStoryStatus').textContent=`Title, logline, world, look and cast, written locally in ${fast?'Fast mode · Gemma 4 E4B':'Standard mode · Gemma 4 12B (8-bit)'}. Every field also has its own ✨.`;
  const summary=offline?'Connect ComfyUI in Setup to resume. Your work is saved.':missing?'Install the missing models for this AI mode in Setup.':running?`${running.label}${running.detail?' — '+running.detail:''}`:attention.length?`${attention.length} step${attention.length===1?' needs':'s need'} attention. Finished work is saved; inspect or retry the affected step.`:blocked.length?`${blocked.length} step${blocked.length===1?'':'s'} waiting. Resume to generate only missing or outdated work.`:project.shots.some(s=>s.video)?'Saved work is ready. Render film fills in missing or outdated shots.':'Ready when you are. Storyboards are planning drafts; finished frames and motion follow.';
  if($('#productionSummary').textContent!==summary) $('#productionSummary').textContent=summary;
  $('#productionSummary').className=attention.length?'attention-text':'';
  $('#queueSummary').textContent=`${pending.length} active · ${attention.length} need attention · ${blocked.length} waiting`;
  const ordered=[...pending.sort((a,b)=>(a.state==='running'?-1:1)-(b.state==='running'?-1:1)),...attention];
  const history=current.filter(j=>!ordered.includes(j)).slice().reverse().slice(0,50);
  const signature=JSON.stringify([project.id,project.continuity_fixes,project.continuity_status,ordered.map(j=>[j.id,j.state,j.label,j.detail,j.error]),history.map(j=>[j.id,j.state])]);
  const row=(j,actionable)=>`<li class="${j.state}"><span>${escapeHtml(j.label)}</span><small>${escapeHtml(j.state.replaceAll('_',' '))}</small>
    <span class="job-meta">${j.ai_mode==='fast'?'Fast':'Standard'}${j.elapsed?` · <span data-job-time="${j.id}">${Math.round(j.elapsed)}s</span>`:''}</span>
    ${j.detail?`<p class="job-detail">${escapeHtml(j.detail)}</p>`:''}${j.error?`<p class="err">${escapeHtml(jobError(j))}</p>`:''}
    ${actionable&&!active(j)&&j.kind==='plan_continuity'&&j.state==='needs_review'&&project.continuity_fixes?.length?`<p class="job-detail">${escapeHtml(project.continuity_fixes.map(f=>f.description).join(' '))}${j.render_after||j.draw_after?' Generation resumes if the plan is ready.':''}</p>`:''}
    ${actionable&&!active(j)?`<div class="job-actions">${j.kind==='plan_continuity'&&j.state==='needs_review'&&project.continuity_fixes?.length?`<button class="ghost small" data-fix-continuity="${j.id}" title="${escapeHtml(project.continuity_fixes.map(f=>f.description).join(' '))}">Auto fix</button>`:''}${j.kind==='plan_continuity'?'<button class="ghost small" data-review-continuity>Review continuity</button>':''}${j.shot?`<button class="ghost small" data-inspect-job="${j.shot}">Inspect shot</button>`:''}<button class="ghost small" data-retry-job="${j.id}">Retry step</button></div>`:''}</li>`;
  if(signature!==queueSignature) {
    queueSignature=signature;
    $('#jobs').innerHTML=ordered.map(j=>row(j,true)).join('')||'<li><span>No steps need attention.</span></li>';
    $('#earlierJobs').innerHTML=history.map(j=>row(j,false)).join('');
    $('#jobHistory').hidden=!history.length;
    $('#jobHistory summary').textContent=`Earlier activity · ${history.length} steps`;
  }
  $$('[data-job-time]',$('#queue')).forEach(el=>{const j=current.find(j=>j.id===el.dataset.jobTime);if(j)el.textContent=Math.round(j.elapsed)+'s';});
}

// ---------------------------------------------------------------- story
function renderStory() {
  renderContinuity();
  $("#title").value = project.title;
  $("#idea").value = project.idea || "";
  $("#logline").value = project.logline || "";
  $("#scene").value = project.scene;
  $("#cast").value = project.cast || "";
  $("#continuity").value = project.continuity || "";
  $("#characters").value = project.characters || "";
  $("#filmLook").value = project.look || "";
  $("#imageQuality").value = project.image_quality || "fast";
  renderBeats();
  paintPortrait();
  requestAnimationFrame(() => growAll($("#story")));
  const grid = $("#looks");
  grid.innerHTML = "";
  for (const look of presets.looks) {
    const description = presets.look_descriptions?.[look] || "No prescribed film look";
    const b = document.createElement("button");
    b.type = "button"; b.className = "look" + (look === project.look ? " on" : "");
    b.innerHTML = `<span class="look-name">${escapeHtml(look)}</span><span class="look-score">${escapeHtml(description)}</span>`;
    b.onclick = () => {
      preservePalette(); project.look = look; $("#filmLook").value = look;
      $$(".look", grid).forEach(x => x.classList.toggle("on", x === b)); applyTheme(); renderEditPanel(); save();
    };
    b.title = description;
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
  everything: ["titleField", "loglineField", "worldField", "lookField", "castField", "continuityField", "sparkField", "beatsField",
    "charactersField"],
  characters: ["charactersField"],
  title: ["titleField"], logline: ["loglineField"], world: ["worldField"], look: ["lookField"], trailer: ["trailerField"],
  beats: ["beatsField"],
};
const AI_FIELDS = ["titleField", "loglineField", "worldField", "lookField", "castField", "continuityField", "sparkField",
  "trailerField", "beatsField", "charactersField"];

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
let beatView = ["strip", "script"].includes(store.get("beatView")) ? store.get("beatView") : "beats";

function setBeatView(view) {
  beatView = view; store.set("beatView", view);
  $$("#beatView button").forEach(b => b.classList.toggle("on", b.dataset.view === view));
  $("#beats").hidden = view !== "beats";
  $("#addBeat").hidden = view !== "beats";
  $("#strip").hidden = view !== "strip";
  $("#script").hidden = view !== "script";
  paintStrip(); paintScript();
}

function renderContinuity() {
  const box = $("#continuityPanel");
  if (!box || box.contains(document.activeElement) && document.activeElement.matches("input,textarea")) return;
  const plan = project.continuity_plan, state = project.scene_state || {}, status = project.continuity_status || "missing";
  const sig = JSON.stringify([plan, state, status, project.continuity_error, project.props]);
  if (box.dataset.sig === sig) return;
  box.dataset.sig = sig;
  box.innerHTML = `<div class="card-head"><div><h2 class="serif">Scene continuity</h2><p class="hint">Design stays fixed. State changes as the story unfolds.</p></div>
    <button type="button" class="ghost small" data-plan>${plan ? "Replan from script" : "Plan continuity"}</button></div>
    <p class="hint">${{missing:"A state plan is created before rendering. You can plan it now and review it first.", stale:"The script changed. Replan, or review these states and confirm them below.", issues:"The plan found story contradictions. Resolve them before rendering.", ready:"Each shot inherits the preceding result. Edit changes in Script → Scene state."}[status]}</p>
    ${project.continuity_error ? `<p class="quality-findings">Planning stopped: ${escapeHtml(project.continuity_error)}. Your story and shots are saved. Plan again to retry.</p>` : ""}
    ${plan ? `<details><summary>Permanent design</summary><label>Objects, materials and wardrobe<textarea data-state-design rows="4">${escapeHtml(plan.design || "")}</textarea></label></details>` : ""}
    ${plan?.issues?.length ? `<ul class="quality-findings">${plan.issues.map(x=>`<li>${escapeHtml(x)}</li>`).join("")}</ul>` : ""}
    ${plan ? `<h4>Before the first shot</h4><div class="state-grid">${Object.entries(state).map(([k,v])=>
      `<label>${escapeHtml(k)}<input data-initial="${escapeHtml(k)}" value="${escapeHtml(v)}"></label>`).join("")}</div>
      <div class="state-add"><input aria-label="New state fact" placeholder="Fact, e.g. Parcel · seal" data-fact-name><input aria-label="Initial fact value" placeholder="Initial value" data-fact-value><button type="button" class="ghost small" data-add-fact>Add fact</button></div>
      ${status !== "ready" ? `<button type="button" class="ghost small" data-accept-plan>Use reviewed states</button>` : ""}` : ""}`;
  if (plan) {
    box.insertAdjacentHTML("beforeend", `<details class="prop-panel"><summary>Prop references · keep recurring objects consistent</summary><p class="hint">Bind a prop to a scene fact, draw its required states, then choose it in each shot’s Scene state. Inspect these references before rendering.</p>
      ${(project.props||[]).map(p=>`<article data-prop="${escapeHtml(p.id)}"><label>Name<input data-prop-field="name" value="${escapeHtml(p.name)}"></label><label>Permanent design<textarea data-prop-field="description" rows="3">${escapeHtml(p.description)}</textarea></label><label>Changing fact<select data-prop-field="state_key">${Object.keys(state).map(k=>`<option ${p.state_key===k?"selected":""}>${escapeHtml(k)}</option>`).join("")}</select></label><div class="prop-variants">${[...new Set([state[p.state_key], ...project.shots.map(s=>s.state_changes?.[p.state_key])].filter(Boolean))].map(v=>`<div>${p.variants?.[v]?.name?`<img src="/media/${project.id}/${p.variants[v].name}" alt="${escapeHtml(p.name+': '+v)}">`:""}<p>${escapeHtml(v)}</p><button type="button" class="ghost small" data-prop-state="${escapeHtml(v)}">${p.variants?.[v]?"Redraw":"Draw reference"}</button></div>`).join("")}</div></article>`).join("")}
      <button type="button" class="ghost small" data-add-prop>Add prop</button></details>`);
    $("[data-add-prop]",box).onclick=async()=>{ project.props ||= []; project.props.push({name:"New prop",description:"",state_key:Object.keys(state)[0],variants:{}}); await flush(); box.dataset.sig=""; renderContinuity(); };
    $$("[data-prop]",box).forEach(card=>{
      const p=project.props.find(p=>p.id===card.dataset.prop);
      $$("[data-prop-field]",card).forEach(el=>el.onchange=()=>{p[el.dataset.propField]=el.value; save();});
      $$("[data-prop-state]",card).forEach(el=>el.onclick=async()=>{try{await flush();await post(`/api/projects/${project.id}/props/${p.id}/generate`,{value:el.dataset.propState});poll();}catch(e){toast(e.message);}});
    });
  }
  $("[data-plan]", box).onclick = async () => { try { await flush(); await post(`/api/projects/${project.id}/plan-continuity`); poll(); } catch(e) { toast(e.message); } };
  $("[data-state-design]", box)?.addEventListener("input", e => {
    project.state_design = e.target.value; project.continuity_plan.design = e.target.value; save();
  });
  $$("[data-initial]", box).forEach(el => el.oninput = () => {
    if (!el.value.trim()) return;
    project.scene_state[el.dataset.initial] = el.value.trim(); save();
  });
  $("[data-add-fact]", box)?.addEventListener("click", () => {
    const key = $("[data-fact-name]", box).value.trim(), value = $("[data-fact-value]", box).value.trim();
    if (!key || !value) return toast("Enter a fact and its starting value");
    if (Object.hasOwn(project.scene_state, key)) return toast("That fact already exists");
    project.scene_state[key] = value; box.dataset.sig = ""; save(); renderContinuity();
  });
  $("[data-accept-plan]", box)?.addEventListener("click", async () => {
    try { project.accept_continuity = true; await flush(); } catch(e) { toast(e.message); }
    finally { delete project.accept_continuity; renderContinuity(); }
  });
}

function stateFields(shot) {
  if (!project.continuity_plan) return "";
  const before = project.asset_status?.[shot.id]?.state_before || {}, after = {...before, ...(shot.state_changes || {})};
  return `<details class="state-fields"><summary>Scene state · inherited → result</summary>
    <label>Starting reference<select data-frame-source><option value="storyboard">Storyboard composition</option><option value="previous_end" ${shot.frame_source==="previous_end"?"selected":""}>Preceding shot’s final frame</option></select></label>
    <label>Prop reference<select data-shot-prop><option value="">None</option>${(project.props||[]).map(p=>`<option value="${escapeHtml(p.id)}" ${shot.prop_id===p.id?"selected":""}>${escapeHtml(p.name)}</option>`).join("")}</select></label>
    <label class="state-check"><input type="checkbox" data-guide-end ${shot.guide_end?"checked":""}>Guide motion with a reviewed end frame</label>
    ${shot.keyframe?`<label>Bring an ending frame<input type="file" data-end-upload accept="image/png,image/jpeg,image/webp"></label>`:""}
    <p class="hint">Only change what this action changes. Checked facts must be visible for review.</p>
    ${Object.entries(before).map(([key,value])=>`<div class="state-row"><label>${escapeHtml(key)}<small>Before: ${escapeHtml(value)}</small>
      <input data-state-key="${escapeHtml(key)}" value="${escapeHtml(after[key])}" aria-label="${escapeHtml(key)} after shot"></label>
      <label class="state-check"><input type="checkbox" data-check="start_checks" data-fact="${escapeHtml(key)}" ${(shot.start_checks||[]).includes(key)?"checked":""}>Check start</label>
      <label class="state-check"><input type="checkbox" data-check="end_checks" data-fact="${escapeHtml(key)}" ${(shot.end_checks||[]).includes(key)?"checked":""}>Check end</label></div>`).join("")}
    <div class="state-grid">${["start","end"].map(phase=>`<label>People at ${phase}<input data-roster="${phase}_cast" value="${escapeHtml(shot[phase+"_cast"] === null ? "?" : (shot[phase+"_cast"] || []).join(", "))}"></label>`).join("")}</div>
    <p class="hint">Use character names separated by commas; ? for an uncountable group. An empty field means nobody is visible.</p></details>`;
}

function bindStateFields(box, shot) {
  $("[data-frame-source]",box)?.addEventListener("change",e=>{shot.frame_source=e.target.value;save();});
  $("[data-shot-prop]",box)?.addEventListener("change",e=>{shot.prop_id=e.target.value;save();});
  $("[data-guide-end]",box)?.addEventListener("change",e=>{shot.guide_end=e.target.checked;save();});
  $("[data-end-upload]",box)?.addEventListener("change",async e=>{
    const file=e.target.files[0];if(!file)return;
    try{await flush();const response=await fetch(`/api/projects/${project.id}/shots/${shot.id}/endframe-upload`,{method:'POST',headers:{'X-Filename':encodeURIComponent(file.name)},body:file});const fresh=await response.json();if(!response.ok)throw new Error(fresh.error);mergeServer(fresh,true);toast('Ending frame added. Inspect and accept it in Visual review.');}catch(error){toast(error.message);}
  });
  $$("[data-state-key]", box).forEach(el=>el.oninput=()=>{
    const value=el.value.trim(), key=el.dataset.stateKey;
    if (!value) return;
    shot.state_changes ||= {};
    if (value === project.asset_status?.[shot.id]?.state_before?.[key]) delete shot.state_changes[key];
    else shot.state_changes[key]=value;
    save();
  });
  $$("[data-check]", box).forEach(el=>el.onchange=()=>{
    const keys=new Set(shot[el.dataset.check] || []);
    if(el.checked) keys.add(el.dataset.fact); else keys.delete(el.dataset.fact);
    shot[el.dataset.check]=[...keys]; save();
  });
  $$("[data-roster]", box).forEach(el=>el.oninput=()=>{
    shot[el.dataset.roster]=el.value.trim()==="?" ? null : [...new Set(el.value.split(",").map(x=>x.trim()).filter(Boolean))]; save();
  });
}

function qualityFields(shot) {
  return `<section class="quality-panel"><h4>Visual review</h4>${["sketch","keyframe","endframe","video"].map(kind=>{
    const q=shot.quality?.[kind];
    const label=kind==="sketch"?"Storyboard":kind==="video"?"Video":kind==="endframe"?"Ending frame":"Opening frame";
    if(!q) return kind==='sketch'||kind==="endframe"&&!shot.guide_end?"":`<p class="hint">${label}: not reviewed</p>`;
    const failed=q.status!=="passed", provisional=/\bprovisional\b/i.test(q.director_review?.reason||'');
    return `<details ${failed||provisional?"open":""}><summary>${label} · ${provisional?"provisional — needs further review":q.director_review?"accepted by director":failed?"needs review":"checks passed"}</summary>
      ${q.findings?.length?`<ul class="quality-findings">${q.findings.map(x=>`<li>${escapeHtml(x)}</li>`).join("")}</ul>`:""}
      ${q.director_review?`<p>${escapeHtml(q.director_review.reason)}</p>`:""}
      ${failed?`<div class="quality-candidate">${kind==="video"?`<video src="${media(q.name)}" controls preload="metadata"></video>`:`<img src="${media(q.name)}" alt="Candidate that needs review">`}</div>
        ${kind==='keyframe'?(shot.frame_repairs||[]).filter(r=>r.phase==='start'&&r.name!==q.name).map(r=>`<div class="quality-candidate"><p class="hint">Earlier candidate from this repair</p><img src="${media(r.name)}" alt="Earlier opening frame candidate"><button type="button" class="ghost small" data-accept-review="keyframe" data-candidate="${escapeHtml(r.name)}">Accept this earlier candidate after inspection</button></div>`).join(''):''}
        ${kind==='sketch'?'<button type="button" class="ghost small" data-redraw-candidate>Redraw this shot</button>':kind!=="video"?`<button type="button" class="ghost small" data-repair-frame="${kind}">Repair these findings</button>`:""}
        <label>Director's reason for accepting this candidate<input data-reason="${kind}" placeholder="Record what you inspected and why it is acceptable"></label>
        <button type="button" class="ghost small" data-accept-review="${kind}" data-candidate="${escapeHtml(q.name)}">Accept after inspection</button>`:""}</details>`;
    }).join("")} ${shot.video?`<button type="button" class="ghost small" data-review-video>Review current video</button>`:""}
    <p class="hint">Video checks sample four moments. They can miss events between samples; review the full clip before delivery.</p></section>`;
}

function bindQuality(box, shot) {
  $('[data-redraw-candidate]',box)?.addEventListener('click',async()=>{try{await flush();await post(`/api/projects/${project.id}/shots/${shot.id}/sketch`);poll();}catch(e){toast(e.message)}});
  $$("[data-repair-frame]",box).forEach(b=>b.onclick=async()=>{try{await flush();await post(`/api/projects/${project.id}/shots/${shot.id}/repair-frame`,{kind:b.dataset.repairFrame});poll();}catch(e){toast(e.message);}});
  $("[data-review-video]",box)?.addEventListener("click",()=>queueShot(shot,"review"));
  $$("[data-accept-review]",box).forEach(button=>button.onclick=async()=>{
    const kind=button.dataset.acceptReview, reason=$(`[data-reason="${kind}"]`,box).value.trim();
    if(!reason) return toast("Inspect the candidate and record a reason first");
    try { await flush(); mergeServer(await post(`/api/projects/${project.id}/shots/${shot.id}/accept-review`,{kind,name:button.dataset.candidate,reason}),true); }
    catch(e) { toast(e.message); }
  });
}

function paintScript() {  // the film as a screenplay: each beat a scene, each shot its action, then what is said
  const box = $("#script");
  if (box.hidden || box.contains(document.activeElement) && document.activeElement.matches("input,textarea")) return;
  const sig = JSON.stringify([beatsOf(), project.asset_status, project.shots.map(s => [s.id, s.beat, s.action, s.line, s.others, s.lead, s.start_frame, s.end_state, s.beat_source])]);
  if (box.dataset.sig === sig) return;
  box.dataset.sig = sig;
  const shots = project.shots.filter(s => s.action?.trim());
  if (!shots.length) { box.innerHTML = `<p class="hint">No shots yet. Write shots and the script appears here.</p>`; return; }
  let html = `<p class="sc-help">Edit action, dialogue and staging here. Edits save automatically; Render film rebuilds affected frames and videos. Changed beats need a shot review first.</p>`, lastBeat = -1;
  for (const s of shots) {
    const beat = s.beat && s.beat <= beatsOf().length ? s.beat : 0;
    if (beat !== lastBeat) {
      html += `<h4 class="sc-head">${beat ? `${beat}. ${escapeHtml(beatsOf()[beat - 1])}` : "Not in the story yet"}</h4>`;
      lastBeat = beat;
    }
    html += `<article class="sc-shot" data-id="${s.id}">
      <span class="sc-num">${String(shotIndex(s.id) + 1).padStart(2, "0")}</span>
      <label class="sc-field">Action<textarea class="grow sc-action" rows="2" data-script="action" aria-label="Shot ${shotIndex(s.id) + 1} action">${escapeHtml(s.action)}</textarea></label>
      <label class="sc-field sc-dialogue">Dialogue<textarea class="grow" rows="1" data-script="line" placeholder='Lead: "Words spoken aloud"' aria-label="Shot ${shotIndex(s.id) + 1} dialogue">${escapeHtml(s.line || "")}</textarea></label>
      <details><summary>Staging · ${escapeHtml(s.shot_size)}</summary>
        <label class="sc-field">First frame<textarea class="grow" rows="2" data-script="start_frame">${escapeHtml(s.start_frame || "")}</textarea></label>
        <label class="sc-field">End state<textarea class="grow" rows="2" data-script="end_state">${escapeHtml(s.end_state || "")}</textarea></label></details>
      ${stateFields(s)}
      <div class="sc-tools"><span>${escapeHtml(staleness(s))}</span><button type="button" data-open>Shot settings</button>
      ${storyStale(s) ? `<button type="button" data-rewrite>Rewrite for changed beat</button><button type="button" data-accept>Still tells this beat</button>` : ""}</div></article>`;
  }
  box.innerHTML = html;
  $$(".sc-shot", box).forEach(row => {
    const shot = project.shots.find(s => s.id === row.dataset.id);
    bindStateFields(row, shot);
    $("[data-open]", row).onclick = () => { setStage("shots"); select(shot.id); };
    $("[data-rewrite]", row)?.addEventListener("click", () => writeShots("rewrite", shot));
    $("[data-accept]", row)?.addEventListener("click", () => acceptBeat(shot));
    $$("[data-script]", row).forEach(field => {
      field.oninput = () => { shot[field.dataset.script] = field.value; shot.ai = false; save(); };
      field.onblur = () => { box.dataset.sig = ""; };
    });
    $("details", row).ontoggle = () => growAll(row);
  });
  requestAnimationFrame(() => growAll(box));
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
    ["continuity", "continuityField"], ["characters", "charactersField"]];
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
    $("#filmLook").value = project.look || "";
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
      <div class="meta"><span class="beat-chip" hidden></span><p class="action"></p><p class="said" hidden></p><div class="facts"><span class="mini-cam"><span class="cam-scene"><span></span></span></span>
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
  const failed = jobs.filter(j => j.project === project.id && j.state === "failed" && ["write_story", "write_shots", "sketch"].includes(j.kind));
  if (seenFailures === null) { seenFailures = new Set(failed.map(j => j.id)); return; }
  const fresh = failed.filter(j => !seenFailures.has(j.id));
  fresh.forEach(j => seenFailures.add(j.id));
  const j = fresh.at(-1);
  if (!j) return;
  if (j.kind === "write_story") toast(`Gemma couldn't finish the story: ${j.error}`, "Try again", () => writeStory(j.target, j.count));
  else if (j.kind === "write_shots") toast(`Gemma couldn't write the shots: ${j.error}`, "Try again", () => writeShots(j.mode, project.shots.find(s => s.id === j.shot)));
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
  const said = $(".said", card), [who, ...words] = (shot.line || "").split(":");
  said.hidden = !shot.line?.trim();
  said.innerHTML = shot.line?.trim() ? (words.length ? `<b>${escapeHtml(who.trim())}</b> ${escapeHtml(words.join(":").trim())}` : escapeHtml(shot.line)) : "";
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
    <label>First frame · before the action<textarea class="grow" data-k="start_frame" rows="2" placeholder="Viewpoint, people, hands and prop positions">${escapeHtml(shot.start_frame || "")}</textarea></label>
    <label>End state · what changes<textarea class="grow" data-k="end_state" rows="2" placeholder="The visible result the next shot picks up">${escapeHtml(shot.end_state || "")}</textarea></label>
    ${storyStale(shot) ? `<p class="hint">The story beat changed. Rewrite this shot, or <button type="button" data-act="accept-beat">Still tells this beat</button>.</p>` : ""}
    ${beatsOf().length ? `<div class="beat-pick"><label>Story beat<select data-beat>${[`<option value="">Not in the story yet</option>`, ...beatsOf().map((b, n) =>
      `<option value="${n + 1}"${shot.beat === n + 1 ? " selected" : ""}>${n + 1} · ${escapeHtml(b.length > 70 ? b.slice(0, 68) + "…" : b)}</option>`)].join("")}</select></label>
      ${shot.beat ? "" : `<button type="button" class="ai small" data-act="place" title="Gemma writes the beat this shot tells and adds it to the story">✨ Add to story</button>`}</div>` : ""}
    <div class="ins-sketch"><div class="ins-sketch-img"></div><div class="ins-sketch-side"><b>Storyboard</b><span class="hint"></span>
      <button type="button" class="ghost small" data-act="sketch">Draw</button></div></div>
    <div class="cam-field"><label>Camera move<select data-k="camera_move">${opts(presets.camera_moves, shot.camera_move)}</select></label>
      <div class="cam-preview" title="Camera move preview"><div class="cam-scene"><span></span></div></div></div>
    <div class="field-row"><label>Shot size<select data-k="shot_size">${opts(presets.shot_sizes, shot.shot_size)}</select></label>
      <label>Seconds<input data-k="seconds" type="number" min="2" max="10" step="1" value="${shot.seconds}"></label></div>
    <label>Also in the shot<input data-k="others" value="${escapeHtml(shot.others || "")}" placeholder="Other characters by name, or a group: Mara, a crowd of dockworkers…"></label>
    <label>Dialogue<input data-k="line" value="${escapeHtml(shot.line || "")}" placeholder='What is said aloud: Mara: "We should go." (or Lead: …)'></label>
    <label>Sound<input data-k="sound" value="${escapeHtml(shot.sound)}" placeholder="What we hear besides speech: wind, waves, footsteps…"></label>
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
    </section><div class="state-host">${stateFields(shot)}</div><div class="quality-host">${qualityFields(shot)}</div>`;
  bindStateFields(ins, shot); bindQuality(ins, shot);
  $(".cam-scene", ins).style.animation = CAMERA_ANIM[shot.camera_move] || "";
  requestAnimationFrame(() => growAll(ins));
  for (const field of $$("[data-k]", ins)) {
    const key = field.dataset.k;
    field.addEventListener(field.tagName === "SELECT" || field.type === "checkbox" ? "change" : "input", () => {
      shot[key] = field.type === "checkbox" ? field.checked : field.type === "number" ? Number(field.value) : field.value;
      shot.ai = false;  // any direction edited by you is kept by Write shots
      paintScript();
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
  $('[data-act="accept-beat"]', ins)?.addEventListener("click", () => acceptBeat(shot));
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
    : !shot.sketch ? "A monochrome staging drawing sets the first frame's composition, poses and props."
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
  const state = $(".state-host", ins), ssig = stateFields(shot);
  if (state && state.dataset.sig !== ssig && !state.contains(document.activeElement)) {
    const open = $("details", state)?.open;
    state.dataset.sig = ssig; state.innerHTML = ssig;
    if (open && $("details", state)) $("details", state).open = true;
    bindStateFields(state, shot);
  }
  const quality = $(".quality-host", ins), qsig = JSON.stringify([shot.quality, shot.video]);
  if (quality && quality.dataset.sig !== qsig && !quality.contains(document.activeElement)) {
    quality.dataset.sig = qsig; quality.innerHTML = qualityFields(shot); bindQuality(quality, shot);
  }
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
  if (r.kind === "shot" && r.world_reference !== false) inputs.push(ing(r.world ? media(r.world) : "", "The world", r.world ? "Place, light and grade" : "Painted first", "world"));
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
    steps.unshift(drawing.of?.visual ? "HiDream-O1 · independent staging drawing · grayscale and cast check" :
      `Qwen-Image-Edit 2511 · draws the storyboard from ${from.filter(Boolean).join(" + ")} · half size`);
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

function picture(shot) { const candidate=shot.quality?.keyframe?.name||shot.quality?.sketch?.name; return shot.keyframe ? media(shot.keyframe) : shot.sketch ? media(shot.sketch) : candidate?media(candidate):""; }

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
  $("#drawBoard").hidden = !project.shots.some(s => s.action?.trim() && (!s.sketch || sketchStale(s))) || !!busyFor(j => j.kind === "sketch");
  paintStrip(); paintScript();
}

function sketchStale(shot) {  // mirrors studio._current_sketch: is the drawing from today's shot, world and lead?
  if (project.asset_status?.[shot.id]?.sketch) return true;
  const take = (shot.sketches || []).find(t => t.name === shot.sketch);
  if (!take) return !!shot.sketch;
  const of = take.of || {};
  return of.action !== (shot.action || "") || of.shot_size !== shot.shot_size || of.camera_move !== shot.camera_move
    || of.lead !== (shot.lead !== false) || of.others !== (shot.others || "")
    || of.visual?.start_frame !== (shot.start_frame || "");
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

const fmtTime = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;  // as the player shows it

function filmChanges() {  // what changed since the cut was made ([] when it's up to date, or when we can't tell)
  const was = project.film_of, now = project.film_now;
  if (!project.film || !was || !now) return [];
  const changes = [], before = new Map(was.shots.map(([id, video, tr], i) => [id, { video, tr, i }]));
  if (project.shots.some(s => storyStale(s) || project.asset_status?.[s.id]?.frame || project.asset_status?.[s.id]?.video))
    changes.push("script or staging changed · render affected shots");
  const ids = now.shots.map(s => s[0]);
  const added = ids.filter(id => !before.has(id)).length, removed = was.shots.filter(s => !ids.includes(s[0])).length;
  if (added) changes.push(`${added} shot${added > 1 ? "s" : ""} added`);
  if (removed) changes.push(`${removed} shot${removed > 1 ? "s" : ""} removed`);
  const kept = was.shots.map(s => s[0]).filter(id => ids.includes(id));
  if (JSON.stringify(kept) !== JSON.stringify(ids.filter(id => before.has(id)))) changes.push("shots reordered");
  const redone = now.shots.map(([id, video], i) => before.has(id) && before.get(id).video !== video ? i + 1 : 0).filter(Boolean);
  if (redone.length) changes.push(`shot${redone.length > 1 ? "s" : ""} ${redone.join(", ")} re-rendered`);
  if (now.shots.some(([id, , tr]) => before.has(id) && before.get(id).tr !== tr)) changes.push("transitions changed");
  if (JSON.stringify([was.titles, was.title, was.look, was.palette, was.title_shot]) !==
      JSON.stringify([now.titles, now.title, now.look, now.palette, now.title_shot])) changes.push("titles changed");
  if (was.finish !== now.finish) changes.push("film finish changed");
  return changes;
}

let autoCutFor = null, autoCutTimer = null;
function autoRecut(changes) {  // with auto-render on, an out-of-date cut re-cuts itself once there's nothing to wait for
  const ready = changes.length && project.auto_render !== false && project.shots.every(s => s.video && !s.paused)
    && !project.shots.some(s => storyStale(s) || project.asset_status?.[s.id]?.frame || project.asset_status?.[s.id]?.video)
    && !busyFor(() => true);
  const sig = JSON.stringify(project.film_now);
  if (!ready || autoCutFor === sig) { clearTimeout(autoCutTimer); autoCutTimer = null; return; }
  if (autoCutTimer) return;
  autoCutTimer = setTimeout(async () => {  // wait for the edits to settle before cutting
    autoCutTimer = null;
    jobs = await api("/api/jobs");  // a fresh look: another action may have just queued a cut
    if (JSON.stringify(project.film_now) !== sig || busyFor(() => true)) return;
    autoCutFor = sig;
    await post(`/api/projects/${project.id}/stitch`); poll();
  }, 2500);
}

function pausedNote() {
  const paused = project.shots.map((s, i) => s.paused ? i + 1 : 0).filter(Boolean);
  return paused.length ? `Shot${paused.length > 1 ? "s" : ""} ${paused.join(", ")} ${paused.length > 1 ? "are" : "is"} paused` : "";
}

function resumeAll() {
  project.shots.filter(s => s.paused).forEach(s => pauseShot(s, false));
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
  const length = v.duration > 0 && src ? fmtTime(v.duration) : `about ${fmtTime(total)}`;  // the cut adds titles and credits
  $("#viewerInfo").textContent = src ? (view === "trailer" ? `Trailer · ${length} · score composed by LTX`
    : `${project.shots.length} shot${project.shots.length === 1 ? "" : "s"} · ${length}`) : `${done}/${project.shots.length} shots rendered`;
  const cutting = busyFor(j => j.kind === "stitch"), changes = view === "film" ? filmChanges() : [];
  const paused = pausedNote(), stale = $("#filmStale");
  stale.hidden = !(changes.length || paused) || !!cutting;
  stale.textContent = paused ? `${paused}, so the film can't be cut` : `Out of date: ${changes.join(", ")}`;
  const missing = project.shots.some(needsRender);
  const known = !!project.film_of;  // a cut from before cuts remembered their inputs: we can't tell, so offer it
  $("#stitch").disabled = !!cutting || (!!project.film && known && !changes.length && !missing && !paused);
  $("#stitch").textContent = cutting ? (cutting.state === "running" ? "Cutting…" : "Queued…")
    : paused ? "▶ Resume & cut" : missing ? "Render & cut" : !project.film ? "Cut film" : changes.length || !known ? "Re-cut film" : "Up to date";
  $("#stitch").title = paused ? "Resume the paused shots; the film is cut when they're done"
    : missing ? "Renders the missing shots, then cuts the film" : project.film && !changes.length ? "Nothing changed since this cut" : "";
  autoRecut(changes);
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
  const pic = $("#pictureTrack"), titles = $("#titlesTrack"), sound = $("#soundTrack"), story = $("#storyTrack");
  pic.innerHTML = ""; titles.innerHTML = ""; story.innerHTML = "";
  // the cut's real sound once there is one; it spans the whole film, titles and credits included
  sound.innerHTML = project.film_wave ? `<div class="wave real" style="background-image:url('${media(project.film_wave)}')" title="The film's sound"></div>`
    : `<div class="wave" title="Cut the film to see its sound"></div>`;
  if (project.film && !project.film_wave && !renderTimeline.asked) {
    renderTimeline.asked = true;
    post(`/api/projects/${project.id}/waveform`).then(fresh => { project.film_wave = fresh.film_wave; if (fresh.film_wave) renderTimeline(); });
  }
  const band = (grow, joints, text, cls) => {  // a story beat spanning its shots (and the joints between them)
    const el = document.createElement("div");
    el.className = "band " + cls; el.style.flexGrow = grow; el.style.flexBasis = `${joints * 24}px`;
    el.textContent = text; el.title = text;
    story.appendChild(el);
  };
  const clip = (grow, html, cls, bg) => {
    const el = document.createElement("div");
    el.className = "clip " + cls; el.style.flexGrow = grow; el.innerHTML = html;
    if (bg) el.style.backgroundImage = `url("${bg}")`;
    return el;
  };
  const layer = (grow, text, on) => {
    const el = document.createElement("div");
    el.className = "layer " + (text ? (on ? "on" : "off") : "gap"); el.style.flexGrow = grow; el.textContent = text || ".";
    if (text) el.title = text;
    titles.appendChild(el);
  };
  if (inworld) {
    pic.appendChild(clip(4, `<b>TITLE</b><small>in-world · 4s</small>`, "", media(project.title_shot.keyframe)));
    pic.appendChild(Object.assign(document.createElement("button"), { className: "joint dissolve", textContent: JOINT.dissolve, title: "Dissolve", disabled: true }));
    layer(4, "IN-WORLD TITLE", true);
    band(4, 0, "", "gap");
  }
  let run = null;  // consecutive shots telling the same beat share one band
  const endRun = () => { if (run) band(run.secs, run.n - 1, run.beat ? `${run.beat} · ${beatsOf()[run.beat - 1]}` : "", run.beat ? "on" : "gap"); };
  shots.forEach(shot => {
    const beat = shot.beat && shot.beat <= beatsOf().length ? shot.beat : 0;
    if (run && run.beat === beat && beat) { run.secs += Number(shot.seconds); run.n++; return; }
    endRun(); run = { beat, secs: Number(shot.seconds), n: 1 };
  });
  endRun();
  shots.forEach((shot, i) => {
    if (i > 0) {
      const t = shot.transition || "cut";
      const j = document.createElement("button");
      j.className = "joint " + t; j.textContent = JOINT[t]; j.title = `${JOINT_NAME[t]} — click to change`;
      j.onclick = () => { shot.transition = TRANSITIONS[(TRANSITIONS.indexOf(t) + 1) % 3]; renderTimeline(); paintBoard(); if (selected === shot.id) renderInspector(); save(); };
      pic.appendChild(j);
    }
    const c = clip(shot.seconds, `<b>${String(i + 1).padStart(2, "0")}</b><small>${escapeHtml(shot.camera_move)} · ${shot.seconds}s</small>`,
      (shot.video ? "" : "pending") + (shot.paused ? " paused" : ""), shot.keyframe ? media(shot.keyframe) : "");
    c.draggable = true; c.dataset.id = shot.id;
    c.title = `Shot ${i + 1} · ${shot.camera_move} · ${shot.seconds}s${shot.paused ? " · paused" : shot.video ? "" : " · not rendered"}\nDrag to reorder · click to open`;
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
    band(3, 0, "", "gap");
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
  if (project.film && project.shots.some(needsRender)) $("#screenInfo").textContent += " · Older cut — render script changes";
  if (project.film && project.shots.some(s=>project.asset_status?.[s.id]?.review)) $("#screenInfo").textContent += " · Continuity review required";
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
  if ((fresh.continuity_rev || 0) !== (project.continuity_rev || 0)) {
    project.scene_state = fresh.scene_state;
    fresh.shots.forEach(s=>{
      const current=project.shots.find(x=>x.id===s.id);
      if(current) for(const key of ["state_changes","start_checks","end_checks","start_cast","end_cast"]) current[key]=s[key];
    });
  }
  project.continuity_rev=fresh.continuity_rev;
  project.continuity_plan=fresh.continuity_plan;
  project.continuity_status=fresh.continuity_status;
  project.continuity_fixes=fresh.continuity_fixes;
  project.continuity_error=fresh.continuity_error;
  if (!$(".prop-panel")?.contains(document.activeElement)) project.props=fresh.props;
  else (project.props||[]).forEach((p,i)=>{const f=(fresh.props||[]).find(x=>x.id===p.id)||(!p.id?fresh.props?.[i]:null);if(f){p.id=f.id;p.variants=f.variants;}});
  delete project.state_design;
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
    renderBeats(); renderContinuity();
    return;
  }
  // keep what the user is typing; take generated media from the server
  fresh.shots.forEach((s, i) => Object.assign(project.shots[i], { id: s.id, keyframe: s.keyframe, video: s.video, takes: s.takes, seed: s.seed,
    sketch: s.sketch, sketches: s.sketches, endframe:s.endframe, endframes:s.endframes, paused: s.paused, beat_source: s.beat_source, quality: s.quality }));
  project.asset_status = fresh.asset_status;
  for (const k of ["film", "film_of", "film_now", "film_wave", "master", "master_of", "trailer", "motion_preview", "motion_defaults", "title_shot", "trailer_score", "reference",
    "lead_identity", "lead_identity_of", "world"]) project[k] = fresh[k];
  if ((fresh.story_history || []).length !== (project.story_history || []).length) adoptStory(fresh);  // the AI (or undo) changed the page
  project.story_history = fresh.story_history;
  paintBoard(); paintInspector(); paintPortrait(); renderViewer(); renderEditPanel(); renderTimeline(); renderScreen(); renderHeader(); applyTheme();
  paintBeatShots();
  paintScript();
  renderContinuity();
}

async function queueShot(shot, kind) {
  try { await flush(); await post(`/api/projects/${project.id}/shots/${shot.id}/${kind}`); toast(kind === "video" ? "Shot queued" : "New frame queued"); poll(); }
  catch (error) { toast(error.message); }
}

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
let pollInFlight = false;
let pollPending = false;
let jobEvents;
function startJobEvents() {
  if (typeof EventSource !== 'undefined') {
    jobEvents = new EventSource('/api/events');
    jobEvents.onmessage = () => poll();
    jobEvents.onopen = () => poll();
  }
  setInterval(() => {
    if (!jobEvents || jobEvents.readyState !== EventSource.OPEN) poll();
  }, 5000);
  // Reconcile even if an intermediary silently drops notifications.
  setInterval(poll, 30000);
}
async function poll() {
  if (pollInFlight) { pollPending = true; return; }
  pollInFlight = true;
  try {
    jobs = await api("/api/jobs");
    const sig = jobs.filter(j => j.project === project.id).map(j => j.id + j.state).join();
    if (sig !== lastSignature) {
      lastSignature = sig;
      mergeServer(await api(`/api/projects/${project.id}`));
      projects = await api("/api/projects");
    } else if (jobs.some(j => j.project === project.id && active(j))) {
      paintBoard(); paintInspector(); paintPortrait();
      if (stage === "story") { paintScript(); renderContinuity(); }
      if (stage === "edit") { renderViewer(); paintTitleShot(); }
      if (stage === "screen") renderScreen();
    }
    renderStatus();
    noticeFailures();
  } catch { presets.comfy = false; renderStatus(); }
  finally {
    pollInFlight = false;
    if (pollPending) { pollPending = false; setTimeout(poll, 100); }
  }
}

// ---------------------------------------------------------------- wiring
$$(".stages button").forEach(b => b.onclick = () => setStage(b.dataset.stage));
$$("[data-goto]").forEach(b => b.onclick = () => setStage(b.dataset.goto));
$("#projectBtn").onclick = e => { e.stopPropagation(); renderProjectMenu(); $("#projectMenu").hidden = !$("#projectMenu").hidden; };
$("#newProject").onclick = async () => { $("#projectMenu").hidden = true; await flush(); createProject(); };
let performanceSaving=false;
$$('[data-ai-mode]').forEach(input=>input.onchange=async e=>{
  if(!e.target.checked || e.target.value===(project.ai_mode||'normal')) return;
  if(performanceSaving){renderStatus();return;}
  const previous=project.ai_mode||'normal';
  project.ai_mode=e.target.value;
  performanceSaving=true;
  try{await flush();renderStatus();renderSetup();if(selectedSetupReady()===false){$('#setupPanel').hidden=false;renderSetup();}toast(`${project.ai_mode==='fast'?'Fast':'Standard'} applies to new jobs. Existing work is kept.`);}
  catch(error){project.ai_mode=previous;renderStatus();toast(error.message);}
  finally{performanceSaving=false;}
});
['#statusPill','#productionDetails'].forEach(id=>$(id).onclick=e=>{e.stopPropagation();setQueueOpen($('#queue').hidden)});
$('#closeQueue').onclick=()=>{setQueueOpen(false);$('#statusPill').focus()};
$('#resumeWork').onclick=()=>$('#renderFilm').click();
$('#queue').addEventListener('click',async e=>{
  const inspect=e.target.closest('[data-inspect-job]'),retry=e.target.closest('[data-retry-job]'),fix=e.target.closest('[data-fix-continuity]'),review=e.target.closest('[data-review-continuity]');
  if(inspect){selected=inspect.dataset.inspectJob;setQueueOpen(false);setStage('shots');renderInspector();paintBoard();$('#inspector').scrollIntoView({block:'start',behavior:'smooth'});}
  if(retry){retry.disabled=true;try{await flush();await post(`/api/jobs/${retry.dataset.retryJob}/retry`);await poll();}catch(error){toast(error.message);retry.disabled=false;}}
  if(review){setQueueOpen(false);setStage('story');renderContinuity();$('#continuityPanel').scrollIntoView({block:'start',behavior:'smooth'});}
  if(fix){fix.disabled=true;try{await flush();const result=await post(`/api/jobs/${fix.dataset.fixContinuity}/auto-fix`,{continuity_rev:project.continuity_rev||0});mergeServer(result.project,true);renderContinuity();await poll();toast(result.warning?'Fixed the stale warning, but could not resume: '+result.warning:result.remaining.length?'Fixed the stale warning. Other continuity issues still need your review.':result.resumed?'Fixed the stale warning and resumed generation.':'Fixed the stale warning. Scene continuity is ready.');}catch(error){toast(error.message);fix.disabled=false;}}
});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('#queue').hidden){setQueueOpen(false);$('#statusPill').focus()}});
document.addEventListener("click", e => {
  if (!e.target.closest("#projectMenu, #projectBtn")) $("#projectMenu").hidden = true;
  if (!e.target.closest("#queue, #statusPill, #productionDetails")) setQueueOpen(false);
});
document.addEventListener("keydown", e => { if (e.key === "Escape") { $("#projectMenu").hidden = true; $("#queue").hidden = true; } });
$("#cancelAll").onclick = () => post("/api/cancel", {project:project.id}).then(poll).catch(error=>toast(error.message));
$("#renderFilm").onclick = async () => {
  if(setupState && !setupState.ready){$('#setupPanel').hidden=false;await checkSetup(true);return;}
  try { await flush(); await post(`/api/projects/${project.id}/render`); }
  catch (error) { toast(error.message); return; }
  const paused = pausedNote();  // paused shots are skipped, and the film can't be cut without them
  if (paused) toast(`Rendering the rest. ${paused}, so the film won't be cut until you resume`, "Resume", resumeAll);
  else toast("Rendering everything that's missing");
  poll();
};

for (const id of ["title", "idea", "logline", "scene", "continuity", "cast", "characters"]) $("#" + id).oninput = e => {
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
$("#filmLook").oninput = e => {
  preservePalette(); project.look = e.target.value;
  $$("#looks .look").forEach(b => b.classList.toggle("on", $(".look-name", b).textContent === project.look));
  applyTheme(); renderEditPanel(); save();
};
$("#imageQuality").onchange=e=>{project.image_quality=e.target.value;save();};
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
  if (pausedNote()) { resumeAll(); toast("Resuming the paused shots; the film is cut when they're done"); return; }
  const complete = !project.shots.some(s=>needsRender(s) || project.asset_status?.[s.id]?.review) && project.continuity_status === "ready";
  try { await post(`/api/projects/${project.id}/${complete ? "stitch" : "render"}`); }
  catch (error) { toast(error.message); return; }
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
