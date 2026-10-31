"""Open Cinema Studio pipeline: projects, shot lists and the GPU job queue."""

from __future__ import annotations

import array
import copy
import hashlib
import json
import queue
import random
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_nodes" / "comfyui-open-cinema"))

import director  # noqa: E402
import graphs  # noqa: E402
from comfy import Comfy  # noqa: E402

PROJECTS = ROOT / "projects"

MOTION_VERSION = 2
MOTION_DEFAULTS: dict[str, Any] = {
    "title": {"on": True, "subtitle": "A film made with open models", "style": "kinetic", "material": ""},
    "stamps": {"on": False},
    "credits": {"on": True, "lines": ""},
    "trailer": {"lines": ""},
}


def motion_settings(project: dict[str, Any]) -> dict[str, Any]:
    """The project's motion graphics settings over the defaults."""
    settings = copy.deepcopy(MOTION_DEFAULTS)
    for key, value in (project.get("motion") or {}).items():
        if isinstance(value, dict) and key in settings:
            settings[key].update(value)
    return settings


def palette_string(project: dict[str, Any]) -> str:
    """The film's custom colours as 'bg,ink,accent,glow' for the motion nodes; '' means the look's palette."""
    p = project.get("palette") or {}
    colours = [p.get(k, "") for k in ("bg", "ink", "accent", "glow")]
    return ",".join(colours) if all(c.startswith("#") and len(c) == 7 for c in colours) else ""


STORY_FIELDS = ("title", "logline", "scene", "look", "palette", "cast", "continuity")


def default_credits(project: dict[str, Any]) -> str:
    return "\n".join([project["title"],
                      "Made with open models | HiDream-O1 · Qwen-Image-Edit · LTX 2.5 · SeedVR2",
                      "Made in | Open Cinema Studio"])


def default_trailer(project: dict[str, Any]) -> str:
    return "\n".join(["Open Cinema presents", "A film in " + str(len(project["shots"])) + " shots"])


def onsets(path: Path, min_gap: float = 0.45) -> list[float]:
    """Times of the clear hits in an audio track (energy jumps well above the recent level)."""
    pcm = subprocess.run([ffmpeg(), "-loglevel", "error", "-i", str(path), "-ac", "1", "-ar", "8000",
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) // 2 * 2])
    window = 160  # 20 ms
    energy = [sum(x * x for x in samples[i:i + window]) / window for i in range(0, len(samples) - window, window)]
    flux = [max(0.0, energy[i] - sum(energy[max(0, i - 8):i]) / max(1, min(8, i))) for i in range(len(energy))]
    if not flux:
        return []
    threshold = sorted(flux)[int(len(flux) * 0.9)] or 1.0
    hits: list[float] = []
    for i in range(1, len(flux) - 1):
        if flux[i] >= threshold and flux[i] >= flux[i - 1] and flux[i] >= flux[i + 1]:
            t = i * window / 8000
            if not hits or t - hits[-1] >= min_gap:
                hits.append(t)
            elif flux[i] > flux[int(hits[-1] * 8000 / window)]:
                hits[-1] = t
    return hits


def snap(target: float, hits: list[float], lo: float, hi: float) -> float:
    """The hit nearest `target` inside [lo, hi], or `target` itself when the score has none there."""
    near = [h for h in hits if lo <= h <= hi]
    return min(near, key=lambda h: abs(h - target)) if near else target


def new_shot(**fields: Any) -> dict[str, Any]:
    shot = {"id": uuid.uuid4().hex[:8], "action": "", "shot_size": "Wide", "camera_move": "Dolly in",
            "seconds": 4.0, "sound": "", "transition": "cut", "lead": True, "keyframe": None, "video": None,
            "seed": random.randrange(1, 2**31)}
    shot.update(fields)
    return shot


def take_seed(shot: dict[str, Any], kind: str) -> int:
    """Take 1 uses the shot's seed; every re-roll gets a new, reproducible one."""
    return (shot["seed"] + 1_000_003 * len(shot.get("takes", {}).get(kind, []))) % 2**31


def lead_identity(project: dict[str, Any]) -> str:
    """What every prompt is told about the lead's face, written by Gemma from the current portrait."""
    return project.get("lead_identity", "") if project.get("lead_identity_of") == project.get("reference") else ""


def anchor_of(project: dict[str, Any]) -> dict[str, Any] | None:
    """The shot whose frame sets the world for every other shot: the pinned one, else shot 1."""
    shots = project["shots"]
    pinned = next((s for i, s in enumerate(shots) if s["id"] == project.get("anchor")
                   and not (i > 0 and s.get("transition") == "continue")), None)
    return pinned or (shots[0] if shots else None)


def add_take(shot: dict[str, Any], kind: str, name: str, **info: Any) -> None:
    """Record a new keyframe or video take and make it current."""
    shot.setdefault("takes", {}).setdefault(kind, []).append({"name": name, **info})
    if kind == "keyframe":
        shot["keyframe"], shot["video"] = name, None
    else:
        shot["video"] = name


def select_take(shot: dict[str, Any], kind: str, name: str) -> None:
    takes = shot.get("takes", {})
    match = next((t for t in takes.get(kind, []) if t["name"] == name), None)
    if not match:
        raise KeyError(f"no {kind} take {name}")
    if kind == "video":
        shot["video"] = name
        shot["keyframe"] = match.get("keyframe") or shot["keyframe"]
    else:
        # bring back the newest video that was rendered from this keyframe, if any
        shot["keyframe"] = name
        shot["video"] = next((t["name"] for t in reversed(takes.get("video", []))
                              if t.get("keyframe") == name), None)


def ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if not found:
        raise RuntimeError("ffmpeg was not found on PATH; it is needed to stitch the film")
    return found


def duration(path: Path) -> float:
    probe = shutil.which("ffprobe") or ffmpeg().replace("ffmpeg", "ffprobe")
    result = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                            check=True, capture_output=True, text=True)
    return float(result.stdout.strip())


DISSOLVE = 0.6  # seconds
EDGE_FADE = 0.03  # de-click every hard cut


FILM_FINISH = "unsharp=5:5:0.35:5:5:0,vignette=angle=PI/8,noise=c0s=6:c0f=t+u"  # sharpen, vignette, grain


