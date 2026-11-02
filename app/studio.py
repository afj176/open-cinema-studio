"""Open Cinema Studio pipeline: projects, shot lists and the GPU job queue."""

from __future__ import annotations

import array
import copy
import hashlib
import itertools
import json
import queue
import random
import re
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
from events import Events  # noqa: E402

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


STORY_FIELDS = ("title", "logline", "scene", "look", "palette", "cast", "continuity", "characters", "beats")


def repeated_title_words(projects: list[dict[str, Any]]) -> str:
    """Identify recurring distinctive title words, keeping generic glue words out of the prompt."""
    from collections import Counter
    stop = {"the", "and", "for", "with", "from", "into", "under", "over", "untitled", "film"}
    counts = Counter()
    eligible = [p for p in projects if not (p.get("title") or "").lower().startswith(("scratch", "test", "continue test"))]
    for project in eligible[:30]:
        words = set()
        for word in re.findall(r"[a-z]{4,}", (project.get("title") or "").lower()):
            if word in stop:
                continue
            stem = word[:-2] if word.endswith("oes") else word[:-1] if word.endswith("s") and not word.endswith("ss") else word
            words.add(stem)
        counts.update(words)
    return ", ".join(word for word, count in counts.most_common(8) if count >= 2)
# Text jobs jump ahead of queued renders, then the lead, world and storyboard; renders keep their order.
PRIORITY = {"write_shots": 0, "write_story": 0, "write_lead": 0, "cast": 1, "describe_lead": 1, "world": 1,
            "sketch": 1, "plan_continuity": 0}
SIDE_JOBS = {"write_shots", "write_story", "write_lead", "sketch", "motion_preview", "review", "plan_continuity"}


def default_credits(project: dict[str, Any]) -> str:
    return "\n".join([project["title"],
                      "Made with open models | HiDream-O1 · Qwen-Image-Edit · LTX 2.5 · SeedVR2 · Gemma 4",
                      "Made in | Open Cinema Studio"])


def film_inputs(project: dict[str, Any]) -> dict[str, Any]:
    """Everything the final cut is made from. The cut keeps a copy, so the Edit page can say what changed since."""
    settings = motion_settings(project)
    return {"shots": [[s["id"], s.get("video"), s.get("transition", "cut")] for s in project["shots"]],
            "titles": {k: settings[k] for k in ("title", "stamps", "credits")},
            "title": project["title"], "look": project["look"], "palette": palette_string(project),
            "title_shot": (project.get("title_shot") or {}).get("video"), "finish": bool(project.get("finish"))}


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
    note = project.get("lead_identity", "") if project.get("lead_identity_of") == project.get("reference") else ""
    return note if usable_identity(note) else ""


def usable_identity(note: str) -> bool:
    """Reject model commentary or refusals instead of treating them as visual traits."""
    text = (note or "").strip()
    commentary = r"\b(?:the (?:request|prompt|image) (?:asks|provided|is)|i (?:cannot|can't|must|am unable)|as an ai|i apologize|i'm sorry|i am sorry)\b"
    traits = r"\b(?:face|skin|eyes?|eyebrows?|nose|lips?|hair|beard|freckles|complexion)\b"
    return bool(text and not re.search(commentary, text, re.I) and re.search(traits, text, re.I))


def cast_stale(project: dict[str, Any]) -> bool:
    """Generated portraits follow their description and medium; uploaded portraits are always kept."""
    prompt = project.get("reference_prompt")
    return bool(prompt and prompt != director.cast_prompt(project.get("cast", ""), project.get("scene", ""), project.get("look", "")))


def world_of(project: dict[str, Any]) -> dict[str, Any]:
    """What the world plate depends on: if any of it changes, the plate is out of date."""
    return {"scene": project.get("scene", ""), "look": project.get("look", ""), "aspect": project.get("aspect", "")}


def world_plate(project: dict[str, Any]) -> str | None:
    return (project.get("world") or {}).get("plate")


def cast_list(project: dict[str, Any]) -> dict[str, str]:
    """The other characters, from the Story page's 'Name: what they look like' lines."""
    people = {}
    for raw in (project.get("characters") or "").splitlines():
        name, _, look = raw.partition(":")
        if name.strip() and look.strip():
            people[name.strip()] = look.strip()
    return people


def others_in(project: dict[str, Any], shot: dict[str, Any]) -> str:
    """Everyone in the shot besides the lead, with each named character's description, so a character looks the
    same in every shot they're in (a speaker is in the shot even if the writer forgot to list them)."""
    people = cast_list(project)
    names = [t.strip() for t in (shot.get("others") or "").replace(";", ",").split(",") if t.strip()]
    staging = " ".join(shot.get(k, "") or "" for k in ("action", "start_frame", "end_state"))
    for name in people:
        if re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", staging, re.I) and not any(name.lower() == n.lower() for n in names):
            names.append(name)
    speaker = (shot.get("line") or "").partition(":")[0].strip() if ":" in (shot.get("line") or "") else ""
    lead_name = director.lead_name(project.get("cast", "")).lower()
    names = [name for name in names if name.lower() != lead_name]
    if speaker and speaker.lower() not in {"lead", "the lead", lead_name} and not any(speaker.lower() == n.lower() for n in names):
        names.append(speaker)
    described = []
    for name in names:
        match = next((k for k in people if k.lower() == name.lower() or name.lower().startswith(k.lower() + " ")), None)
        described.append(f"{match} ({people[match]})" if match else name)
    return "; ".join(described)


def is_blank(shot: dict[str, Any]) -> bool:
    return not shot.get("action", "").strip() and not is_made(shot)


def is_made(shot: dict[str, Any]) -> bool:
    return bool(shot.get("keyframe") or shot.get("video") or (shot.get("takes") or {}).get("keyframe"))


def beat_text(project: dict[str, Any], shot: dict[str, Any]) -> str:
    beat = shot.get("beat")
    beats = project.get("beats") or []
    return beats[beat - 1] if isinstance(beat, int) and 0 < beat <= len(beats) else ""


def story_stale(project: dict[str, Any], shot: dict[str, Any]) -> bool:
    return "beat_source" in shot and shot["beat_source"] != beat_text(project, shot)


def continuity_inputs(project: dict) -> dict:
    return {**{k: project.get(k, "") for k in ("scene", "look", "cast", "characters", "continuity", "beats")},
            "shots": [{k: s.get(k, "") for k in ("id", "beat", "action", "start_frame", "end_state", "lead", "others", "line", "transition")}
                      for s in project["shots"]]}


def plan_status(project: dict) -> str:
    plan = project.get("continuity_plan")
    if not plan:
        return "missing"
    if plan.get("of") != continuity_inputs(project):
        return "stale"
    if plan.get("issues") and not plan.get("acknowledged"):
        return "issues"
    return "ready"


def continuity_auto_fixes(project: dict) -> list[dict]:
    """Identify obsolete missing-fact warnings without inventing any scene state."""
    plan = project.get("continuity_plan") or {}
    if plan.get("of") != continuity_inputs(project):
        return []  # do not act on a warning from an earlier script
    shots = project.get("shots", [])
    fixes = []
    for issue in plan.get("issues", []):
        match = re.fullmatch(r"Shot (\d+) introduces '([^']+)' which is not defined in initial state facts\.", issue)
        if not match or not 1 <= int(match.group(1)) <= len(shots):
            continue
        fact = match.group(2)
        # If anything still depends on the fact, a missing initial value is a real
        # editorial decision and this action must not erase the warning.
        referenced = any(fact in (shot.get("state_changes") or {}) or
                         fact in (shot.get("start_checks") or []) or
                         fact in (shot.get("end_checks") or []) for shot in shots)
        if fact not in (project.get("scene_state") or {}) and not referenced:
            fixes.append({"issue": issue, "fact": fact,
                          "description": f"Remove obsolete warning: no shot tracks '{fact}'."})
    return fixes


def shot_states(project: dict, shot: dict) -> tuple[dict, dict]:
    state = dict(project.get("scene_state") or {})
    for item in project["shots"]:
        before = dict(state)
        state.update(item.get("state_changes") or {})
        if item["id"] == shot["id"]:
            return before, state
    raise KeyError("Shot absent from state ledger")


def state_design(project: dict) -> str:
    return (project.get("continuity_plan") or {}).get("design", project.get("continuity", ""))


def review_requirements(project: dict, shot: dict, phase: str) -> dict:
    before, after = shot_states(project, shot)
    start_names, end_names = shot.get("start_cast"), shot.get("end_cast")
    names = start_names if phase == "start" else end_names
    if phase == "middle":
        keys = [k for k in shot.get("start_checks", []) if k in shot.get("end_checks", []) and before.get(k) == after.get(k)]
        names = list(dict.fromkeys((start_names or []) + (end_names or [])))
        allowed = list(range(min(len(start_names), len(end_names)), max(len(start_names), len(end_names)) + 1)) \
            if start_names is not None and end_names is not None else None
    else:
        keys = shot.get(phase + "_checks", [])
        allowed = [len(names)] if names is not None else None
    state = before if phase != "end" else after
    people = {director.lead_name(project.get("cast", "")) or "Lead": project.get("cast", ""), **cast_list(project)}
    if names is not None:
        visible = {n.casefold() for n in names}
        lead_aliases = {"lead", "the lead", director.lead_name(project.get("cast", "")).casefold()}
        people = {k:v for k,v in people.items() if k.casefold() in visible or k == next(iter(people)) and visible & lead_aliases}
    facts = {k: state[k] for k in keys if k in state}
    prop = next((p for p in project.get("props", []) if p["id"] == shot.get("prop_id")), None)
    if prop and (prop.get("state_key") in keys or phase == "middle" and
                 prop.get("state_key") in shot.get("start_checks", []) and prop.get("state_key") in shot.get("end_checks", [])):
        facts["Design of " + prop["name"]] = prop["description"]
    return {"state": facts, "count": len(names) if names is not None else None,
            "allowed_counts": allowed, "visible_names": names,
            "people": people}


def review_passed(take: dict | None) -> bool:
    review = (take or {}).get("review") or {}
    return review.get("version") == director.REVIEW_VERSION and review.get("status") == "passed"


def current_take(shot: dict, kind: str) -> dict:
    return next((t for t in (shot.get("takes") or {}).get(kind, []) if t["name"] == shot.get(kind)), {})


def starting_cast(project: dict, shot: dict) -> tuple[bool, str]:
    names = shot.get("start_cast")
    if names is None:
        return shot.get("lead", True), others_in(project, shot)
    lead_name = director.lead_name(project.get("cast", "")).casefold()
    lead = any(n.casefold() in {"lead", "the lead", lead_name} for n in names)
    people = {k.casefold(): (k, v) for k, v in cast_list(project).items()}
    others = []
    for name in names:
        if name.casefold() in {"lead", "the lead", lead_name}:
            continue
        key, description = people.get(name.casefold(), (name, ""))
        others.append(f"{key} ({description})" if description else key)
    return lead, "; ".join(others)


def prop_input(project: dict, shot: dict, phase: str = "start") -> dict:
    """One explicit hero prop per setup; unrelated offscreen objects never enter the references."""
    prop = next((p for p in project.get("props", []) if p["id"] == shot.get("prop_id")), None)
    if not prop:
        return {}
    state = shot_states(project, shot)[phase == "end"].get(prop.get("state_key"), "")
    variant = prop.get("variants", {}).get(state, {})
    return {"id": prop["id"], "name": prop["name"], "description": prop["description"], "state": state,
            "image": variant.get("name") if variant.get("of") == prop_design(project, prop) else None}