def cut_filter(videos: list[Path], transitions: list[str], finish: bool = False) -> tuple[list[str], str]:
    """ffmpeg inputs + filter graph for the final cut.

    cut: hard cut with a few ms of audio fade so it doesn't click.
    continue: the clip opens on the previous clip's last frame, so that frame is dropped.
    dissolve: video crossfade and audio crossfade.
    """
    inputs: list[str] = []
    parts: list[str] = []
    lengths: list[float] = []
    for i, video in enumerate(videos):
        inputs += ["-i", str(video)]
        length = duration(video)
        mode = transitions[i] if i else "cut"
        if mode == "continue":
            parts.append(f"[{i}:v]trim=start_frame=1,setpts=PTS-STARTPTS,fps=24,format=yuv420p,settb=AVTB[v{i}]")
            length -= 1 / 24
        else:
            parts.append(f"[{i}:v]fps=24,format=yuv420p,settb=AVTB,setpts=PTS-STARTPTS[v{i}]")
        parts.append(f"[{i}:a]aresample=48000,atrim=0:{length:.4f},asetpts=PTS-STARTPTS,"
                     f"afade=t=in:d={EDGE_FADE},afade=t=out:st={max(0, length - EDGE_FADE):.4f}:d={EDGE_FADE}[a{i}]")
        lengths.append(length)
    video, audio, total = "v0", "a0", lengths[0]
    for i in range(1, len(videos)):
        if transitions[i] == "dissolve":
            offset = max(0.0, total - DISSOLVE)
            parts.append(f"[{video}][v{i}]xfade=transition=fade:duration={DISSOLVE}:offset={offset:.4f}[vx{i}]")
            parts.append(f"[{audio}][a{i}]acrossfade=d={DISSOLVE}[ax{i}]")
            total += lengths[i] - DISSOLVE
        else:
            parts.append(f"[{video}][{audio}][v{i}][a{i}]concat=n=2:v=1:a=1[vx{i}][ax{i}]")
            total += lengths[i]
        video, audio = f"vx{i}", f"ax{i}"
    parts.append(f"[{video}]{FILM_FINISH if finish else 'null'}[v]")
    parts.append(f"[{audio}]loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[a]")
    return inputs, ";".join(parts)