def prop_design(project: dict, prop: dict) -> dict:
    return {"description": prop["description"], "look": project["look"]}


def visual_inputs(project: dict[str, Any], shot: dict[str, Any]) -> dict[str, Any]:
    anchor = {}
    if shot.get("frame_source") == "previous_end":
        index = next(i for i,s in enumerate(project["shots"]) if s["id"] == shot["id"])
        previous = project["shots"][index-1] if index else {}
        anchor = {"previous_end": previous.get("video")}
    return {"version": 4, "action": shot.get("action", ""), "start_frame": shot.get("start_frame", ""),
            **anchor,
            "shot_size": shot.get("shot_size"), "camera_move": shot.get("camera_move"),
            "lead": shot.get("lead", True), "others": others_in(project, shot),
            "cast": project.get("cast", "") if shot.get("lead", True) else "",
            "continuity": project.get("continuity", ""), "design": state_design(project),
            "prop": prop_input(project, shot), "image_quality": project.get("image_quality", "fast"),
            "state_before": shot_states(project, shot)[0], "start_cast": shot.get("start_cast"),
            "start_checks": shot.get("start_checks", []), **world_of(project)}


def video_inputs(project: dict[str, Any], shot: dict[str, Any]) -> dict[str, Any]:
    index = next((i for i, s in enumerate(project["shots"]) if s["id"] == shot["id"]), 0)
    previous_video = project["shots"][index - 1].get("video") if index and shot.get("transition") == "continue" else None
    return {**visual_inputs(project, shot), "end_state": shot.get("end_state", ""), "state_after": shot_states(project, shot)[1],
            **({"end_frame": (shot.get("endframe") or {}).get("name")} if shot.get("guide_end") else {}),
            "end_cast": shot.get("end_cast"), "end_checks": shot.get("end_checks", []),
            "seconds": shot.get("seconds"), "sound": shot.get("sound", ""), "line": shot.get("line", ""),
            "transition": shot.get("transition", "cut"), "keyframe": shot.get("keyframe"), "previous_video": previous_video,
            "guide_end": shot.get("guide_end", False), "end_prop": prop_input(project, shot, "end")}


def ending_inputs(project: dict, shot: dict) -> dict:
    inputs = {**video_inputs(project, shot), "start": shot.get("keyframe")}
    inputs.pop("end_frame", None)
    return inputs


def video_stale(project: dict[str, Any], shot: dict[str, Any]) -> bool:
    take = next((t for t in (shot.get("takes") or {}).get("video", []) if t["name"] == shot.get("video")), {})
    return bool(shot.get("video") and (take.get("of") != video_inputs(project, shot)))


def asset_status(project: dict[str, Any]) -> dict[str, Any]:
    return {s["id"]: {"story": story_stale(project, s), "frame": frame_stale(project, s),
                      "video": video_stale(project, s), "sketch": sketch_stale(project, s),
                      "review": bool(s.get("video") and not review_passed(current_take(s, "video"))),
                      "state_before": shot_states(project, s)[0], "state_after": shot_states(project, s)[1]} for s in project["shots"]}


def sketch_stale(project: dict[str, Any], shot: dict[str, Any]) -> bool:
    take = next((t for t in shot.get("sketches", []) if t["name"] == shot.get("sketch")), {})
    return bool(shot.get("sketch") and ((take.get("of") or {}).get("visual") != visual_inputs(project, shot)
                or take.get("source_frame") and take["source_frame"] != shot.get("keyframe")))


def sketch_of(shot: dict[str, Any], plate: str | None, reference: str | None,
              project: dict[str, Any] | None = None) -> dict[str, Any]:
    """What a storyboard drawing depends on: if any of it changes, the drawing is redrawn before the next frame."""
    return {"action": shot.get("action", ""), "shot_size": shot.get("shot_size"), "camera_move": shot.get("camera_move"),
            "lead": shot.get("lead", True) is not False,
            "others": shot.get("others", ""), "visual": visual_inputs(project, shot) if project else None}


def frame_stale(project: dict[str, Any], shot: dict[str, Any]) -> bool:
    """The shot's frame no longer matches it (mirrors staleness() in the web app): a new lead, world, action or
    framing. Frames from before a field was recorded aren't flagged for it."""
    take = next((t for t in (shot.get("takes") or {}).get("keyframe", []) if t["name"] == shot.get("keyframe")), None)
    r = (take or {}).get("recipe") or {}
    if not shot.get("keyframe") or r.get("kind") != "shot":
        return False
    drawing = next((t for t in shot.get("sketches", []) if t["name"] == shot.get("sketch")), {})
    traced_current = drawing.get("source_frame") == shot.get("keyframe")
    if r.get("composition_version") != 2 or r.get("visual") != visual_inputs(project, shot) or (
            r.get("sketch") != shot.get("sketch") and not traced_current):
        return True
    lead = shot.get("lead", True) is not False and project.get("reference")
    return bool((lead and r.get("lead") != project.get("reference")) or r.get("world") != current_plate(project)
                or ("action" in r and r["action"] != shot.get("action", ""))
                or ("shot_size" in r and (r["shot_size"] != shot.get("shot_size")
                                          or r.get("camera_move") != shot.get("camera_move"))))


def current_plate(project: dict[str, Any]) -> str | None:
    """The world plate, but only if it was painted from today's world, look and aspect."""
    unit = project.get("world") or {}
    take = next((t for t in unit.get("takes", []) if t["name"] == unit.get("plate")), None)
    return unit.get("plate") if take and take.get("of") == world_of(project) else None


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
    if match.get("review", {}).get("status") == "needs_review":
        raise RuntimeError("This candidate failed visual review. Inspect its findings and regenerate it before using it.")
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