class Studio:
    def __init__(self, comfy_url: str):
        self.comfy = Comfy(comfy_url)
        self.lock = threading.RLock()
        self.jobs: list[dict[str, Any]] = []
        self.queue: queue.Queue[dict[str, Any]] = queue.Queue()
        PROJECTS.mkdir(exist_ok=True)
        threading.Thread(target=self._worker, daemon=True).start()

    # ---------- projects ----------
    def path(self, project_id: str) -> Path:
        if not project_id.isalnum():
            raise ValueError("bad project id")
        return PROJECTS / project_id

    def load(self, project_id: str) -> dict[str, Any]:
        project = json.loads((self.path(project_id) / "project.json").read_text(encoding="utf-8"))
        for shot in project["shots"]:  # projects from before takes existed
            if "takes" not in shot:
                shot["takes"] = {"keyframe": [{"name": shot["keyframe"]}] if shot.get("keyframe") else [],
                                 "video": [{"name": shot["video"], "keyframe": shot.get("keyframe")}]
                                 if shot.get("video") else []}
        return project

    def choose_take(self, project_id: str, shot_id: str, kind: str, name: str) -> dict[str, Any]:
        with self.lock:
            project = self.load(project_id)
            select_take(self._shot(project, shot_id), kind, name)
            project["film"] = None
            return self.save(project)

    def save(self, project: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            folder = self.path(project["id"])
            folder.mkdir(parents=True, exist_ok=True)
            temporary = folder / "project.json.tmp"
            temporary.write_text(json.dumps(project, indent=2), encoding="utf-8")
            temporary.replace(folder / "project.json")
        return project

    def list_projects(self) -> list[dict[str, Any]]:
        items = []
        for file in sorted(PROJECTS.glob("*/project.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            project = json.loads(file.read_text(encoding="utf-8"))
            cover = next((s["keyframe"] for s in project["shots"] if s.get("keyframe")), None)
            items.append({"id": project["id"], "title": project["title"], "shots": len(project["shots"]),
                          "cover": cover, "film": project.get("film")})
        return items

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        project = {"id": uuid.uuid4().hex[:10], "title": data.get("title") or "Untitled film",
                   "scene": data.get("scene", ""), "look": data.get("look", "Anamorphic blockbuster"),
                   "aspect": data.get("aspect", "16:9"), "continuity": data.get("continuity", ""),
                   "cast": data.get("cast", ""),
                   "reference": None, "film": None, "created": time.time(),
                   "shots": [new_shot(**s) for s in data.get("shots", [])] or [new_shot()]}
        return self.save(project)

    def update(self, project_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Apply edits from the UI; generated media stays owned by the server."""
        with self.lock:
            project = self.load(project_id)
            for key in ("title", "scene", "look", "aspect", "continuity", "cast", "finish", "motion", "idea",
                        "logline", "palette", "anchor"):
                if key in data:
                    project[key] = data[key]
            if "shots" in data:
                existing = {s["id"]: s for s in project["shots"]}
                shots = []
                for incoming in data["shots"]:
                    shot = existing.get(incoming.get("id")) or new_shot(takes={"keyframe": [], "video": []})
                    for key in ("action", "shot_size", "camera_move", "seconds", "sound", "transition", "seed",
                                "lead"):
                        if key in incoming:
                            shot[key] = incoming[key]
                    try:  # LTX shots are 2-10 s; anything else would blow the VRAM or render nothing
                        shot["seconds"] = min(10.0, max(2.0, float(shot["seconds"])))
                    except (TypeError, ValueError):
                        shot["seconds"] = 4.0
                    shots.append(shot)
                project["shots"] = shots
            return self.save(project)

    def set_reference(self, project_id: str, filename: str, data: bytes) -> dict[str, Any]:
        suffix = Path(filename).suffix.lower() if Path(filename).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} else ".png"
        with self.lock:
            project = self.load(project_id)
            target = self.path(project_id) / f"reference_{uuid.uuid4().hex[:6]}{suffix}"
            target.write_bytes(data)
            project["reference"] = target.name
            project.pop("reference_prompt", None)
            saved = self.save(project)
        self.enqueue("describe_lead", project_id, None, "Describing the lead's face")
        return saved

    def set_keyframe(self, project_id: str, shot_id: str, filename: str, data: bytes) -> dict[str, Any]:
        """Let the director bring their own start frame for a shot."""
        with self.lock:
            project = self.load(project_id)
            shot = self._shot(project, shot_id)
            target = self.path(project_id) / f"key_{shot_id}_{uuid.uuid4().hex[:6]}{Path(filename).suffix.lower() or '.png'}"
            target.write_bytes(data)
            add_take(shot, "keyframe", target.name, recipe={"kind": "upload", "lead": None, "anchor": None,
                                                            "steps": ["Your uploaded frame"]})
            return self.save(project)

    @staticmethod
    def _shot(project: dict[str, Any], shot_id: str) -> dict[str, Any]:
        for shot in project["shots"]:
            if shot["id"] == shot_id:
                return shot
        raise KeyError(f"shot {shot_id} not found")

    # ---------- jobs ----------
    def enqueue(self, kind: str, project_id: str, shot_id: str | None = None, label: str = "",
                **extra: Any) -> dict[str, Any]:
        job = {"id": uuid.uuid4().hex[:8], "kind": kind, "project": project_id, "shot": shot_id,
               "label": label or kind, "state": "queued", "error": None, "elapsed": 0.0, "created": time.time(),
               **extra}
        with self.lock:
            self.jobs.append(job)
            self.jobs = self.jobs[-200:]
        self.queue.put(job)
        return job

    def queue_film(self, project_id: str, redo_keyframes: bool = False) -> list[dict[str, Any]]:
        """Everything still missing, in dependency order.

        All keyframes run before any video so ComfyUI swaps the Qwen and LTX
        weights once instead of once per shot.
        """
        project = self.load(project_id)
        jobs = []
        if project.get("cast", "").strip() and not project.get("reference"):
            jobs.append(self.enqueue("cast", project_id, None, "Casting"))
        elif project.get("reference") and not lead_identity(project):
            jobs.append(self.enqueue("describe_lead", project_id, None, "Describing the lead's face"))
        anchor = anchor_of(project)
        order = sorted(enumerate(project["shots"]), key=lambda pair: pair[1] is not anchor)  # the anchor first
        for index, shot in order:
            continues = shot["transition"] == "continue" and index > 0
            if not continues and (redo_keyframes or not shot.get("keyframe")):
                jobs.append(self.enqueue("keyframe", project_id, shot["id"], f"Keyframe {index + 1}"))
        with self.lock:  # a keyframe still in the queue will replace this shot's start frame
            reframing = {j["shot"] for j in self.jobs if j["project"] == project_id and j["kind"] == "keyframe"
                         and j["state"] in ("queued", "running")}
        previous_redone = False
        for index, shot in enumerate(project["shots"]):
            continues = shot["transition"] == "continue" and index > 0
            # a one-take continuation starts on the previous shot's last frame, so it follows that shot
            redo = (redo_keyframes or not shot.get("video") or shot["id"] in reframing
                    or (continues and previous_redone))
            if redo:
                jobs.append(self.enqueue("video", project_id, shot["id"], f"Shot {index + 1}"))
            previous_redone = redo
        jobs.append(self.enqueue("stitch", project_id, None, "Final cut"))
        return jobs

    def cancel(self) -> None:
        with self.lock:
            for job in self.jobs:
                if job["state"] == "queued":
                    job["state"] = "cancelled"
        try:
            self.comfy.interrupt()
        except Exception:
            pass

    def list_jobs(self, project_id: str | None = None) -> list[dict[str, Any]]:
        with self.lock:
            return [dict(j) for j in self.jobs if project_id in (None, j["project"])]

    def _worker(self) -> None:
        while True:
            job = self.queue.get()
            if job["state"] == "cancelled":
                continue
            job["state"], started = "running", time.monotonic()
            try:
                tick = lambda elapsed: job.__setitem__("elapsed", elapsed)  # noqa: E731
                getattr(self, f"_run_{job['kind']}")(job, tick)
                job["state"] = "done"
            except Exception as error:  # surface every failure in the UI
                job["state"], job["error"] = "failed", str(error)
                traceback.print_exc()
                with self.lock:  # later steps of this film depend on this one
                    for later in self.jobs:
                        if later["project"] == job["project"] and later["state"] == "queued":
                            later["state"], later["error"] = "cancelled", "an earlier step failed"
            job["elapsed"] = time.monotonic() - started

    # ---------- pipeline steps ----------
    def _upload(self, project_id: str, filename: str) -> str:
        return self.comfy.upload(self.path(project_id) / filename, f"oc_{project_id}_{filename}")

    def _run_cast(self, job: dict[str, Any], tick) -> None:
        """Generate the lead's reference portrait from the cast description."""
        project = self.load(job["project"])
        prompt = director.cast_prompt(project["cast"], project["scene"], project["look"])
        graph = graphs.keyframe_graph(prompt, random.randrange(1, 2**31), project["aspect"],
                                      f"open-cinema/{project['id']}/cast", size=graphs.CAST_SIZE)
        files = self.comfy.run(graph, on_tick=tick)
        name = f"cast_{uuid.uuid4().hex[:6]}.png"
        self.comfy.download(files[0], self.path(project["id"]) / name)
        with self.lock:
            project = self.load(job["project"])
            project["reference"], project["reference_prompt"] = name, prompt
            self.save(project)
        job["label"] = "Casting · describing the face"
        self._describe_lead(job["project"], tick)

    def _describe_lead(self, project_id: str, tick) -> None:
        """Gemma 4 E4B looks at the portrait and writes the traits that make this face recognisable."""
        project = self.load(project_id)
        reference = project.get("reference")
        if not reference:
            return
        graph = graphs.lead_writer_graph("identity", project["title"], project["scene"], project["look"],
                                         photo=self._upload(project_id, reference), seed=7)
        record = self.comfy.wait(self.comfy.submit(graph), on_tick=tick, timeout=600)
        note = "".join(record["outputs"].get("lead", {}).get("text", [""])).strip().rstrip(".")
        with self.lock:
            fresh = self.load(project_id)
            if note and fresh.get("reference") == reference:
                fresh["lead_identity"], fresh["lead_identity_of"] = note, reference
                self.save(fresh)

    def _run_describe_lead(self, job: dict[str, Any], tick) -> None:
        self._describe_lead(job["project"], tick)

    def _run_keyframe(self, job: dict[str, Any], tick) -> None:
        project = self.load(job["project"])
        index = next(i for i, s in enumerate(project["shots"]) if s["id"] == job["shot"])
        shot = project["shots"][index]
        look, scene, aspect = project["look"], project["scene"], project["aspect"]
        continuity = project.get("continuity", "")
        prefix = f"open-cinema/{project['id']}/key_{shot['id']}"
        # Every other shot is built from ONE anchor frame (shot 1 unless pinned), never from the
        # latest shot, so small drifts don't compound from shot to shot.
        anchor_shot = anchor_of(project)
        anchor = anchor_shot.get("keyframe") if anchor_shot and anchor_shot["id"] != shot["id"] else None
        lead = shot.get("lead", True)
        reference = project.get("reference") if lead else None
        seed = take_seed(shot, "keyframe")
        recipe: dict[str, Any] = {"lead": reference, "anchor": None, "base": None}
        identity = False
        if anchor:
            # name the world as well as showing it, so a new camera setup never wanders off to another place
            prompt = director.coverage_prompt(shot["action"], shot["shot_size"], look, continuity,
                                              has_cast=bool(reference), camera_move=shot["camera_move"], lead=lead,
                                              world=scene.split(". ")[0].strip().rstrip("."),
                                              identity=lead_identity(project) if reference else "")
            graph = graphs.coverage_graph(prompt, seed, self._upload(project["id"], anchor), prefix, aspect,
                                          second_reference=self._upload(project["id"], reference) if reference else None)
            recipe.update(kind="coverage", anchor={"shot": anchor_shot["id"], "image": anchor},
                          steps=["Qwen-Image-Edit 2511 · new camera setup · 4 steps"])
        elif reference and not project.get("cast", "").strip():
            # Only a photo to go on: edit the person into the scene.
            prompt = director.cast_keyframe_prompt(scene, shot["action"], shot["shot_size"], look, continuity)
            graph = graphs.coverage_graph(prompt, seed, self._upload(project["id"], reference), prefix, aspect)
            recipe.update(kind="photo", steps=["Qwen-Image-Edit 2511 · lead placed in the world · 4 steps"])
        else:
            # Text-to-image gives the best establishing frame; the cast portrait takes over from shot 2.
            # A full description of the lead makes the model frame them large, so wide shots carry only
            # the continuity essentials (or the description's first sentence): enough to be the same person.
            cast = project.get("cast", "").strip()
            if shot["shot_size"] in director.WIDE_SIZES:
                cast = continuity.strip() or cast.split(". ")[0]
            cast = director._join(lead_identity(project) if reference else "", cast).rstrip(".")
            cast = cast and lead and "The lead: " + cast
            prompt = director.keyframe_prompt(director._join(scene, cast), shot["action"], shot["shot_size"], look,
                                              shot["camera_move"], lead)
            graph = graphs.keyframe_graph(prompt, seed, project["aspect"], prefix)
            identity = bool(reference)  # HiDream can't see the portrait: recast its person as the lead
            recipe.update(kind="establishing", steps=["HiDream-O1 · world frame · 40 steps"])
        files = self.comfy.run(graph, on_tick=tick)
        name = f"key_{shot['id']}_{uuid.uuid4().hex[:6]}.png"
        self.comfy.download(files[0], self.path(project["id"]) / name)
        if identity:
            job["label"] = f"Keyframe {index + 1} · casting the lead"
            base, name = name, f"key_{shot['id']}_{uuid.uuid4().hex[:6]}.png"
            identity_prompt = director.identity_prompt(continuity, lead_identity(project))
            files = self.comfy.run(graphs.identity_graph(
                identity_prompt, seed, self._upload(project["id"], base), self._upload(project["id"], reference),
                prefix, aspect), on_tick=tick)
            self.comfy.download(files[0], self.path(project["id"]) / name)
            recipe.update(base=base, identity_prompt=identity_prompt, identity=lead_identity(project),
                          steps=recipe["steps"] + ["Qwen-Image-Edit 2511 · identity pass · 4 steps"])
        with self.lock:
            project = self.load(job["project"])
            current = self._shot(project, shot["id"])
            add_take(current, "keyframe", name, prompt=prompt, seed=seed, recipe=recipe)
            project["film"] = None
            self.save(project)

    def _last_frame(self, project_id: str, video: str) -> str:
        name = f"{Path(video).stem}_last.png"
        subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-sseof", "-0.1", "-i",
                        str(self.path(project_id) / video), "-frames:v", "1", "-update", "1",
                        str(self.path(project_id) / name)], check=True)
        return name

    def _path_guide(self, project_id: str, start: str, guide: tuple[float, float, float, float]) -> str:
        """End frame for a forward camera move: the start frame zoomed in toward the move's target."""
        zoom, cx, cy, _ = guide
        name = f"{Path(start).stem}_path{zoom:g}.png"
        crop = (f"crop=iw/{zoom}:ih/{zoom}:(iw-iw/{zoom})*{cx}:(ih-ih/{zoom})*{cy},"
                f"scale=iw*{zoom}:ih*{zoom}:flags=lanczos")
        subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-i", str(self.path(project_id) / start),
                        "-vf", crop, "-frames:v", "1", "-update", "1", str(self.path(project_id) / name)], check=True)
        return name

    def _run_video(self, job: dict[str, Any], tick) -> None:
        project = self.load(job["project"])
        index = next(i for i, s in enumerate(project["shots"]) if s["id"] == job["shot"])
        shot = project["shots"][index]
        if shot["transition"] == "continue" and index > 0:
            previous = project["shots"][index - 1]
            if not previous.get("video"):
                raise RuntimeError(f"Shot {index + 1} continues shot {index}, which has no video yet")
            start = self._last_frame(project["id"], previous["video"])
            with self.lock:
                fresh = self.load(project["id"])
                add_take(self._shot(fresh, shot["id"]), "keyframe", start,
                         recipe={"kind": "continue", "lead": None, "anchor": None, "from": previous["id"],
                                 "steps": [f"Last frame of shot {index}"]})
                self.save(fresh)
        else:
            start = shot.get("keyframe")
            if not start:
                raise RuntimeError(f"Shot {index + 1} has no keyframe yet")
        prompt = director.motion_prompt(shot["action"], shot["camera_move"], shot.get("sound", ""), project["look"],
                                        director._join(project.get("cast", ""), lead_identity(project)).rstrip("."),
                                        shot["shot_size"], project.get("continuity", ""),
                                        shot.get("lead", True))
        seed = take_seed(shot, "video")
        guide = director.CAMERA_PATHS.get(shot["camera_move"])
        end, end_strength = (self._path_guide(project["id"], start, guide), guide[3]) if guide else (None, 1.0)
        graph = graphs.shot_graph(self._upload(project["id"], start), prompt, seed, project["aspect"],
                                  float(shot["seconds"]), f"open-cinema/{project['id']}/shot_{shot['id']}",
                                  end_image=end and self._upload(project["id"], end), end_strength=end_strength)
        files = self.comfy.run(graph, on_tick=tick)
        name = f"shot_{shot['id']}_{uuid.uuid4().hex[:6]}.mp4"
        self.comfy.download(files[0], self.path(project["id"]) / name)
        with self.lock:
            project = self.load(job["project"])
            current = self._shot(project, shot["id"])
            add_take(current, "video", name, prompt=prompt, seed=seed, keyframe=start)
            project["film"] = None
            self.save(project)

    def _run_master(self, job: dict[str, Any], tick) -> None:
        """1080p master: SeedVR2 each shot (a whole film doesn't fit in RAM), then cut them like the film."""
        project = self.load(job["project"])
        if not project.get("film"):
            raise RuntimeError("Cut the film before mastering it")
        folder = self.path(project["id"])
        mastered = []
        _, _, width, height = graphs.ASPECTS[project["aspect"]]
        size = f"{width * 3 // 2}x{height * 3 // 2}"
        for index, shot in enumerate(project["shots"]):
            cached = shot.get("master") or {}
            if (cached.get("of") == shot["video"] and cached.get("size") == size
                    and (folder / cached["name"]).is_file()):
                mastered.append(folder / cached["name"])
                continue
            job["label"] = f"1080p master · shot {index + 1}/{len(project['shots'])}"
            uploaded = self.comfy.upload(folder / shot["video"], f"oc_{project['id']}_{shot['video']}")
            files = self.comfy.run(graphs.master_graph(uploaded, f"open-cinema/{project['id']}/master_{shot['id']}",
                                                      project["aspect"]),
                                   on_tick=tick, timeout=3600)
            name = f"{Path(shot['video']).stem}_1080.mp4"
            self.comfy.download(files[0], folder / name)
            with self.lock:
                fresh = self.load(project["id"])
                self._shot(fresh, shot["id"])["master"] = {"of": shot["video"], "name": name, "size": size}
                self.save(fresh)
            mastered.append(folder / name)
        title_master = None
        if self._title_clip(project):
            job["label"] = "1080p master · in-world title"
            title_master = self._master_clip(project, project["title_shot"], size, tick)
        job["label"] = "1080p master · titles & motion"
        name = f"master_{uuid.uuid4().hex[:6]}.mp4"
        self._assemble(project, mastered, name, width * 3 // 2, height * 3 // 2, job, tick, crf="18", preset="slow",
                       title_clip=title_master)
        with self.lock:
            project = self.load(job["project"])
            project["master"], project["master_of"] = name, project.get("film")
            self.save(project)

    def _run_stitch(self, job: dict[str, Any], tick) -> None:
        project = self.load(job["project"])
        videos = [s.get("video") for s in project["shots"]]
        if not videos or not all(videos):
            raise RuntimeError("Every shot needs a rendered video before the final cut")
        folder = self.path(project["id"])
        name = f"film_{uuid.uuid4().hex[:6]}.mp4"
        _, _, width, height = graphs.ASPECTS[project["aspect"]]
        self._assemble(project, [folder / v for v in videos], name, width, height, job, tick,
                       title_clip=self._title_clip(project))
        with self.lock:
            project = self.load(job["project"])
            project["film"] = name
            self.save(project)

    # ---------- titles & motion ----------
    def _motion_clip(self, project: dict[str, Any], key: list[Any], graph_for, tick,
                     source: Path | None = None) -> Path:
        """Render a motion graph once per distinct input; the file name is a hash of everything it depends on."""
        key = [MOTION_VERSION, *key]  # bump when the renderer changes so cached clips re-render
        target = self.path(project["id"]) / f"motion_{hashlib.sha1(json.dumps(key).encode()).hexdigest()[:12]}.mp4"
        if target.is_file():
            return target
        uploaded = self.comfy.upload(source, f"oc_{project['id']}_{source.name}") if source else ""
        files = self.comfy.run(graph_for(uploaded), on_tick=tick, timeout=1800)
        self.comfy.download(files[0], target)
        return target

    def _dress(self, project: dict[str, Any], clips: list[Path], job: dict[str, Any], tick) -> list[Path]:
        """Main title on the opening shot, HUD stamps on the rest — each only if switched on."""
        settings, look, prefix = motion_settings(project), project["look"], f"open-cinema/{project['id']}/motion"
        dressed = []
        for index, (shot, clip) in enumerate(zip(project["shots"], clips)):
            if index == 0 and settings["title"]["on"] and settings["title"]["style"] != "inworld":
                node_class = "OpenCinemaTitleOverlay"
                params = {"title": project["title"], "subtitle": settings["title"]["subtitle"], "look": look,
                          "start": 0.5, "hold": max(1.0, min(3.2, duration(clip) - 0.9)),
                          "palette": palette_string(project)}
            elif settings["stamps"]["on"]:  # shot 1 too, unless the kinetic title is over it
                move = shot["camera_move"].upper()
                node_class = "OpenCinemaShotStamp"
                params = {"text": f"SHOT {index + 1:02d} · {shot['shot_size'].upper()} · {move}",
                          "highlight": move, "look": look, "palette": palette_string(project)}
            else:
                dressed.append(clip)
                continue
            job["label"] = f"{job['label'].split(' · ')[0]} · titles shot {index + 1}"
            dressed.append(self._motion_clip(
                project, [clip.name, node_class, params],
                lambda uploaded, c=node_class, p=params: graphs.motion_overlay_graph(uploaded, prefix, c, **p),
                tick, clip))
        return dressed

    def _cards(self, project: dict[str, Any], lines: str, width: int, height: int, per_card: float, tick,
               seed: int = 5) -> Path:
        palette = palette_string(project)
        key = ["cards", lines, project["look"], width, height, per_card, seed, palette]
        return self._motion_clip(project, key, lambda _: graphs.cards_graph(
            lines, project["look"], width, height, f"open-cinema/{project['id']}/cards", per_card, 24.0, seed,
            palette), tick)

    def _credits(self, project: dict[str, Any], last_clip: Path, width: int, height: int, tick) -> Path | None:
        """End credits, scored with the film's own sound: the last shot's audio echoing out."""
        settings = motion_settings(project)
        if not settings["credits"]["on"]:
            return None
        lines = settings["credits"]["lines"].strip() or default_credits(project)
        silent = self._cards(project, lines, width, height, 1.5, tick, seed=9)
        target = silent.with_name(silent.stem + f"_scored_{last_clip.stem[-6:]}.mp4")
        if not target.is_file():
            length, tail = duration(silent), max(0.0, duration(last_clip) - 2.5)
            subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-i", str(silent), "-ss", f"{tail:.3f}",
                            "-i", str(last_clip), "-filter_complex",
                            f"[1:a]aresample=48000,aecho=0.8:0.6:180|380:0.45|0.25,apad,atrim=0:{length:.3f},"
                            f"afade=t=in:d=0.05,afade=t=out:st={max(0, length - 1.4):.3f}:d=1.4[a]",
                            "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                            str(target)], check=True)
        return target

    def _assemble(self, project: dict[str, Any], clips: list[Path], name: str, width: int, height: int,
                  job: dict[str, Any], tick, crf: str = "17", preset: str = "medium",
                  title_clip: Path | None = None) -> None:
        """The cut: dressed shots, transitions, credits, finish, loudness — one ffmpeg pass."""
        dressed = self._dress(project, clips, job, tick)
        transitions = [s["transition"] for s in project["shots"]]
        if title_clip:  # the in-world title opens the film and dissolves into the first shot
            dressed, transitions = [title_clip] + dressed, ["cut", "dissolve"] + transitions[1:]
        credits = self._credits(project, clips[-1], width, height, tick)
        if credits:
            dressed, transitions = dressed + [credits], transitions + ["cut"]
        inputs, graph = cut_filter(dressed, transitions, bool(project.get("finish")))
        subprocess.run([ffmpeg(), "-y", "-loglevel", "error", *inputs, "-filter_complex", graph,
                        "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", crf, "-preset", preset,
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                        str(self.path(project["id"]) / name)], check=True)

    # ---------- in-world title ----------
    def _title_clip(self, project: dict[str, Any]) -> Path | None:
        settings, shot = motion_settings(project), project.get("title_shot") or {}
        if settings["title"]["on"] and settings["title"]["style"] == "inworld" and shot.get("video"):
            return self.path(project["id"]) / shot["video"]
        return None

    def _master_clip(self, project: dict[str, Any], unit: dict[str, Any], size: str, tick) -> Path:
        """SeedVR2 one clip (a shot or the title shot), cached per take and output size."""
        folder, cached = self.path(project["id"]), unit.get("master") or {}
        if cached.get("of") == unit["video"] and cached.get("size") == size and (folder / cached["name"]).is_file():
            return folder / cached["name"]
        uploaded = self.comfy.upload(folder / unit["video"], f"oc_{project['id']}_{unit['video']}")
        files = self.comfy.run(graphs.master_graph(uploaded, f"open-cinema/{project['id']}/master_title",
                                                   project["aspect"]), on_tick=tick, timeout=3600)
        name = f"{Path(unit['video']).stem}_1080.mp4"
        self.comfy.download(files[0], folder / name)
        with self.lock:
            fresh = self.load(project["id"])
            fresh.setdefault("title_shot", {})["master"] = {"of": unit["video"], "name": name, "size": size}
            self.save(fresh)
        return folder / name

    def title_material(self, project: dict[str, Any]) -> str:
        return (motion_settings(project)["title"]["material"].strip()
                or director.TITLE_MATERIALS.get(project["look"], director.TITLE_MATERIALS["None"]))

    def queue_title_shot(self, project_id: str, frame: bool = True) -> list[dict[str, Any]]:
        jobs = [self.enqueue("title_frame", project_id, None, "In-world title · frame")] if frame else []
        return jobs + [self.enqueue("title_video", project_id, None, "In-world title · motion")]

    def choose_title_take(self, project_id: str, kind: str, name: str) -> dict[str, Any]:
        with self.lock:
            project = self.load(project_id)
            select_take(project.setdefault("title_shot", {}), kind, name)
            project["film"] = None
            return self.save(project)

    def _run_title_frame(self, job: dict[str, Any], tick) -> None:
        project = self.load(job["project"])
        source = project["shots"][0].get("keyframe")
        if not source:
            raise RuntimeError("Shot 1 needs a keyframe before the in-world title can be made")
        unit = project.get("title_shot") or {"seed": random.randrange(1, 2**31)}
        unit.setdefault("seed", random.randrange(1, 2**31))
        seed, material = take_seed(unit, "keyframe"), self.title_material(project)
        prompt = director.title_frame_prompt(project["title"], material)
        files = self.comfy.run(graphs.title_frame_graph(prompt, seed, self._upload(project["id"], source),
                                                        f"open-cinema/{project['id']}/title_frame",
                                                        project["title"], project["look"]), on_tick=tick)
        name = f"title_{uuid.uuid4().hex[:6]}.png"
        self.comfy.download(files[0], self.path(project["id"]) / name)
        with self.lock:
            project = self.load(job["project"])
            unit = project.setdefault("title_shot", {})
            unit.setdefault("seed", seed)
            add_take(unit, "keyframe", name, prompt=prompt, seed=seed)
            project["film"] = None
            self.save(project)

    def _run_title_video(self, job: dict[str, Any], tick) -> None:
        project = self.load(job["project"])
        unit = project.get("title_shot") or {}
        if not unit.get("keyframe"):
            raise RuntimeError("Make the in-world title frame first")
        start, material = unit["keyframe"], self.title_material(project)
        prompt = director.title_motion_prompt(project["title"], material, project["shots"][0].get("sound", ""))
        seed = take_seed(unit, "video")
        guide = director.CAMERA_PATHS["Push in (slow)"]
        end = self._path_guide(project["id"], start, guide)
        graph = graphs.shot_graph(self._upload(project["id"], start), prompt, seed, project["aspect"], 4.0,
                                  f"open-cinema/{project['id']}/title_shot", end_image=self._upload(project["id"], end),
                                  end_strength=0.85)
        files = self.comfy.run(graph, on_tick=tick)
        name = f"title_shot_{uuid.uuid4().hex[:6]}.mp4"
        self.comfy.download(files[0], self.path(project["id"]) / name)
        with self.lock:
            project = self.load(job["project"])
            add_take(project.setdefault("title_shot", {}), "video", name, prompt=prompt, seed=seed, keyframe=start)
            project["film"] = None
            self.save(project)

    def _score(self, project: dict[str, Any], seconds: float, tick, reroll: bool = False) -> Path:
        """The trailer's soundtrack: one continuous LTX render whose audio is the score (cached per take)."""
        folder, unit = self.path(project["id"]), project.get("trailer_score") or {}
        if unit.get("name") and not reroll and unit.get("seconds") == seconds and (folder / unit["name"]).is_file():
            return folder / unit["name"]
        # Start from the film's dark title card, not a scene: with no weather or crowd in frame, LTX scores music
        # instead of ambience.
        card = self.comfy.run(graphs.title_preview_graph(project["title"], project["look"],
                                                         f"open-cinema/{project['id']}/score_card",
                                                         palette=palette_string(project)), on_tick=tick)
        start = f"score_card_{uuid.uuid4().hex[:6]}.png"
        self.comfy.download(card[0], folder / start)
        seed = (project["shots"][0]["seed"] + 7919 * (unit.get("takes", 0) + (1 if reroll else 0))) % 2**31
        files = self.comfy.run(graphs.score_graph(self._upload(project["id"], start),
                                                  director.score_prompt(project["look"], project["title"]), seed,
                                                  seconds, f"open-cinema/{project['id']}/score"), on_tick=tick)
        name = f"score_{uuid.uuid4().hex[:6]}.mp4"
        self.comfy.download(files[0], folder / name)
        with self.lock:
            fresh = self.load(project["id"])
            takes = (fresh.get("trailer_score") or {}).get("takes", 0) + 1
            fresh["trailer_score"] = {"name": name, "seconds": seconds, "seed": seed, "takes": takes}
            self.save(fresh)
        return folder / name

    def _run_trailer(self, job: dict[str, Any], tick) -> None:
        """Trailer cut: type cards between shots over one continuous LTX score, every cut landing on a hit."""
        project = self.load(job["project"])
        if not all(s.get("video") for s in project["shots"]):
            raise RuntimeError("Every shot needs a rendered video before cutting a trailer")
        folder, settings = self.path(project["id"]), motion_settings(project)
        _, _, width, height = graphs.ASPECTS[project["aspect"]]
        lines = [l.strip() for l in (settings["trailer"]["lines"] or default_trailer(project)).splitlines() if l.strip()]
        if lines and lines[-1].lower() == project["title"].strip().lower():
            lines.pop()  # the title card closes the trailer anyway
        card_len, clip_len, title_len = 0.9, 1.5, 2.6
        count = len(project["shots"])
        plan: list[tuple[str, int, float, int]] = []  # (kind, index, length, repeat)
        for k in range(max(count, len(lines))):  # every card gets a beat; shots come round again if needed
            if k < len(lines):
                plan.append(("card", k, card_len, 0))
            plan.append(("shot", k % count, clip_len, k // count))
        total = sum(entry[2] for entry in plan) + title_len
        job["label"] = "Trailer · composing the score"
        score = self._score(project, round(total + 1.5), tick, reroll=bool(job.get("reroll")))
        hits = onsets(score)
        # lay the cut onto the score: each boundary snaps to the nearest hit around its planned time
        bounds, t = [], 0.0
        for _, _, length, _ in plan:
            t = snap(t + length, hits, t + length * 0.6, t + length * 1.5)
            bounds.append(t)
        end = min(duration(score) - 0.1, max(bounds[-1] + title_len, snap(bounds[-1] + title_len, hits,
                                                                         bounds[-1] + 1.6, bounds[-1] + 3.4)))
        job["label"] = "Trailer · cutting to the score"
        cards = self._cards(project, "\n".join(lines), width, height, card_len, tick, seed=21) if lines else None
        title = self._cards(project, project["title"], width, height, max(title_len, end - bounds[-1]), tick, seed=33)
        shots = [folder / s["video"] for s in project["shots"]]
        inputs = [arg for p in shots for arg in ("-i", str(p))]
        c_in = len(shots)
        if cards:
            inputs += ["-i", str(cards)]
        t_in = c_in + (1 if cards else 0)
        inputs += ["-i", str(title), "-i", str(score)]
        s_in = t_in + 1
        norm = "fps=24,format=yuv420p,settb=AVTB,setpts=PTS-STARTPTS"
        parts, labels, previous = [], [], 0.0
        for (kind, k, _, repeat), bound in zip(plan, bounds):
            length = bound - previous
            if kind == "card":
                parts.append(f"[{c_in}:v]trim=start={k * card_len:.3f}:duration={card_len},tpad=stop_mode=clone:"
                             f"stop_duration=2,trim=duration={length:.3f},{norm}[p{len(labels)}]")
            else:  # the middle of the shot, where its motion is; a repeat shows another moment of it
                start = max(0.0, (duration(shots[k]) - length) * (0.5, 0.12, 0.88, 0.3, 0.7)[repeat % 5])
                parts.append(f"[{k}:v]trim=start={start:.3f}:duration={length:.3f},{norm}[p{len(labels)}]")
            labels.append(f"[p{len(labels)}]")
            previous = bound
        parts.append(f"[{t_in}:v]trim=duration={end - previous:.3f},{norm}[p{len(labels)}]")
        labels.append(f"[p{len(labels)}]")
        finish = FILM_FINISH if project.get("finish") else "null"
        parts.append(f"{''.join(labels)}concat=n={len(labels)}:v=1:a=0,{finish}[v]")
        parts.append(f"[{s_in}:a]aresample=48000,atrim=0:{end:.3f},asetpts=PTS-STARTPTS,"
                     f"afade=t=out:st={max(0.0, end - 0.6):.3f}:d=0.6,loudnorm=I=-14:TP=-1.0:LRA=9,aresample=48000[a]")
        name = f"trailer_{uuid.uuid4().hex[:6]}.mp4"
        subprocess.run([ffmpeg(), "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(parts),
                        "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "17", "-preset", "medium",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                        str(folder / name)], check=True)
        with self.lock:
            project = self.load(job["project"])
            project["trailer"] = name
            self.save(project)

    # ---------- AI lead writer ----------
    def _run_write_lead(self, job: dict[str, Any], tick) -> None:
        """Gemma 4 E4B writes (or refines, or describes from the casting photo) the lead and continuity notes."""
        project = self.load(job["project"])
        mode = job.get("mode", "write")
        draft = project.get("cast", "")
        photo = None
        if mode == "from photo":
            if not project.get("reference"):
                raise RuntimeError("Add a cast photo first")
            photo = self._upload(project["id"], project["reference"])
        if mode == "continuity" and not draft.strip():
            mode = "write"  # nothing to distil yet: write the lead and its continuity together
        graph = graphs.lead_writer_graph(mode, project["title"], project["scene"], project["look"], draft, photo,
                                         seed=random.randrange(1, 2**31))
        record = self.comfy.wait(self.comfy.submit(graph), on_tick=tick, timeout=600)
        read = lambda key: "".join(record["outputs"].get(key, {}).get("text", [""])).strip()
        lead, continuity = read("lead"), read("continuity")
        if mode == "continuity" and not continuity:  # a bare list without its "CONTINUITY:" prefix
            continuity, lead = lead, ""
        if not lead and not continuity:
            raise RuntimeError("The writer returned nothing; try again")
        with self.lock:
            fresh = self.load(job["project"])
            self._remember_story(fresh, ("continuity",) if mode == "continuity" else ("cast", "continuity"))
            if mode != "continuity" and lead:
                fresh["cast"] = lead
            if continuity:
                fresh["continuity"] = continuity
            self.save(fresh)

    def _remember_story(self, project: dict[str, Any], keys: tuple[str, ...] = STORY_FIELDS) -> None:
        """Snapshot the fields an AI change is about to touch, so undo never reverts the user's own later edits."""
        snapshot = {k: copy.deepcopy(project.get(k)) for k in keys}
        project["story_history"] = (project.get("story_history") or [])[-14:] + [snapshot]

    def undo_story(self, project_id: str) -> dict[str, Any]:
        with self.lock:
            project = self.load(project_id)
            if project.get("story_history"):
                previous = project["story_history"].pop()
                for key, value in previous.items():
                    project[key] = value
            return self.save(project)

    def _run_write_story(self, job: dict[str, Any], tick) -> None:
        """Gemma 4 E4B writes the whole story page, or one field of it, consistent with the rest."""
        project = self.load(job["project"])
        target = job.get("target", "everything")
        graph = graphs.story_writer_graph(target, project.get("idea", ""), project["title"], project.get("logline", ""),
                                          project["scene"], project["look"] if target != "everything" else "",
                                          project.get("cast", "") if target != "everything" else "",
                                          seed=random.randrange(1, 2**31))
        record = self.comfy.wait(self.comfy.submit(graph), on_tick=tick, timeout=900)
        out = {k: "".join(record["outputs"].get(k, {}).get("text", [""])).strip()
               for k in ("title", "logline", "world", "look", "palette", "lead", "continuity", "trailer")}
        wanted = {"everything": ("title", "logline", "world", "look", "palette", "lead", "continuity"),
                  "title": ("title",), "logline": ("logline",), "world": ("world",),
                  "look": ("look", "palette"), "trailer": ("trailer",)}[target]
        if not any(out[k] for k in wanted):
            raise RuntimeError("The writer returned nothing usable; try again")
        with self.lock:
            fresh = self.load(job["project"])
            field = {"world": "scene", "lead": "cast", "trailer": "motion"}
            self._remember_story(fresh, tuple(field.get(k, k) for k in wanted) + (("palette",) if target == "look" else ()))
            for key in wanted:
                value = out[key]
                if not value:
                    continue
                if key == "palette":
                    bg, ink, accent, glow = value.split(",")
                    fresh["palette"] = {"bg": bg, "ink": ink, "accent": accent, "glow": glow}
                elif key == "look":
                    fresh["look"] = value
                elif key == "trailer":
                    motion = fresh.setdefault("motion", {}) or {}
                    motion.setdefault("trailer", {})["lines"] = value
                    fresh["motion"] = motion
                else:
                    fresh[field.get(key, key)] = value
            if target == "look" and not out["palette"]:
                fresh.pop("palette", None)  # a new look without colours of its own uses the look's palette
            self.save(fresh)
            recast = target == "everything" and out["lead"] and (not fresh.get("reference") or fresh.get("reference_prompt"))
        if recast:  # the page is complete only with the lead's face; never replaces an uploaded photo
            self.enqueue("cast", job["project"], None, "Casting the new lead")

    def _run_motion_preview(self, job: dict[str, Any], tick) -> None:
        project = self.load(job["project"])
        files = self.comfy.run(graphs.title_preview_graph(project["title"], project["look"],
                                                          f"open-cinema/{project['id']}/preview",
                                                          palette=palette_string(project)), on_tick=tick)
        name = f"motion_preview_{uuid.uuid4().hex[:6]}.png"
        self.comfy.download(files[0], self.path(project["id"]) / name)
        with self.lock:
            project = self.load(job["project"])
            project["motion_preview"] = name
            self.save(project)