def cut_filter(videos: list[Path], transitions: list[str], finish: bool = False,
               size: tuple[int, int] | None = None) -> tuple[list[str], str]:
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
        scale = f"scale={size[0]}:{size[1]}:flags=lanczos," if size else ""
        if mode == "continue":
            parts.append(f"[{i}:v]trim=start_frame=1,setpts=PTS-STARTPTS,{scale}fps=24,format=yuv420p,settb=AVTB[v{i}]")
            length -= 1 / 24
        else:
            parts.append(f"[{i}:v]{scale}fps=24,format=yuv420p,settb=AVTB,setpts=PTS-STARTPTS[v{i}]")
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
        self.events = Events()
        self.comfy.on_event = self._comfy_event
        self.lock = threading.RLock()
        self.jobs_path = PROJECTS.parent / "runtime" / "studio-jobs.json"
        try:
            self.jobs = json.loads(self.jobs_path.read_text(encoding="utf-8"))[-200:]
        except (OSError, ValueError, TypeError):
            self.jobs = []
        for job in self.jobs:
            if job.get("state") in ("running", "queued"):
                job.update(state="interrupted", error="Studio restarted. Resume missing work when ready.")
        self.queue: queue.PriorityQueue[tuple[int, int, dict[str, Any]]] = queue.PriorityQueue()
        self.order = itertools.count()
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
            shot.setdefault("beat_source", beat_text(project, shot))
            if "takes" not in shot:
                shot["takes"] = {"keyframe": [{"name": shot["keyframe"]}] if shot.get("keyframe") else [],
                                 "video": [{"name": shot["video"], "keyframe": shot.get("keyframe")}]
                                 if shot.get("video") else []}
        project["asset_status"] = asset_status(project)
        project["continuity_status"] = plan_status(project)
        project["continuity_fixes"] = continuity_auto_fixes(project)
        return project

    def choose_take(self, project_id: str, shot_id: str, kind: str, name: str) -> dict[str, Any]:
        with self.lock:
            project = self.load(project_id)
            select_take(self._shot(project, shot_id), kind, name)
            return self.save(project)

    def save(self, project: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            folder = self.path(project["id"])
            folder.mkdir(parents=True, exist_ok=True)
            temporary = folder / "project.json.tmp"
            project.pop("film_now", None)  # computed for the web app, never stored
            project.pop("asset_status", None)
            project.pop("continuity_status", None)
            project.pop("continuity_fixes", None)
            temporary.write_text(json.dumps(project, indent=2), encoding="utf-8")
            temporary.replace(folder / "project.json")
        return {**project, "film_now": film_inputs(project), "asset_status": asset_status(project), "continuity_status": plan_status(project),
                "continuity_fixes": continuity_auto_fixes(project)}

    def list_projects(self) -> list[dict[str, Any]]:
        items = []
        for file in sorted(PROJECTS.glob("*/project.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            project = json.loads(file.read_text(encoding="utf-8"))
            cover = next((s["keyframe"] for s in project["shots"] if s.get("keyframe")), None)
            items.append({"id": project["id"], "title": project["title"], "shots": len(project["shots"]),
                          "cover": cover, "film": project.get("film")})
        return items

    def delete(self, project_id: str) -> list[dict[str, Any]]:
        """Delete a film and everything made for it, and drop its queued jobs."""
        with self.lock:
            folder = self.path(project_id)
            if not folder.exists():
                raise KeyError(f"film {project_id} not found")
            if any(j["project"] == project_id and j["state"] == "running" for j in self.jobs):
                raise RuntimeError("This film is rendering; cancel the queue or wait for it to finish first")
            for job in self.jobs:
                if job["project"] == project_id and job["state"] == "queued":
                    job["state"], job["error"] = "cancelled", "the film was deleted"
            shutil.rmtree(folder)
        return self.list_projects()

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        project = {"id": uuid.uuid4().hex[:10], "title": data.get("title") or "Untitled film",
                   "scene": data.get("scene", ""), "look": data.get("look", "Anamorphic blockbuster"),
                   "aspect": data.get("aspect", "16:9"), "continuity": data.get("continuity", ""),
                   "ai_mode": data.get("ai_mode", "normal") if data.get("ai_mode", "normal") in ("normal", "fast") else "normal",
                   "cast": data.get("cast", ""),
                   "reference": None, "film": None, "created": time.time(),
                   "shots": [new_shot(**s) for s in data.get("shots", [])] or [new_shot()]}
        return self.save(project)

    def update(self, project_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Apply edits from the UI; generated media stays owned by the server."""
        if "ai_mode" in data and data["ai_mode"] not in ("normal", "fast"):
            raise ValueError("Choose Normal or Fast AI mode")
        with self.lock:
            project = self.load(project_id)
            current_revision = data.get("continuity_rev", 0) == project.get("continuity_rev", 0)
            if "scene_state" in data and current_revision:
                project["scene_state"] = director.state_map(data["scene_state"])
            if "state_design" in data and current_revision and project.get("continuity_plan"):
                project["continuity_plan"]["design"] = str(data["state_design"])
            if isinstance(data.get("beats"), list):
                project["beats"] = [str(b).strip() for b in data["beats"] if str(b).strip()]
            if "props" in data:
                existing_props = {p["id"]: p for p in project.get("props", [])}
                props = []
                for incoming in data["props"][:20]:
                    prop = existing_props.get(incoming.get("id"), {"id": uuid.uuid4().hex[:8], "variants": {}})
                    for field in ("name", "description", "state_key"):
                        prop[field] = str(incoming.get(field, "")).strip()
                    if prop["state_key"] not in project.get("scene_state", {}):
                        raise ValueError("A prop must follow a fact in scene continuity")
                    props.append(prop)
                project["props"] = props
            for key in ("title", "scene", "look", "aspect", "continuity", "cast", "finish", "motion", "idea",
                        "logline", "palette", "auto_render", "characters", "image_quality", "ai_mode"):
                if key in data:
                    project[key] = data[key]
            if "shots" in data:
                existing = {s["id"]: s for s in project["shots"]}
                shots = []
                for incoming in data["shots"]:
                    shot = existing.get(incoming.get("id")) or new_shot(takes={"keyframe": [], "video": []})
                    for key in ("action", "shot_size", "camera_move", "seconds", "sound", "transition", "seed",
                                "lead", "beat", "ai", "others", "line", "start_frame", "end_state", "prop_id", "guide_end", "frame_source"):
                        if key in incoming:
                            shot[key] = incoming[key]
                    if incoming.get("accept_beat"):
                        shot["beat_source"] = beat_text(project, shot)
                    if "state_changes" in incoming and current_revision:
                        changes = director.state_map(incoming["state_changes"])
                        if changes.keys() - (project.get("scene_state") or {}).keys():
                            raise ValueError("State changes must use a fact from the initial scene state")
                        shot["state_changes"] = changes
                    if current_revision:
                        for field in ("start_checks", "end_checks"):
                            if field in incoming:
                                keys = incoming[field]
                                if not isinstance(keys, list) or any(not isinstance(k, str) or k not in project.get("scene_state", {}) for k in keys):
                                    raise ValueError("Review checks must refer to initial scene facts")
                                shot[field] = list(dict.fromkeys(keys))
                        for field in ("start_cast", "end_cast"):
                            if field in incoming:
                                names = incoming[field]
                                if names is not None and (not isinstance(names, list) or len(names) > 50 or
                                        any(not isinstance(n, str) or not n.strip() for n in names)):
                                    raise ValueError("Visible cast must be a list of names, or null for a crowd")
                                shot[field] = names
                    try:  # LTX shots are 2-10 s; anything else would blow the VRAM or render nothing
                        shot["seconds"] = min(10.0, max(2.0, float(shot["seconds"])))
                    except (TypeError, ValueError):
                        shot["seconds"] = 4.0
                    shots.append(shot)
                project["shots"] = shots
            if data.get("accept_continuity") and current_revision and project.get("continuity_plan"):
                project["continuity_plan"].update(of=continuity_inputs(project), acknowledged=True)
            # No GPU work on each autosave. The next explicit render resolves the dependencies below.
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
            review = {"version": director.REVIEW_VERSION, "status": "needs_review",
                      "findings": ["Inspect the uploaded opening frame before using it"], "of": visual_inputs(project, shot)}
            add_take(shot, "keyframe", target.name, recipe={"kind": "upload", "lead": None, "anchor": None,
                                                            "steps": ["Your uploaded frame"]}, review=review)
            shot.setdefault("quality", {})["keyframe"] = {"name": target.name, **review}
            return self.save(project)

    def set_endframe(self, project_id: str, shot_id: str, filename: str, data: bytes) -> dict:
        with self.lock:
            project = self.load(project_id)
            shot = self._shot(project, shot_id)
            if not shot.get("keyframe"):
                raise ValueError("Choose an opening frame before adding an ending frame")
            suffix = Path(filename).suffix.lower()
            if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
                raise ValueError("Upload an image file")
            shot["guide_end"] = True
            name = f"end_upload_{shot_id}_{uuid.uuid4().hex[:6]}{suffix}"
            (self.path(project_id) / name).write_bytes(data)
            snapshot = ending_inputs(project, shot)
            review = {"version":director.REVIEW_VERSION, "status":"needs_review", "findings":["Inspect the uploaded ending frame before using it"], "of":snapshot}
            shot.setdefault("endframes", []).append({"name":name, "of":snapshot, "review":review, "source":"upload"})
            shot.setdefault("quality", {})["endframe"] = {"name":name, **review}
            return self.save(project)

    @staticmethod
    def _shot(project: dict[str, Any], shot_id: str) -> dict[str, Any]:
        for shot in project["shots"]:
            if shot["id"] == shot_id:
                return shot
        raise KeyError(f"shot {shot_id} not found")

    # ---------- jobs ----------
    def _comfy_event(self, message):
        data = message.get("data", {})
        prompt = data.get("prompt_id")
        with self.lock:
            if message.get("type") == "studio_submitted":
                for running in self.jobs:
                    if running["state"] == "running":
                        running["prompt_id"] = prompt
                        running.pop("progress", None)
                        running.pop("node", None)
            job = next((j for j in self.jobs if j.get("prompt_id") == prompt and j["state"] == "running"), None)
            if job:
                if message.get("type") == "progress":
                    job["progress"] = {"value": data.get("value"), "max": data.get("max")}
                if message.get("type") == "executing":
                    job["node"] = data.get("node")
        self.events.publish()

    def _save_jobs(self):
        if hasattr(self, "events"):
            self.events.publish()
        if not hasattr(self, "jobs_path"):
            return
        with self.lock:
            self.jobs_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.jobs_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.jobs[-200:], indent=2), encoding="utf-8")
            temporary.replace(self.jobs_path)

    def retry_job(self, job_id: str) -> dict:
        with self.lock:
            old = next((j for j in self.jobs if j["id"] == job_id), None)
            if not old or old["state"] not in ("failed", "needs_review", "blocked", "interrupted", "cancelled"):
                raise ValueError("This step is not waiting for a retry")
            extra = {k: old[k] for k in ("mode", "target", "count", "redraw", "prop", "value", "candidate_kind",
                     "render_after", "draw_after", "redo_keyframe", "reroll") if k in old}
            return self.enqueue(old["kind"], old["project"], old.get("shot"), old.get("base_label", old["label"]), **extra)

    def auto_fix_continuity(self, job_id: str, expected_revision: int) -> dict:
        """Remove provably obsolete continuity warnings, then resume only a ready plan."""
        with self.lock:
            job = next((j for j in self.jobs if j["id"] == job_id), None)
            if not job or job["kind"] != "plan_continuity" or job["state"] != "needs_review":
                raise ValueError("This continuity step is no longer waiting for a fix")
            if any(j["project"] == job["project"] and j["kind"] == "plan_continuity" and
                   j["state"] in ("queued", "running") for j in self.jobs):
                raise ValueError("Continuity planning is already running")
            project = self.load(job["project"])
            if project.get("continuity_rev", 0) != expected_revision:
                raise ValueError("The continuity plan changed. Review it and try again.")
            fixes = continuity_auto_fixes(project)
            if not fixes:
                raise ValueError("No safe automatic fix is available. Review the scene state before continuing.")
            fixed = {item["issue"] for item in fixes}
            project["continuity_plan"]["issues"] = [issue for issue in project["continuity_plan"]["issues"] if issue not in fixed]
            project["continuity_plan"]["acknowledged"] = False
            project["continuity_rev"] = project.get("continuity_rev", 0) + 1
            project.pop("continuity_error", None)
            unresolved_values = [key for key, value in (project.get("scene_state") or {}).items()
                                 if value == "Unknown before first change"]
            for key in unresolved_values:
                if not any(key in issue for issue in project["continuity_plan"]["issues"]):
                    project["continuity_plan"]["issues"].append(f"Set the unknown initial value of '{key}' before rendering.")
            saved = self.save(project)
            ready = plan_status(saved) == "ready" and not unresolved_values
            job.setdefault("auto_fixes", []).extend(fixes)
            if saved["continuity_plan"]["issues"]:
                job["error"] = "Continuity needs review: " + "; ".join(saved["continuity_plan"]["issues"])
            self._save_jobs()
        queued, warning = [], ("Set the unknown initial values for " + ", ".join(unresolved_values) +
                               " in Scene continuity before resuming." if unresolved_values else None)
        if ready:
            try:
                if job.get("render_after"):
                    queued = self.queue_film(job["project"])
                elif job.get("draw_after"):
                    queued = self.queue_sketches(job["project"])
            except Exception as error:
                warning = str(error)
        return {"project": saved, "fixed": fixes, "remaining": saved["continuity_plan"]["issues"],
                "resumed": bool(queued), "warning": warning}

    def _block_dependents(self, failed: dict):
        """Only block the failed shot's downstream work, linked performances, and final assembly."""
        shot_id, kind = failed.get("shot"), failed["kind"]
        affected = {shot_id} if shot_id else set()
        if shot_id:
            previous_affected = False
            try:
                shots = self.load(failed["project"])["shots"]
            except FileNotFoundError:
                shots = []  # deleting a film must not terminate the worker
            for shot in shots:
                if shot["id"] in affected or previous_affected and (shot.get("transition") == "continue" or shot.get("frame_source") == "previous_end"):
                    affected.add(shot["id"])
                    previous_affected = True
                else:
                    previous_affected = False
        rank = {"sketch": 0, "keyframe": 1, "repair_frame": 1, "video": 2, "review": 3}
        for later in self.jobs:
            if later["project"] != failed["project"] or later["state"] != "queued":
                continue
            assembly = later["kind"] in ("stitch", "master", "trailer")
            dependent = later.get("shot") in affected and (later.get("shot") != shot_id or
                         rank.get(later["kind"], -1) > rank.get(kind, 99))
            shared = not shot_id and kind in ("cast", "world", "plan_continuity") and later["kind"] in ("keyframe", "video", "review", "repair_frame")
            if dependent or shared or assembly and (affected or kind in ("cast", "world", "plan_continuity")):
                later.update(state="blocked", blocked_by=failed["id"],
                             error=f"Waiting for {failed.get('base_label', failed['label'])}. Independent shots can continue.")

    def enqueue(self, kind: str, project_id: str, shot_id: str | None = None, label: str = "",
                **extra: Any) -> dict[str, Any]:
        mode = self.load(project_id).get("ai_mode", "normal")
        if hasattr(self, "setup"):
            self.setup.require(kind, extra.get("target"), mode=mode)
        job = {"id": uuid.uuid4().hex[:8], "kind": kind, "project": project_id, "shot": shot_id,
               "label": label or kind, "state": "queued", "error": None, "elapsed": 0.0, "created": time.time(),
               **extra, "ai_mode": mode, "base_label": label or kind}
        with self.lock:
            existing = next((j for j in self.jobs if j["project"] == project_id and j.get("shot") == shot_id and
                             j["kind"] == kind and j["state"] in ("queued", "running") and
                             all(j.get(k) == extra.get(k) for k in ("mode", "target", "prop", "value"))), None)
            if existing:
                return existing
            self.jobs.append(job)
            self.jobs = self.jobs[-200:]
            self._save_jobs()
        self.queue.put((PRIORITY.get(kind, 2), next(self.order), job))
        return job

    def queue_film(self, project_id: str, redo_keyframes: bool = False,
                   only: set[str] | None = None) -> list[dict[str, Any]]:
        """Everything missing or out of date, in dependency order (`only`: just these shots).

        All keyframes run before any video so ComfyUI swaps the Qwen and LTX
        weights once instead of once per shot. Paused shots are skipped, a step
        already waiting in the queue isn't queued again, and the film is cut only
        when every shot will have a video.
        """
        if hasattr(self, "setup"):
            self.setup.require("film", mode=self.load(project_id).get("ai_mode", "normal"))
        project = self.load(project_id)
        outdated = [str(i + 1) for i, s in enumerate(project["shots"]) if story_stale(project, s)
                    and not s.get("paused") and (only is None or s["id"] in only)]
        if outdated:
            raise RuntimeError("Story beats changed for shots " + ", ".join(outdated) +
                               ". Rewrite those shots or confirm 'Still tells this beat' before rendering.")
        status = plan_status(project)
        if status == "missing":
            pending = next((j for j in self.jobs if j["project"] == project_id and j["kind"] == "plan_continuity"
                            and j["state"] in ("queued", "running")), None)
            if pending:
                pending["render_after"] = True
                return [pending]
            return [self.enqueue("plan_continuity", project_id, label="Planning continuity", render_after=True)]
        if status != "ready":
            raise RuntimeError("Review scene continuity on Story: replan it, or confirm your edited states before rendering.")
        with self.lock:
            waiting = {(j["kind"], j["shot"]) for j in self.jobs if j["project"] == project_id
                       and j["state"] in ("queued", "running")}
        held = set()  # paused shots, and one-take shots that start from one
        for index, shot in enumerate(project["shots"]):
            if shot.get("paused") or (shot["transition"] == "continue" and index > 0
                                      and project["shots"][index - 1]["id"] in held):
                held.add(shot["id"])
        wanted = lambda shot: shot["id"] not in held and (only is None or shot["id"] in only)  # noqa: E731
        jobs = []
        if project.get("cast", "").strip() and (not project.get("reference") or cast_stale(project)) and ("cast", None) not in waiting:
            jobs.append(self.enqueue("cast", project_id, None, "Casting"))
        elif project.get("reference") and not lead_identity(project) and ("describe_lead", None) not in waiting:
            jobs.append(self.enqueue("describe_lead", project_id, None, "Describing the lead's face"))
        if not current_plate(project) and ("world", None) not in waiting:
            jobs.append(self.enqueue("world", project_id, None, "Painting the world", auto=True))
        jobs.extend(self.queue_sketches(project_id, [s["id"] for s in project["shots"] if wanted(s)]))
        if any(s.get("frame_source") == "previous_end" for s in project["shots"]):
            # A later frame needs the preceding completed performance. Preserve dependency order
            # instead of batching all image work ahead of all animation.
            upstream_changed = False
            for index, shot in enumerate(project["shots"]):
                redo = wanted(shot) and (redo_keyframes or not shot.get("video") or video_stale(project, shot)
                       or frame_stale(project, shot) or upstream_changed and shot.get("frame_source") == "previous_end")
                if redo and ("video", shot["id"]) not in waiting:
                    jobs.append(self.enqueue("video", project_id, shot["id"], f"Shot {index+1}", redo_keyframe=redo_keyframes))
                elif wanted(shot) and shot.get("video") and not review_passed(current_take(shot, "video")) and ("review",shot["id"]) not in waiting:
                    jobs.append(self.enqueue("review",project_id,shot["id"],f"Review shot {index+1}"))
                upstream_changed = redo
            coming = {j["shot"] for j in self.jobs if j["project"] == project_id and j["kind"] == "video" and j["state"] in ("queued","running")}
            if not held and all(s.get("video") or s["id"] in coming for s in project["shots"]) and ("stitch",None) not in waiting:
                jobs.append(self.enqueue("stitch",project_id,None,"Final cut"))
            return jobs
        for index, shot in enumerate(project["shots"]):
            continues = shot["transition"] == "continue" and index > 0
            if not continues and wanted(shot) and ("keyframe", shot["id"]) not in waiting and \
                    (redo_keyframes or not shot.get("keyframe") or frame_stale(project, shot)):
                jobs.append(self.enqueue("keyframe", project_id, shot["id"], f"Keyframe {index + 1}"))
        with self.lock:  # a keyframe still in the queue will replace this shot's start frame
            reframing = {j["shot"] for j in self.jobs if j["project"] == project_id and j["kind"] == "keyframe"
                         and j["state"] in ("queued", "running")}
        previous_redone = False
        for index, shot in enumerate(project["shots"]):
            continues = shot["transition"] == "continue" and index > 0
            # a one-take continuation starts on the previous shot's last frame, so it follows that shot
            redo = wanted(shot) and (redo_keyframes or not shot.get("video") or video_stale(project, shot) or shot["id"] in reframing
                                     or (continues and previous_redone))
            if redo and ("video", shot["id"]) not in waiting:
                jobs.append(self.enqueue("video", project_id, shot["id"], f"Shot {index + 1}"))
            elif wanted(shot) and shot.get("video") and not review_passed(current_take(shot, "video")) and ("review", shot["id"]) not in waiting:
                jobs.append(self.enqueue("review", project_id, shot["id"], f"Review shot {index + 1}"))
            previous_redone = redo
        with self.lock:
            coming = {j["shot"] for j in self.jobs if j["project"] == project_id and j["kind"] == "video"
                      and j["state"] in ("queued", "running")}
        if not held and all(s.get("video") or s["id"] in coming for s in project["shots"]) and \
                ("stitch", None) not in waiting:
            jobs.append(self.enqueue("stitch", project_id, None, "Final cut"))
        return jobs

    def pause_shot(self, project_id: str, shot_id: str, paused: bool) -> dict[str, Any]:
        """Pause: drop the shot's waiting work and stop it if it's running. Resume: render it again from
        whatever is now missing or out of date (drawing, frame, video), then cut the film if it's complete."""
        with self.lock:
            project = self.load(project_id)
            shot = self._shot(project, shot_id)
            shot["paused"] = paused
            saved = self.save(project)
            running = None
            if paused:
                for job in self.jobs:
                    if job["project"] == project_id and job["shot"] == shot_id and job["state"] == "queued":
                        job["state"], job["error"] = "cancelled", "paused"
                    elif job["project"] == project_id and job["shot"] == shot_id and job["state"] == "running":
                        running = job
                        job["stopped"] = True
                    elif job["project"] == project_id and job["kind"] == "stitch" and job["state"] == "queued":
                        job["state"], job["error"] = "cancelled", "a shot is paused"  # resuming cuts it again
        if running:
            try:
                self.comfy.interrupt()
            except Exception:
                pass
        if not paused:
            self.queue_sketches(project_id, [shot_id])
            self.queue_film(project_id, only={shot_id})
        return saved

    def cancel(self, project_id: str) -> None:
        running = False
        with self.lock:
            for job in self.jobs:
                if job["project"] != project_id:
                    continue
                if job["state"] == "queued":
                    job["state"] = "cancelled"
                    job["error"] = "Stopped by you"
                elif job["state"] == "running":
                    job["stopped"] = True
                    running = True
            self._save_jobs()
            if running:
                try:
                    self.comfy.interrupt()
                except Exception:
                    pass

    def list_jobs(self, project_id: str | None = None) -> list[dict[str, Any]]:
        with self.lock:
            return [dict(j) for j in self.jobs if project_id in (None, j["project"])]

    def _worker(self) -> None:
        while True:
            job = self.queue.get()[2]
            with self.lock:
                if job["state"] != "queued":
                    continue
                job["state"], started = "running", time.monotonic()
                now = time.time()
                job["timing"] = {"queue_seconds": max(0.0, now - job.get("created", now))}
                timing = getattr(getattr(self, "comfy", None), "_timing", None)
                if timing is not None:
                    timing.metrics = job["timing"]
            try:
                tick = lambda elapsed: job.__setitem__("elapsed", time.monotonic() - started)  # noqa: E731
                self._save_jobs()
                with graphs.using_writer(job.get("ai_mode", "normal")):
                    getattr(self, f"_run_{job['kind']}")(job, tick)
                job["state"] = "done"
            except Exception as error:  # surface every failure in the UI
                if job.get("stopped"):  # its shot was paused while it ran
                    job["state"], job["error"] = "cancelled", "Stopped by you"
                    job["elapsed"] = time.monotonic() - started
                    self._save_jobs()
                    if timing is not None:
                        timing.metrics = None
                    continue
                job["state"], job["error"] = ("needs_review" if "needs review" in str(error).lower() else "failed"), str(error)
                traceback.print_exc()
                with self.lock:
                    self._block_dependents(job)
            job["elapsed"] = time.monotonic() - started
            if timing is not None:
                timing.metrics = None
            self._save_jobs()

    # ---------- pipeline steps ----------
    def _upload(self, project_id: str, filename: str) -> str:
        return self.comfy.upload(self.path(project_id) / filename, f"oc_{project_id}_{filename}")

    def _render_checked(self, graph: dict[str, Any], seed: int, tick) -> tuple[list, int, dict]:
        """One explicit attempt, always retaining a candidate and its review for the director."""
        record = self.comfy.wait(self.comfy.submit(graph), on_tick=tick)
        files = [item for output in record.get("outputs", {}).values() for item in output.get("images", [])
                 if item.get("type") == "output"]
        if not files:
            raise RuntimeError("Generation finished without saving an image")
        text = "".join(record.get("outputs", {}).get("cast_review", {}).get("text", []))
        if "cast_review" in graph or text:
            try:
                review = json.loads(text)
                if not isinstance(review, dict) or review.get("status") not in ("passed", "needs_review"):
                    raise ValueError("Invalid cast review")
            except (ValueError, TypeError):
                review = {"version": director.REVIEW_VERSION, "status": "needs_review",
                          "findings": ["The cast check returned no usable evidence. Inspect this candidate or redraw it."]}
        else:
            review = {"version": director.REVIEW_VERSION, "status": "passed", "findings": []}
        return files, seed, review

    def _text_graph(self, graph: dict, output: str, tick) -> dict:
        record = self.comfy.wait(self.comfy.submit(graph), on_tick=tick, timeout=900)
        text = "".join(record.get("outputs", {}).get(output, {}).get("text", []))
        return json.loads(text)

    def _run_plan_continuity(self, job: dict, tick) -> None:
        project = self.load(job["project"])
        if any(not s.get("action", "").strip() for s in project["shots"]):
            raise RuntimeError("Write the shots before planning continuity")
        source = continuity_inputs(project)
        try:
            plan = self._text_graph(graphs.continuity_graph(json.dumps(source), len(project["shots"])), "plan", tick)
        except Exception as error:
            with self.lock:
                fresh = self.load(project["id"])
                fresh["continuity_error"] = str(error)
                self.save(fresh)
            raise
        with self.lock:
            fresh = self.load(project["id"])
            if continuity_inputs(fresh) != source or fresh.get("scene_state") != project.get("scene_state") or \
                    [s.get("state_changes") for s in fresh["shots"]] != [s.get("state_changes") for s in project["shots"]]:
                raise RuntimeError("The script or scene states changed during planning. Your edits were kept; replan.")
            fresh["scene_state"] = plan["initial"]
            fresh.pop("continuity_error", None)
            fresh["continuity_plan"] = {"of": source, "design": plan["design"], "issues": plan["issues"], "acknowledged": False}
            fresh["continuity_rev"] = fresh.get("continuity_rev", 0) + 1
            for shot, row in zip(fresh["shots"], plan["shots"]):
                shot["state_changes"] = row["changes"]
                for key in ("start_checks", "end_checks", "start_cast", "end_cast"):
                    shot[key] = row[key]
            self.save(fresh)
        if plan["issues"]:
            raise RuntimeError("Continuity needs review: " + "; ".join(plan["issues"]))
        if job.get("render_after"):
            self.queue_film(project["id"])
        elif job.get("draw_after"):
            self.queue_sketches(project["id"])

    def _require_plan(self, project_id: str, tick) -> dict:
        project = self.load(project_id)
        if plan_status(project) == "missing":
            self._run_plan_continuity({"project": project_id}, tick)
            project = self.load(project_id)
        if plan_status(project) != "ready":
            raise RuntimeError("Review scene continuity on Story before generating media")
        return project

    def _review_image(self, project: dict, shot: dict, name: str, tick, phase="start") -> dict:
        review = self._text_graph(graphs.visual_review_graph(self._upload(project["id"], name),
                                  json.dumps(review_requirements(project, shot, phase)),
                                  director.look_for_state(project["look"], review_requirements(project, shot, phase)["state"])), "review", tick)
        review["of"] = visual_inputs(project, shot)
        return review

    def _review_video(self, project: dict, shot: dict, name: str, tick) -> dict:
        contracts = [json.dumps(review_requirements(project, shot, phase)) for phase in ("start", "middle", "end")]
        review = self._text_graph(graphs.video_review_graph(self._upload(project["id"], name), *contracts,
                                 director.look_for_state(project["look"], review_requirements(project, shot, "start")["state"])), "review", tick)
        review["of"] = video_inputs(project, shot)
        review["sample_positions"] = [0, 1/3, 2/3, 1]
        return review

    def _record_candidate(self, project_id: str, shot_id: str, kind: str, name: str, review: dict, **info) -> None:
        """Keep rejected work inspectable, but never promote it over an accepted take."""
        with self.lock:
            fresh = self.load(project_id)
            current = self._shot(fresh, shot_id)
            current.setdefault("quality", {})[kind] = {"name": name, **review}
            if review["status"] == "passed":
                add_take(current, kind, name, review=review, **info)
            else:
                current.setdefault("takes", {}).setdefault(kind, []).append({"name": name, "review": review, **info})
            self.save(fresh)
        if review["status"] != "passed":
            raise RuntimeError(f"{kind.title()} needs review: " + "; ".join(review["findings"][:4]))

    def _run_review(self, job: dict, tick) -> None:
        project = self._require_plan(job["project"], tick)
        shot = self._shot(project, job["shot"])
        if not shot.get("video"):
            raise RuntimeError("Render a clip before reviewing it")
        review = self._review_video(project, shot, shot["video"], tick)
        with self.lock:
            fresh = self.load(project["id"])
            current = self._shot(fresh, shot["id"])
            take = next(t for t in current["takes"]["video"] if t["name"] == shot["video"])
            take["review"] = review
            current.setdefault("quality", {})["video"] = {"name": shot["video"], **review}
            self.save(fresh)
        if review["status"] != "passed":
            raise RuntimeError("Video needs review: " + "; ".join(review["findings"][:4]))

    def accept_review(self, project_id: str, shot_id: str, kind: str, name: str, reason: str) -> dict:
        """An explicit director decision, kept alongside the model's original evidence."""
        if kind not in ("keyframe", "endframe", "video", "sketch") or not reason.strip():
            raise ValueError("Inspect the candidate and enter a reason before accepting it")
        with self.lock:
            project = self.load(project_id)
            shot = self._shot(project, shot_id)
            candidates = shot.get("sketches", []) if kind == "sketch" else shot.get("endframes", []) if kind == "endframe" else shot.get("takes", {}).get(kind, [])
            take = next((t for t in candidates if t["name"] == name), None)
            if not take and kind == "keyframe":
                earlier = next((t for t in shot.get("frame_repairs", [])
                                if t.get("name") == name and t.get("phase") == "start"), None)
                if earlier:
                    take = {"name": name, "review": copy.deepcopy(earlier["review"]), "recovered_from_repair": True}
            review = (take or {}).get("review")
            expected = visual_inputs(project, shot) if kind == "keyframe" else video_inputs(project, shot)
            if kind == "endframe":
                expected = ending_inputs(project, shot)
            elif kind == "sketch":
                lead, _ = starting_cast(project, shot)
                expected = sketch_of(shot, current_plate(project), project.get("reference") if lead else None, project)
            if not review or review.get("of") != expected or plan_status(project) != "ready":
                raise RuntimeError("The candidate's inputs are out of date; regenerate it before accepting")
            if take not in candidates:
                candidates.append(take)
            review.update(status="passed", version=director.REVIEW_VERSION, director_review={"reason": reason.strip(), "time": time.time()},
                          automated_status=review.get("automated_status", review["status"]))
            if kind == "endframe":
                shot["endframe"] = take
            elif kind == "sketch":
                shot["sketch"] = name
            else:
                select_take(shot, kind, name)
            shot.setdefault("quality", {})[kind] = {"name": name, **review}
            return self.save(project)

    def _run_cast(self, job: dict[str, Any], tick) -> None:
        """Generate the lead's reference portrait from the cast description."""
        project = self.load(job["project"])
        prompt = director.cast_prompt(project["cast"], project["scene"], project["look"])
        graph = graphs.keyframe_graph(prompt, random.randrange(1, 2**31), project["aspect"],
                                      f"open-cinema/{project['id']}/cast", size=graphs.CAST_SIZE,
                                      negative=director.image_negative(project["look"]))
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
        """Gemma 4 12B (8-bit) looks at the portrait and writes the traits that make this face recognisable."""
        project = self.load(project_id)
        reference = project.get("reference")
        if not reference:
            return
        graph = graphs.lead_writer_graph("identity", project["title"], project["scene"], project["look"],
                                         photo=self._upload(project_id, reference), seed=7)
        record = self.comfy.wait(self.comfy.submit(graph), on_tick=tick, timeout=600)
        note = "".join(record["outputs"].get("lead", {}).get("text", [""])).strip().rstrip(".")
        if not usable_identity(note):
            # Keep the casting description as the source of truth if the vision model talks about the
            # request instead of describing the portrait, and avoid retrying it for every frame.
            note = ((project.get("cast") or "").strip() + ". Match the face and hair in the reference portrait").lstrip(". ")
        with self.lock:
            fresh = self.load(project_id)
            if note and fresh.get("reference") == reference:
                fresh["lead_identity"], fresh["lead_identity_of"] = note, reference
                self.save(fresh)

    def _run_describe_lead(self, job: dict[str, Any], tick) -> None:
        self._describe_lead(job["project"], tick)

    def _make_world(self, project_id: str, tick, job: dict[str, Any] | None = None) -> str:
        """HiDream-O1 paints the film's world with nobody in it; Gemma checks it really is empty (re-rolling up
        to three times), so the only face any shot ever sees is the lead's portrait."""
        project = self.load(project_id)
        world = project.get("world") or {}
        seed = (world.get("seed") or random.randrange(1, 2**31)) + 1_000_003 * len(world.get("takes", []))
        prompt = director.world_plate_prompt(project["scene"], project["look"])
        folder = self.path(project_id)
        for attempt in range(3):
            if job:
                job["label"] = "Painting the world" + (f" · try {attempt + 1}" if attempt else "")
            files = self.comfy.run(graphs.keyframe_graph(prompt, seed + attempt, project["aspect"],
                                                         f"open-cinema/{project_id}/world",
                                                         negative=director.image_negative(project["look"])), on_tick=tick)
            name = f"world_{uuid.uuid4().hex[:6]}.png"
            self.comfy.download(files[0], folder / name)
            if job:
                job["label"] = "Painting the world · checking it's empty"
            record = self.comfy.wait(self.comfy.submit(graphs.people_check_graph(
                self._upload(project_id, name), director.PEOPLE_CHECK)), on_tick=tick, timeout=600)
            answer = "".join(record["outputs"].get("answer", {}).get("text", [""])).strip().upper()
            empty = not answer.startswith("YES")
            if empty or attempt == 2:
                break
        with self.lock:
            fresh = self.load(project_id)
            unit = fresh.setdefault("world", {})
            unit.setdefault("seed", seed)
            unit.setdefault("takes", []).append({"name": name, "prompt": prompt, "seed": seed + attempt,
                                                 "of": world_of(fresh), "empty": empty})
            unit["plate"] = name
            self.save(fresh)
        return name

    def _run_world(self, job: dict[str, Any], tick) -> None:
        if job.get("auto") and current_plate(self.load(job["project"])):
            return  # something earlier in the queue already painted it
        self._make_world(job["project"], tick, job)

    def choose_world(self, project_id: str, name: str) -> dict[str, Any]:
        with self.lock:
            project = self.load(project_id)
            unit = project.get("world") or {}
            if not any(t["name"] == name for t in unit.get("takes", [])):
                raise KeyError(f"no world plate {name}")
            unit["plate"] = name
            return self.save(project)

    def _run_keyframe(self, job: dict[str, Any], tick) -> None:
        """Finish independent storyboard staging with identity and, for wide shots, world references."""
        project = self._require_plan(job["project"], tick)
        if cast_stale(project):
            self._run_cast({"project": project["id"]}, tick)
            project = self.load(job["project"])
        index = next(i for i, s in enumerate(project["shots"]) if s["id"] == job["shot"])
        shot = project["shots"][index]
        if story_stale(project, shot):
            raise RuntimeError("The story beat changed. Rewrite this shot or confirm it still tells the beat.")
        planned_visual = visual_inputs(project, shot)
        look, scene, aspect = project["look"], project["scene"], project["aspect"]
        look = director.look_for_state(look, review_requirements(project, shot, "start")["state"])
        continuity = state_design(project)
        prefix = f"open-cinema/{project['id']}/key_{shot['id']}"
        plate = current_plate(project) or self._make_world(project["id"], tick)
        lead, visible_others = starting_cast(project, shot)
        reference = project.get("reference") if lead else None
        if reference and not lead_identity(project):  # a new portrait: describe its face before painting it
            job["label"] = f"Keyframe {index + 1} · describing the lead"
            self._describe_lead(project["id"], tick)
            project = self.load(job["project"])
        sketch = self._current_sketch(project, shot, plate, reference)
        if not sketch:  # the storyboard drawing sets the composition, so it's drawn (or redrawn) first
            job["label"] = f"Keyframe {index + 1} · drawing the storyboard"
            sketch = self._draw_sketch(project["id"], shot["id"], tick)
            project = self.load(job["project"])
            shot = self._shot(project, shot["id"])
            if visual_inputs(project, shot) != planned_visual:
                raise RuntimeError("The staging changed while drawing. Render again to use the updated direction.")
        job["label"] = f"Keyframe {index + 1}"
        seed = take_seed(shot, "keyframe")
        identity = lead_identity(project) if reference else ""
        source = sketch
        previous_end = shot.get("frame_source") == "previous_end"
        if previous_end:
            previous = project["shots"][index-1] if index else {}
            if not previous.get("video") or video_stale(project, previous) or not review_passed(current_take(previous, "video")):
                raise RuntimeError("Render and review the preceding shot before using its final frame")
            source = self._last_frame(project["id"], previous["video"])
        prop = prop_input(project, shot)
        if prop and not prop["image"]:
            raise RuntimeError("Generate the prop reference for its starting state on Story first")
        use_world_reference = shot["shot_size"] in director.WIDE_SIZES and not prop
        prompt = director.shot_prompt(shot["action"], shot["shot_size"], look, continuity, has_cast=bool(reference),
                                      camera_move=shot["camera_move"], lead=lead,
                                      world=scene.split(". ")[0].strip().rstrip("."), identity=identity,
                                      cast=project.get("cast", ""), storyboard=bool(sketch) and not previous_end,
                                      others=visible_others, line=shot.get("line", ""),
                                      start_frame=shot.get("start_frame", ""), world_reference=use_world_reference)
        prompt += " " + director.state_direction(shot_states(project, shot)[0], visible_keys=shot.get("start_checks"))
        if previous_end:
            people = review_requirements(project, shot, "start")["people"]
            established = {name.casefold() for name in previous.get("end_cast", [])}
            cast_direction = "; ".join(f"{name}, the same person already in Picture 1" if name.casefold() in established
                                       else description for name, description in people.items())
            prompt = director.following_frame_prompt(shot.get("start_frame") or shot["action"], shot["shot_size"],
                cast_direction, review_requirements(project, shot, "start")["state"])
        # The accepted performance owns identity and material; a portrait can redesign both.
        refs = [] if previous_end else [self._upload(project["id"], name) for name in
                                       (reference, plate if use_world_reference else None) if name]
        if prop and not previous_end:
            refs.append(self._upload(project["id"], prop["image"]))
            prompt += " " + director.prop_reference_direction(len(refs) + 1, prop["name"], prop["description"], prop["state"])
        graph = graphs.coverage_graph(prompt, seed, self._upload(project["id"], source), prefix, aspect,
                                      second_reference=refs[0] if refs else None,
                                      third_reference=refs[1] if len(refs) > 1 else None,
                                      detailed=project.get("image_quality") == "detailed")
        graph = graphs.verify_cast(graph, "15", len(shot["start_cast"]) if shot.get("start_cast") is not None else
                                   director.character_count(lead, visible_others))
        recipe = {"kind": "shot", "world": plate, "lead": reference, "identity": identity, "sketch": sketch,
                  "composition_version": 2, "world_reference": use_world_reference,
                  "source_frame": source, "frame_source": shot.get("frame_source", "storyboard"),
                  "visual": visual_inputs(project, shot),
                  "others": shot.get("others", ""),
                  "action": shot["action"], "shot_size": shot["shot_size"], "camera_move": shot["camera_move"],
                  "steps": ["Qwen-Image-Edit 2511 · " + ("previous performance" if previous_end else
                            "the storyboard" + (" + the lead" if reference else "") +
                            (" + the world" if use_world_reference else "")) +
                            (" · 40 steps" if project.get("image_quality") == "detailed" else " · 4 steps")]}
        files, seed, cast_review = self._render_checked(graph, seed, tick)
        name = f"key_{shot['id']}_{uuid.uuid4().hex[:6]}.png"
        self.comfy.download(files[0], self.path(project["id"]) / name)
        if cast_review["status"] != "passed":
            cast_review["of"] = visual_inputs(project, shot)
            self._record_candidate(project["id"], shot["id"], "keyframe", name, cast_review, prompt=prompt, seed=seed, recipe=recipe)
        job["label"] = f"Keyframe {index + 1} · checking state and style"
        review = self._review_image(project, shot, name, tick)
        name, review = self._repair_frame(project, shot, name, review, tick, "start")
        self._record_candidate(project["id"], shot["id"], "keyframe", name, review, prompt=prompt, seed=seed, recipe=recipe)

    def _run_repair_frame(self, job: dict, tick) -> None:
        project = self._require_plan(job["project"], tick)
        shot = self._shot(project, job["shot"])
        kind = job.get("candidate_kind", "keyframe")
        if kind not in ("keyframe", "endframe"):
            raise ValueError("Choose an opening or ending frame")
        candidates = shot.get("endframes", []) if kind == "endframe" else shot.get("takes", {}).get(kind, [])
        candidate = next(t for t in candidates if t["name"] == shot.get("quality", {}).get(kind, {}).get("name"))
        expected = visual_inputs(project, shot) if kind == "keyframe" else ending_inputs(project, shot)
        if candidate["review"].get("of") != expected:
            raise RuntimeError("The candidate is out of date; generate a new frame")
        name, review = self._repair_frame(project, shot, candidate["name"], candidate["review"], tick,
                                          "start" if kind == "keyframe" else "end")
        review["of"] = expected
        if kind == "keyframe":
            self._record_candidate(project["id"], shot["id"], kind, name, review, recipe=candidate.get("recipe"), seed=shot["seed"],
                                   repaired_from=candidate["name"])
        else:
            with self.lock:
                fresh = self.load(project["id"])
                current = self._shot(fresh, shot["id"])
                take = {"name":name,"of":expected,"review":review,"repaired_from":candidate["name"]}
                current.setdefault("endframes", []).append(take)
                current.setdefault("quality", {})[kind] = {"name":name, **review}
                if review["status"] == "passed":
                    current["endframe"] = take
                self.save(fresh)
            if review["status"] != "passed":
                raise RuntimeError("Ending frame still needs review: " + "; ".join(review["findings"][:4]))

    def _repair_frame(self, project: dict, shot: dict, name: str, review: dict, tick, phase: str) -> tuple[str, dict]:
        """Two bounded visual repairs; retain the failed images and evidence for inspection."""
        for attempt in range(2):
            if review["status"] == "passed":
                break
            with self.lock:
                fresh = self.load(project["id"])
                self._shot(fresh, shot["id"]).setdefault("frame_repairs", []).append(
                    {"name": name, "phase": phase, "review": review})
                self.save(fresh)
            prop = prop_input(project, shot, phase)
            prompt = director.frame_repair_prompt(shot.get("start_frame" if phase == "start" else "end_state", ""),
                         json.dumps(review_requirements(project, shot, phase)), json.dumps(review["findings"]))
            files = self.comfy.run(graphs.coverage_graph(prompt, (shot["seed"] + 97 * (attempt + 1)) % 2**31,
                    self._upload(project["id"], name), f"open-cinema/{project['id']}/repair_{shot['id']}", project["aspect"],
                    keep_layout=True, detailed=True), on_tick=tick)
            name = f"repair_{phase}_{shot['id']}_{uuid.uuid4().hex[:6]}.png"
            self.comfy.download(files[0], self.path(project["id"]) / name)
            review = self._review_image(project, shot, name, tick, phase)
        return name, review

    def _run_prop(self, job: dict, tick) -> None:
        project = self.load(job["project"])
        prop = next(p for p in project.get("props", []) if p["id"] == job["prop"])
        state = str(job["value"]).strip()
        valid_states = {project["scene_state"][prop["state_key"]],
                        *(s.get("state_changes", {}).get(prop["state_key"]) for s in project["shots"])}
        if state not in valid_states:
            raise ValueError("Choose a state from this film's continuity plan")
        prompt = director.prop_prompt(prop["description"], state, project["look"])
        variants = [v for v in prop.get("variants", {}).values() if v.get("of") == prop_design(project, prop)]
        prefix = f"open-cinema/{project['id']}/prop_{prop['id']}"
        seed = random.randrange(2**31)
        graph = graphs.coverage_graph(prompt + " Preserve the exact object design in Picture 1; change only its stated condition.",
                    seed, self._upload(project["id"], variants[0]["name"]), prefix, "1:1", keep_layout=True) if variants else \
                graphs.keyframe_graph(prompt, seed, "1:1", prefix)
        files = self.comfy.run(graph, on_tick=tick)
        name = f"prop_{prop['id']}_{uuid.uuid4().hex[:6]}.png"
        self.comfy.download(files[0], self.path(project["id"]) / name)
        with self.lock:
            fresh = self.load(project["id"])
            current = next(p for p in fresh.get("props", []) if p["id"] == prop["id"])
            current.setdefault("variants", {})[state] = {"name": name, "of": prop_design(project, prop)}
            self.save(fresh)

    def _ending_frame(self, project: dict, shot: dict, start: str, tick) -> str:
        snapshot = {**ending_inputs(project, shot), "start": start}
        cached = shot.get("endframe") or {}
        if cached.get("of") == snapshot and review_passed(cached):
            return cached["name"]
        prop = prop_input(project, shot, "end")
        if prop and not prop["image"]:
            raise RuntimeError("Generate the prop reference for its ending state on Story first")
        visible = review_requirements(project, shot, "end")["state"]
        prompt = director.ending_frame_prompt(shot["action"], shot.get("end_state", ""), project["look"], visible, state_design(project))
        files = self.comfy.run(graphs.coverage_graph(prompt, take_seed(shot, "video"), self._upload(project["id"], start),
                    f"open-cinema/{project['id']}/end_{shot['id']}", project["aspect"], keep_layout=True,
                    detailed=project.get("image_quality") == "detailed"), on_tick=tick)
        name = f"end_{shot['id']}_{uuid.uuid4().hex[:6]}.png"
        self.comfy.download(files[0], self.path(project["id"]) / name)
        review = self._review_image(project, shot, name, tick, "end")
        name, review = self._repair_frame(project, shot, name, review, tick, "end")
        review["of"] = snapshot
        with self.lock:
            fresh = self.load(project["id"])
            current = self._shot(fresh, shot["id"])
            candidate = {"name": name, "of": snapshot, "review": review, "prompt": prompt}
            current.setdefault("endframes", []).append(candidate)
            current.setdefault("quality", {})["endframe"] = {"name": name, **review}
            if review["status"] == "passed":
                current["endframe"] = candidate
            self.save(fresh)
        if review["status"] != "passed":
            raise RuntimeError("Ending frame needs review: " + "; ".join(review["findings"][:4]))
        return name

    # ---------- storyboard drawings ----------
    def _current_sketch(self, project: dict[str, Any], shot: dict[str, Any], plate: str | None,
                        reference: str | None) -> str | None:
        """The shot's storyboard drawing, if it was drawn from today's action, framing, world and lead."""
        return shot.get("sketch") if not sketch_stale(project, shot) else None

    def _draw_sketch(self, project_id: str, shot_id: str, tick, job: dict[str, Any] | None = None) -> str:
        """Plan each shot independently; reference images cannot pull the drawing back to an establishing view."""
        project = self._require_plan(project_id, tick)
        index = next(i for i, s in enumerate(project["shots"]) if s["id"] == shot_id)
        plate = current_plate(project)
        project = self.load(project_id)
        shot = project["shots"][index]
        lead, visible_others = starting_cast(project, shot)
        reference = project.get("reference") if lead else None
        if job:
            job["label"] = f"Storyboard {index + 1}"
        expected_cast = len(shot["start_cast"]) if shot.get("start_cast") is not None else director.character_count(lead, visible_others)
        prompt = director.sketch_prompt(shot["action"], shot["shot_size"], shot["camera_move"], has_cast=bool(reference),
                                        lead=lead, world=project["scene"], cast=project.get("cast", ""),
                                        continuity="", start_frame=shot.get("start_frame", ""),
                                        others=visible_others, expected_cast=expected_cast)
        prompt += " " + director.sketch_state_prompt(shot_states(project, shot)[0], visible_keys=shot.get("start_checks"))
        seed = (shot["seed"] + 7_777 * len(shot.get("sketches", []))) % 2**31
        prop = prop_input(project, shot)
        if prop:
            prompt += " Exact recurring prop geometry: " + prop["description"] + ". Depict every named colour as a grey value only."
        frame = current_take(shot, "keyframe")
        source_frame = shot.get("keyframe") if review_passed(frame) and frame.get("review", {}).get("of") == visual_inputs(project, shot) else None
        if source_frame:
            prompt = director.sketch_from_frame_prompt()
            graph = graphs.frame_storyboard_graph(self._upload(project_id, source_frame), seed, project["aspect"],
                      f"open-cinema/{project_id}/sketch_{shot_id}", expected_cast)
        else:
            graph = graphs.storyboard_graph(prompt, seed, project["aspect"],
                      f"open-cinema/{project_id}/sketch_{shot_id}", expected_cast)
        if job:
            job["detail"] = "Drawing a planning thumbnail, then checking visible cast. One attempt; flagged results are kept."
        files, seed, review = self._render_checked(graph, seed, tick)
        name = f"sketch_{shot_id}_{uuid.uuid4().hex[:6]}.png"
        self.comfy.download(files[0], self.path(project_id) / name)
        snapshot = sketch_of(shot, plate, reference, project)
        review["of"] = snapshot
        with self.lock:
            fresh = self.load(project_id)
            current = self._shot(fresh, shot_id)
            current.setdefault("sketches", []).append({"name": name, "prompt": prompt, "seed": seed,
                                                       "source_frame": source_frame,
                                                       "of": snapshot, "review": review})
            current.setdefault("quality", {})["sketch"] = {"name": name, **review}
            if review["status"] == "passed":
                current["sketch"] = name
            self.save(fresh)
        if review["status"] != "passed":
            raise RuntimeError("Storyboard needs review: " + "; ".join(review["findings"]))
        return name

    def _run_sketch(self, job: dict[str, Any], tick) -> None:
        project = self.load(job["project"])
        try:
            shot = self._shot(project, job["shot"])
        except KeyError:
            return  # the shot was deleted while its drawing waited in the queue
        lead = shot.get("lead", True) is not False
        plate = current_plate(project)
        if not job.get("redraw") and self._current_sketch(project, shot, plate,
                                                                    project.get("reference") if lead else None):
            return
        self._draw_sketch(job["project"], job["shot"], tick, job)

    def queue_sketches(self, project_id: str, shot_ids: list[str] | None = None, redraw: bool = False) -> list[dict[str, Any]]:
        project = self.load(project_id)
        with self.lock:
            waiting = {j["shot"] for j in self.jobs if j["project"] == project_id and j["kind"] == "sketch"
                       and j["state"] in ("queued", "running")}
        plate, jobs = current_plate(project), []
        for index, shot in enumerate(project["shots"]):
            reference = project.get("reference") if shot.get("lead", True) is not False else None
            drawn = self._current_sketch(project, shot, plate, reference)
            if (shot_ids is None or shot["id"] in shot_ids) and shot.get("action", "").strip() and \
                    (redraw or (shot["id"] not in waiting and not drawn)):
                jobs.append(self.enqueue("sketch", project_id, shot["id"], f"Storyboard {index + 1}", redraw=redraw))
        return jobs

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
        project = self._require_plan(job["project"], tick)
        index = next(i for i, s in enumerate(project["shots"]) if s["id"] == job["shot"])
        shot = project["shots"][index]
        if story_stale(project, shot):
            raise RuntimeError("The story beat changed. Rewrite this shot or confirm it still tells the beat.")
        if shot.get("transition") != "continue" and (job.get("redo_keyframe") or not shot.get("keyframe") or frame_stale(project, shot)):
            self._run_keyframe(job, tick)
            project = self.load(job["project"])
            shot = project["shots"][index]
        project_snapshot = copy.deepcopy(project)
        job["label"] = f"Shot {index + 1}"
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
        shot["keyframe"] = start
        frame_take = current_take(shot, "keyframe")
        if not review_passed(frame_take) or frame_take.get("review", {}).get("of") != visual_inputs(project, shot):
            job["label"] = f"Shot {index + 1} · checking opening frame"
            opening_review = self._review_image(project, shot, start, tick)
            with self.lock:
                fresh = self.load(project["id"])
                current = self._shot(fresh, shot["id"])
                for take in current.get("takes", {}).get("keyframe", []):
                    if take["name"] == start:
                        take["review"] = opening_review
                current.setdefault("quality", {})["keyframe"] = {"name": start, **opening_review}
                self.save(fresh)
            if opening_review["status"] != "passed":
                raise RuntimeError("Opening frame needs review: " + "; ".join(opening_review["findings"][:4]))
        fresh = self.load(project["id"])
        if plan_status(fresh) != "ready" or video_inputs(fresh, self._shot(fresh, shot["id"])) != video_inputs(project, shot):
            raise RuntimeError("The shot changed during opening-frame review. Render again to use the latest direction.")
        prompt = director.motion_prompt(shot["action"], shot["camera_move"], shot.get("sound", ""),
                                        director.look_for_state(project["look"], review_requirements(project, shot, "start")["state"]),
                                        director._join(project.get("cast", ""), lead_identity(project)).rstrip("."),
                                        shot["shot_size"], state_design(project),
                                        shot.get("lead", True), others_in(project, shot), shot.get("line", ""),
                                        shot.get("start_frame", ""), shot.get("end_state", ""))
        prompt += " " + director.state_direction(shot_states(project, shot)[0], shot.get("state_changes", {}),
                                                 list(set(shot.get("start_checks", []) + shot.get("end_checks", []))))
        prompt += " " + director.cast_transition_direction(shot.get("start_cast"), shot.get("end_cast"))
        seed = take_seed(shot, "video")
        # the zoomed end frame also pins the subject to its first pose, so a shot with someone acting in it
        # comes out as a zooming still: only empty wide views get the guide
        guide = (director.CAMERA_PATHS.get(shot["camera_move"])
                 if shot.get("lead") is False and not others_in(project, shot)
                 and shot["shot_size"] in director.WIDE_SIZES else None)
        if shot.get("guide_end"):
            end, end_strength = self._ending_frame(project, shot, start, tick), 1.0
            shot["endframe"] = self._shot(self.load(project["id"]), shot["id"])["endframe"]
        else:
            end, end_strength = (self._path_guide(project["id"], start, guide), guide[3]) if guide else (None, 1.0)
        graph = graphs.shot_graph(self._upload(project["id"], start), prompt, seed, project["aspect"],
                                  float(shot["seconds"]), f"open-cinema/{project['id']}/shot_{shot['id']}",
                                  end_image=end and self._upload(project["id"], end), end_strength=end_strength,
                                  performance=job.get("ai_mode", "normal"))
        files = self.comfy.run(graph, on_tick=tick)
        name = f"shot_{shot['id']}_{uuid.uuid4().hex[:6]}.mp4"
        self.comfy.download(files[0], self.path(project["id"]) / name)
        job["label"] = f"Shot {index + 1} · reviewing four video samples"
        review = self._review_video(project, shot, name, tick)
        self._record_candidate(project["id"], shot["id"], "video", name, review, prompt=prompt, seed=seed, keyframe=start,
                               performance_mode=job.get("ai_mode", "normal"),
                               of={**video_inputs(project_snapshot, shot), "keyframe": start})

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
        if plan_status(project) != "ready":
            raise RuntimeError("Review scene continuity before cutting the film")
        if any(not review_passed(current_take(s, "video")) or
               current_take(s, "video").get("review", {}).get("of") != video_inputs(project, s) for s in project["shots"]):
            raise RuntimeError("Every clip needs a current passing video review before the final cut")
        if any(story_stale(project, s) or frame_stale(project, s) or video_stale(project, s) for s in project["shots"]):
            raise RuntimeError("The script or staging changed. Render film to update affected shots before cutting.")
        videos = [s.get("video") for s in project["shots"]]
        if not videos or not all(videos):
            raise RuntimeError("Every shot needs a rendered video before the final cut")
        folder = self.path(project["id"])
        name = f"film_{uuid.uuid4().hex[:6]}.mp4"
        _, _, width, height = graphs.ASPECTS[project["aspect"]]
        cut_from = film_inputs(project)
        self._assemble(project, [folder / v for v in videos], name, width, height, job, tick,
                       title_clip=self._title_clip(project))
        wave = self._waveform(project["id"], name)
        with self.lock:
            project = self.load(job["project"])
            project["film"], project["film_of"], project["film_wave"] = name, cut_from, wave
            self.save(project)

    def _waveform(self, project_id: str, film: str) -> str | None:
        """The cut's sound as a picture, for the Sound track on the Edit page."""
        name = f"{Path(film).stem}_wave.png"
        if not (self.path(project_id) / name).is_file():
            result = subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-i", str(self.path(project_id) / film),
                                     "-filter_complex", "aformat=channel_layouts=mono,showwavespic=s=2400x120:colors=white",
                                     "-frames:v", "1", str(self.path(project_id) / name)])
            if result.returncode:
                return None
        return name

    def waveform(self, project_id: str) -> dict[str, Any]:
        """Draw the waveform of a cut made before the Sound track was real."""
        with self.lock:
            project = self.load(project_id)
            if project.get("film") and not project.get("film_wave"):
                project["film_wave"] = self._waveform(project_id, project["film"])
            return self.save(project)

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
        inputs, graph = cut_filter(dressed, transitions, bool(project.get("finish")), (width, height))
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
            return self.save(project)

    def _run_title_frame(self, job: dict[str, Any], tick) -> None:
        project = self.load(job["project"])
        source = current_plate(project) or self._make_world(project["id"], tick, job)  # carved into the world itself
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
            add_take(unit, "keyframe", name, prompt=prompt, seed=seed,
                     recipe={"kind": "title", "world": source})
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
                                  end_strength=0.85, performance=job.get("ai_mode", "normal"))
        files = self.comfy.run(graph, on_tick=tick)
        name = f"title_shot_{uuid.uuid4().hex[:6]}.mp4"
        self.comfy.download(files[0], self.path(project["id"]) / name)
        with self.lock:
            project = self.load(job["project"])
            add_take(project.setdefault("title_shot", {}), "video", name, prompt=prompt, seed=seed, keyframe=start)
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
        name = f"score_{uuid.uuid4().hex[:6]}{Path(files[0]['filename']).suffix or '.flac'}"
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
        if not settings["trailer"]["lines"].strip() and (project.get("beats") or project.get("logline")):
            job["label"] = "Trailer · writing the cards"  # from the story, rather than a generic "A film in N shots"
            self._run_write_story({"project": project["id"], "target": "trailer"}, tick)
            project = self.load(job["project"])
            settings = motion_settings(project)
        lines = [l.strip() for l in (settings["trailer"]["lines"] or default_trailer(project)).splitlines() if l.strip()]
        bare = lambda text: "".join(ch for ch in text.lower() if ch.isalnum())  # noqa: E731
        if lines and bare(lines[-1]) == bare(project["title"]):
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
        """Gemma 4 12B (8-bit) writes (or refines, or describes from the casting photo) the lead and continuity notes."""
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
        """Gemma 4 12B (8-bit) writes the whole story page, or one field of it, consistent with the rest."""
        project = self.load(job["project"])
        target = job.get("target", "everything")
        avoid_title_words = repeated_title_words([p for p in self.list_projects() if p["id"] != project["id"]]) if target in ("everything", "title") else ""
        graph = graphs.story_writer_graph(target, project.get("idea", ""), project["title"], project.get("logline", ""),
                                          project["scene"], project["look"] if target != "everything" else "",
                                          project.get("cast", "") if target != "everything" else "",
                                          seed=random.randrange(1, 2**31),
                                          beats=director.beat_list_text(project.get("beats") or []),
                                          count=int(job.get("count", 3)),
                                          characters=project.get("characters", "") if target != "everything" else "",
                                          avoid_title_words=avoid_title_words)
        record = self.comfy.wait(self.comfy.submit(graph), on_tick=tick, timeout=900)
        out = {k: "".join(record["outputs"].get(k, {}).get("text", [""])).strip()
               for k in ("title", "logline", "world", "look", "palette", "lead", "continuity", "trailer", "beats",
                         "characters")}
        if target == "everything" and len(out["beats"].splitlines()) < 3:
            # A small model can omit the final label or run out of tokens. Complete the story before
            # saving anything or scheduling expensive downstream work, using the draft it just wrote.
            job["label"] = "Writing the story · completing the beats"
            retry = graphs.story_writer_graph(
                "beats", project.get("idea", ""), out["title"] or project["title"],
                out["logline"] or project.get("logline", ""), out["world"] or project["scene"],
                out["look"] or project["look"], out["lead"] or project.get("cast", ""),
                seed=random.randrange(1, 2**31), characters=out["characters"])
            result = self.comfy.wait(self.comfy.submit(retry), on_tick=tick, timeout=900)
            out["beats"] = "".join(result["outputs"].get("beats", {}).get("text", [""])).strip()
        wanted = {"everything": ("title", "logline", "world", "look", "palette", "lead", "continuity", "characters",
                                 "beats"), "characters": ("characters",),
                  "title": ("title",), "logline": ("logline",), "world": ("world",),
                  "look": ("look",), "trailer": ("trailer",), "beats": ("beats",),
                  "more beats": ("beats",)}[target]
        if not any(out[k] for k in wanted):
            raise RuntimeError("The writer returned nothing usable; try again")
        if target == "everything":
            missing = [k for k in ("title", "logline", "world", "lead") if not out[k]]
            if len(out["beats"].splitlines()) < 3:
                missing.append("at least three story beats")
            if missing:
                raise RuntimeError("The story draft is incomplete (missing " + ", ".join(missing) + "); try again")
        with self.lock:
            fresh = self.load(job["project"])
            field = {"world": "scene", "lead": "cast", "trailer": "motion"}
            self._remember_story(fresh, tuple(field.get(k, k) for k in wanted) + (("palette",) if target == "look" else ()))
            if target == "look" and not fresh.get("palette"):
                ink, accent, glow, bg, _ = director.LOOK_PALETTES.get(fresh.get("look"), director.LOOK_PALETTES["None"])
                fresh["palette"] = {"bg": bg, "ink": ink, "accent": accent, "glow": glow}
            for key in wanted:
                value = out[key]
                if not value and not (target == "everything" and key == "characters"):
                    continue
                if key == "palette":
                    bg, ink, accent, glow = value.split(",")
                    fresh["palette"] = {"bg": bg, "ink": ink, "accent": accent, "glow": glow}
                elif key == "look":
                    fresh["look"] = value
                elif key == "beats":
                    new = [b.strip() for b in value.splitlines() if b.strip()]
                    if target == "more beats":  # continuing: on the end, never more than were asked for
                        new = (fresh.get("beats") or []) + new[:int(job.get("count", 3))]
                    fresh["beats"] = new
                elif key == "trailer":
                    motion = fresh.setdefault("motion", {}) or {}
                    motion.setdefault("trailer", {})["lines"] = value
                    fresh["motion"] = motion
                else:
                    fresh[field.get(key, key)] = value
            self.save(fresh)
            recast = target == "everything" and out["lead"] and (not fresh.get("reference") or fresh.get("reference_prompt"))
            repaint = target in ("everything", "world", "look") and not current_plate(fresh) and not any(
                j["project"] == fresh["id"] and j["kind"] == "world" and j["state"] in ("queued", "running")
                for j in self.jobs)
            storyboard = target == "everything" and all(is_blank(x) for x in fresh["shots"])
            # new beats get their shots (and, with auto-render, their videos) like everything Gemma writes
            fill = target == "more beats" and fresh.get("auto_render", True)
        if recast:  # the page is complete only with the lead's face; never replaces an uploaded photo
            self.enqueue("cast", job["project"], None, "Casting the new lead")
        if repaint:  # a new world needs its own plate before any shot is made in it
            self.enqueue("world", job["project"], None, "Painting the world", auto=True)
        if fill:
            self.enqueue("write_shots", job["project"], None, "Writing shots for the new beats", mode="board",
                         count=int(job.get("count", 3)))
        if storyboard:  # a new story on an empty board: write its shots, which then get drawn
            self.enqueue("write_shots", job["project"], None, "Writing the shots", mode="board",
                         count=len(fresh.get("beats") or []) or 5)

    # ---------- AI shot writer ----------
    def _run_write_shots(self, job: dict[str, Any], tick) -> None:
        """Gemma 4 12B (8-bit) writes shots from the story beats: "board" fills in the beats no kept shot tells yet (or,
        without beats, starts or continues the film), "next" adds the shot after the last, "rewrite" writes one shot
        again. Kept shots are the ones with a frame and the ones you wrote or edited; Gemma's own unmade drafts
        are replaced by a new board, so writing again gives a new draft instead of piling up."""
        project = self.load(job["project"])
        mode, count = job.get("mode", "board"), int(job.get("count", 5))
        shots, beats = project["shots"], project.get("beats") or []
        index = next((n for n, s in enumerate(shots) if s["id"] == job.get("shot")), len(shots) - 1)
        kept = [s for s in shots if is_made(s) or (s.get("action", "").strip() and not s.get("ai"))]
        context = kept if mode == "board" else shots
        missing = [n + 1 for n in range(len(beats)) if not any(s.get("beat") == n + 1 for s in kept)]
        # past the end of the story, every new shot brings a new beat with it, so the story grows with the film
        write = ", ".join(map(str, missing)) if missing else "new" if beats and kept else ""
        if mode == "next" and beats:
            told = {s.get("beat") for s in shots}
            last = max((s["beat"] for s in shots if s.get("beat")), default=0)
            untold = [b for b in range(1, len(beats) + 1) if b not in told]
            write = str(next((b for b in untold if b > last), untold[0] if untold else "new"))
        graph = graphs.shot_writer_graph(
            mode, project["title"], project.get("logline", ""), project["scene"], project["look"],
            project.get("cast", ""), project.get("continuity", ""), director.shot_list_text(context), index + 1,
            len(missing) if missing else count, seed=random.randrange(1, 2**31), beats=director.beat_list_text(beats),
            write_beats=write, characters=project.get("characters", ""))
        record = self.comfy.wait(self.comfy.submit(graph), on_tick=tick, timeout=900)
        if mode == "beat":
            return self._place_in_story(job, record)
        written = json.loads("".join(record["outputs"].get("shots", {}).get("text", ["[]"])) or "[]")
        if not written:
            raise RuntimeError("Gemma's reply had no shots in it")
        if mode == "board" and missing:
            coverage = [s.get("beat") for s in written]
            if coverage != missing:
                raise RuntimeError("The shot draft did not cover each requested beat in order; try again")
        if mode == "next" and write and write != "new" and written[0].get("beat") != int(write):
            raise RuntimeError("The shot draft did not cover the requested beat; try again")
        if write == "new" and mode != "rewrite" and any(not s.get("new_beat") for s in written):
            raise RuntimeError("The shot draft was missing a new beat; try again")
        if any(not s.get("start_frame", "").strip() or not s.get("end_state", "").strip() for s in written):
            raise RuntimeError("The shot draft was missing first-frame staging or an end state; try again")
        for shot in written:  # a beat that doesn't exist is no beat, unless the shot brought it
            if not (isinstance(shot.get("beat"), int) and 1 <= shot["beat"] <= len(beats)):
                shot["beat"] = None
            if write != "new" or mode == "rewrite":
                shot.pop("new_beat", None)
        with self.lock:
            fresh = self.load(job["project"])
            if any(fresh.get(k) != project.get(k) for k in ("beats", "scene", "cast", "characters", "continuity", "look")):
                raise RuntimeError("The story changed while shots were being written. Try again with the current story.")
            if mode == "rewrite":
                old, current = self._shot(project, job["shot"]), self._shot(fresh, job["shot"])
                if any(old.get(k) != current.get(k) for k in director.SHOT_FIELDS):
                    raise RuntimeError("This shot was edited while the writer was running. Your edits were kept; try again.")
            fresh["shots_history"] = (fresh.get("shots_history") or [])[-9:] + [
                {"shots": copy.deepcopy(fresh["shots"]), "beats": list(fresh.get("beats") or [])}]
            fresh["shots_rev"] = fresh.get("shots_rev", 0) + 1
            for shot in written:  # new beats go on the end of the story, in order
                text = shot.pop("new_beat", None)
                if text:
                    fresh.setdefault("beats", []).append(text)
                    shot["beat"] = len(fresh["beats"])
            if mode == "rewrite":
                target = self._shot(fresh, job["shot"])
                update = {k: v for k, v in written[0].items() if k in director.SHOT_FIELDS}
                if index == 0:
                    update.pop("transition", None)
                if update.get("beat") is None:
                    update.pop("beat", None)
                target.update(update, ai=True)
                target["beat_source"] = beat_text(project, target)
                new = [target]
            else:
                new = [new_shot(takes={"keyframe": [], "video": []}, ai=True, **w)
                       for w in (written[:1] if mode == "next" else written[:len(missing) or count])]
                for shot in new:
                    shot["beat_source"] = beat_text(fresh, shot)
                if mode == "next":
                    fresh["shots"].append(new[0])
                else:
                    keep = {s["id"] for s in kept}
                    board = [s for s in fresh["shots"] if s["id"] in keep or (is_made(s) or (
                        s.get("action", "").strip() and not s.get("ai")))]  # also anything edited meanwhile
                    for shot in new:  # by beat: before the first kept shot of a later beat, else at the end
                        at = next((n for n, s in enumerate(board) if s["id"] in keep and s.get("beat")
                                   and shot.get("beat") and s["beat"] > shot["beat"]), len(board))
                        board.insert(at, shot)
                    fresh["shots"] = board
            fresh["shots"][0]["transition"] = "cut"
            self.save(fresh)
        if not fresh.get("continuity_plan"):
            self.enqueue("plan_continuity", job["project"], label="Planning continuity",
                         render_after=fresh.get("auto_render", True), draw_after=True)
        # Existing director-reviewed state is kept; the Story page asks for review after a rewrite.

    def _place_in_story(self, job: dict[str, Any], record: dict[str, Any]) -> None:
        """✨ Add to story: Gemma's beat for a shot that isn't in the story goes in right after the beat of the
        nearest shot before it, and the beats after it move down one."""
        text = next(iter(director.parse_new_beats("".join(record["outputs"].get("new_beats", {}).get("text", [""])))
                         ), "") or "".join(record["outputs"].get("new_beats", {}).get("text", [""])).strip()
        if not text:
            raise RuntimeError("Gemma's reply had no beat in it")
        with self.lock:
            fresh = self.load(job["project"])
            fresh["shots_history"] = (fresh.get("shots_history") or [])[-9:] + [
                {"shots": copy.deepcopy(fresh["shots"]), "beats": list(fresh.get("beats") or [])}]
            fresh["shots_rev"] = fresh.get("shots_rev", 0) + 1
            index = next(n for n, s in enumerate(fresh["shots"]) if s["id"] == job["shot"])
            after = next((s["beat"] for s in reversed(fresh["shots"][:index]) if s.get("beat")), 0)
            beats = fresh.setdefault("beats", [])
            beats.insert(after, text)
            for s in fresh["shots"]:
                if s.get("beat") and s["beat"] > after:
                    s["beat"] += 1
            fresh["shots"][index]["beat"] = after + 1
            self.save(fresh)

    def undo_shots(self, project_id: str) -> dict[str, Any]:
        """Put the storyboard back as it was before the last AI write (media made since is kept on its shot)."""
        with self.lock:
            project = self.load(project_id)
            if project.get("shots_history"):
                current = {s["id"]: s for s in project["shots"]}
                previous = project["shots_history"].pop()
                if isinstance(previous, dict):  # the beats a write added go too
                    project["beats"], previous = previous["beats"], previous["shots"]
                for shot in previous:
                    if shot["id"] in current:
                        for key in ("keyframe", "video", "takes", "sketch", "sketches"):
                            shot[key] = current[shot["id"]].get(key, shot.get(key))
                project["shots"] = previous
                project["shots_rev"] = project.get("shots_rev", 0) + 1
            return self.save(project)

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
