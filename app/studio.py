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
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_nodes" / "comfyui-open-cinema"))

import director  # noqa: E402
import graphs  # noqa: E402
import speech  # noqa: E402
import staging  # noqa: E402
from comfy import Comfy, ComfyError  # noqa: E402
from events import Events  # noqa: E402

PROJECTS = ROOT / "projects"
_active_review_policy = ContextVar('review_policy', default=None)


@contextmanager
def using_review_policy(policy):
    token = _active_review_policy.set(policy)
    try:
        yield
    finally:
        _active_review_policy.reset(token)

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
            "sketch": 1, "plan_continuity": 0, "review": 3, "review_frame": 3}
SIDE_JOBS = {"write_shots", "write_story", "write_lead", "sketch", "motion_preview", "review", "review_frame", "plan_continuity"}


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
    cast, scene, look = project.get("cast", ""), project.get("scene", ""), project.get("look", "")
    return bool(prompt and prompt not in (director.cast_prompt(cast, scene, look),
                                           director.legacy_mixed_cast_prompt(cast, look)))


def world_of(project: dict[str, Any]) -> dict[str, Any]:
    """What the world plate depends on: if any of it changes, the plate is out of date."""
    return {"scene": project.get("scene", ""), "look": project.get("look", ""), "aspect": project.get("aspect", "")}


def world_environment(project: dict[str, Any]) -> list[str]:
    """Use only verbatim scene excerpts from the current continuity plan.

    Older, scene-stale or malformed plans fall back to the original scene.
    Since this extraction depends only on the world text, editing an unrelated
    shot must not needlessly invalidate a previously painted plate.
    """
    plan = project.get('continuity_plan') or {}
    source = plan.get('of')
    if not isinstance(source, dict) or source.get('scene', '') != project.get('scene', ''):
        return []
    scene = project.get('scene') or ''
    fragments = plan.get('environment')
    if not isinstance(fragments, list) or not fragments or len(fragments) > 20:
        return []
    if any(not isinstance(item, str) or not item.strip() or len(item) > 300 or item.strip() not in scene
           for item in fragments):
        return []
    fragments = [item.strip() for item in fragments]
    # Names already supplied as cast cannot be used as scenery; if the writer
    # returned one, keep the complete original direction rather than guess.
    people = [director.lead_name(project.get('cast', '')), *cast_list(project).keys()]
    if any(re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', fragment, re.I)
           for name in people if name.strip() for fragment in fragments):
        return []
    return fragments


def world_plate_inputs(project: dict[str, Any]) -> dict[str, Any]:
    # Keep the extraction result even when empty.  New fallback plates need a
    # distinct lineage from legacy takes, so a later usable extraction can
    # invalidate the earlier full-scene result.
    return {**world_of(project), 'environment': world_environment(project)}


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
    raw = (project.get("continuity_plan") or {}).get("design", project.get("continuity", ""))
    people = {director.lead_name(project.get("cast", "")): project.get("cast", ""), **cast_list(project)}
    return director.scope_shared_design(raw, people)


def draft_mode(project: dict) -> bool:
    return (_active_review_policy.get() or project.get("review_policy", "draft")) == "draft"


def plan_usable(project: dict) -> bool:
    status = plan_status(project)
    return status == "ready" or draft_mode(project) and status == "issues"


def review_outcome(review: dict) -> str:
    if review.get("status") == "passed":
        if review.get('outcome', 'passed') != 'passed' and not review.get('director_review'):
            return 'reviewer_error'
        return "passed"
    return review.get("outcome", "uncertain")


def valid_review_result(review) -> bool:
    """Only a complete, internally consistent automated contract can be trusted."""
    if not isinstance(review, dict) or review.get('version') != director.REVIEW_VERSION:
        return False
    issues = review.get('issues')
    if not isinstance(issues, list) or not isinstance(review.get('findings'), list):
        return False
    for issue in issues:
        if not isinstance(issue, dict) or issue.get('category') not in ('content_issue','uncertain','reviewer_error'):
            return False
        if any(not isinstance(issue.get(key), str) or not issue[key].strip() for key in ('code','message')):
            return False
        if issue.get('severity') not in ('warning','blocking'):
            return False
    expected = director.review_result(issues)
    return all(review.get(key) == expected[key] for key in ('status','outcome','findings'))


def temporal_drift_suggestion(review: dict) -> dict | None:
    """Offer an optional new take only for repeated, structured temporal evidence.

    Vision-model verdicts are not independently confirmed, so this deliberately
    never initiates rendering. Broken or uncertain evidence produces no advice.
    """
    if not valid_review_result(review) or review.get('outcome') != 'content_issue' or review.get('director_review'):
        return None
    samples = review.get('samples')
    if not isinstance(samples, list) or len(samples) != 4 or any(not valid_review_result(sample) for sample in samples):
        return None
    if any(issue.get('category') != 'content_issue' for sample in samples for issue in sample.get('issues', [])):
        return None
    for field, label in (('style', 'visual style'), ('cast', 'character appearance')):
        evidence = samples[0].get('evidence')
        first = evidence.get(field) if isinstance(evidence, dict) else None
        if not isinstance(first, dict):
            continue
        if first.get('verdict') != 'pass' or not str(first.get('observed', '')).strip():
            continue
        later = []
        for index, sample in enumerate(samples[1:], start=2):
            evidence = sample.get('evidence')
            observation = evidence.get(field) if isinstance(evidence, dict) else None
            if isinstance(observation, dict) and observation.get('verdict') == 'fail' and str(observation.get('observed', '')).strip() and any(
                    issue.get('category') == 'content_issue' and issue.get('code') == field + '_mismatch'
                    for issue in sample.get('issues', [])):
                later.append(index)
        if len(later) >= 2:
            return {'kind': field, 'samples': later,
                    'message': f'The visual check suggests {label} may drift after the opening frame. '
                               'Watch this take; you can try another while keeping the original.'}
    return None


def take_usable(project: dict, take: dict | None) -> bool:
    review = (take or {}).get("review") or {}
    return review_passed(take) or draft_mode(project) and review.get("version") == director.REVIEW_VERSION and review.get('status') == 'needs_review'


def review_pending(take: dict) -> bool:
    return any(issue.get('code') == 'pending_review' for issue in take.get('review', {}).get('issues', []))


def film_review(project: dict) -> dict:
    """A draft never launders uncertain evidence into an automated pass."""
    findings = []
    for index, shot in enumerate(project.get("shots", [])):
        for kind in ("keyframe", "endframe", "video"):
            take = shot.get("endframe") if kind == "endframe" else current_take(shot, kind)
            if not take or kind == "endframe" and not shot.get("guide_end"):
                continue
            review = take.get("review") or {}
            if not review_passed(take):
                findings.append({"shot": shot["id"], "shot_number": index + 1, "kind": kind, "name": take.get('name'),
                                 "outcome": review_outcome(review),
                                 "findings": review.get("findings") or ["This take has not been checked with the current reviewer."]})
    plan_issues = (project.get("continuity_plan") or {}).get("issues", [])
    if plan_status(project) == "issues":
        findings.insert(0, {"shot": None, "shot_number": None, "kind": "continuity", "outcome": "uncertain", "findings": plan_issues})
    complete = bool(project.get('shots')) and all(s.get('video') for s in project['shots'])
    stale = bool(project.get('film') and (project.get('film_of') != film_inputs(project) or any(
        story_stale(project, shot) or frame_stale(project, shot) or video_stale(project, shot) for shot in project['shots'])))
    return {"status": ('draft' if findings or project.get('film_marked_draft') or stale else 'passed') if project.get('film') and complete else 'pending', "findings": findings,
            'ready_to_finalize': bool(project.get('film_marked_draft') and not findings and complete and not stale),
            "stale": stale}


def _cast_identity_key(project: dict, name: str) -> str:
    key = name.strip().casefold()
    lead = director.lead_name(project.get('cast', '')).casefold()
    return '__lead__' if key and key in {'lead', 'the lead', lead} else key


def _merge_cast_names(project: dict, *rosters: list[str]) -> list[str]:
    """Keep the first spelling of each visible person across old and new rosters."""
    names, seen = [], set()
    for roster in rosters:
        for entry in roster:
            name = entry.strip()
            key = _cast_identity_key(project, name)
            if key and key not in seen:
                names.append(name)
                seen.add(key)
    return names


def review_requirements(project: dict, shot: dict, phase: str) -> dict:
    before, after = shot_states(project, shot)
    start_names, end_names = shot.get("start_cast"), shot.get("end_cast")
    # Existing plans can contain whitespace from older model output.
    start_names = _merge_cast_names(project, start_names) if start_names is not None else None
    end_names = _merge_cast_names(project, end_names) if end_names is not None else None
    descriptions = {name.casefold(): description for name, description in cast_list(project).items()}
    def roster_count(names):
        if names is None:
            return None
        counts = [director.roster_entry_count(name, descriptions.get(name.casefold(), "")) for name in names]
        return None if any(count is None for count in counts) else sum(counts)
    names = start_names if phase == "start" else end_names
    if phase == "middle":
        keys = [k for k in shot.get("start_checks", []) if k in shot.get("end_checks", []) and before.get(k) == after.get(k)]
        names = _merge_cast_names(project, start_names or [], end_names or [])
        start_count, end_count = roster_count(start_names), roster_count(end_names)
        allowed = list(range(min(start_count, end_count), max(start_count, end_count) + 1)) \
            if start_count is not None and end_count is not None else None
        count = roster_count(names) if allowed is not None else None
    else:
        keys = shot.get(phase + "_checks", [])
        count = roster_count(names)
        allowed = [count] if count is not None else None
    unresolved_opening = shot.get('cast_roster_unresolved') or []
    if phase in ('start', 'middle') and unresolved_opening:
        count, allowed = None, None
    state = before if phase != "end" else after
    people = {director.lead_name(project.get("cast", "")) or "Lead": project.get("cast", ""), **cast_list(project)}
    unresolved_cast = list(unresolved_opening) if phase in ('start', 'middle') else []
    if names is not None:
        visible = {n.casefold() for n in names}
        lead_aliases = {"lead", "the lead", director.lead_name(project.get("cast", "")).casefold()}
        people = {k:v for k,v in people.items() if k.casefold() in visible or k == next(iter(people)) and visible & lead_aliases}
        described = {key.casefold() for key in people}
        for name in names:
            if name.casefold() in described or name.casefold() in lead_aliases:
                continue
            # A group label carries visual evidence; a bare proper name does not.
            cardinality = director.roster_entry_count(name)
            if cardinality is None or cardinality > 1:
                people[name] = name
            else:
                unresolved_cast.append(name)
    facts = {k: state[k] for k in keys if k in state}
    unresolved = []
    visible = {n.casefold() for n in names or []}
    for key, value in list(facts.items()):
        subject, separator, field = key.partition(' · ')
        unknown = str(value).casefold() in ('unknown', 'n/a', 'unknown before first change', 'not established')
        absent_visible_actor = separator and subject.casefold() in visible and field.casefold() in ('location','position') and str(value).casefold() == 'none'
        if unknown or absent_visible_actor:
            unresolved.append(key)
            del facts[key]
    prop = next((p for p in project.get("props", []) if p["id"] == shot.get("prop_id")), None)
    if prop and (prop.get("state_key") in keys or phase == "middle" and
                 prop.get("state_key") in shot.get("start_checks", []) and prop.get("state_key") in shot.get("end_checks", [])):
        facts["Design of " + prop["name"]] = prop["description"]
    facts.update(staging.visual_facts(shot.get('start_frame', ''), project.get('look', ''), people, phase))
    return {"state": facts, "count": count, "phase": phase, 'unresolved_facts': unresolved, 'unresolved_cast': unresolved_cast,
            'advisory_facts': list(staging.material_facts(project.get('look', ''), people)),
            'uncertain_cast_presence': list(unresolved_opening) if phase in ('start', 'middle') else [],
            "allowed_counts": allowed, "visible_names": names,
            "people": people, "objects": {prop['name']: prop['description']} if prop else {}}


def review_passed(take: dict | None) -> bool:
    review = (take or {}).get("review") or {}
    return review.get("version") == director.REVIEW_VERSION and review.get("status") == "passed" and review_outcome(review) == 'passed'


def current_take(shot: dict, kind: str) -> dict:
    return next((t for t in (shot.get("takes") or {}).get(kind, []) if t["name"] == shot.get(kind)), {})


def starting_cast(project: dict, shot: dict) -> tuple[bool, str]:
    names = shot.get("start_cast")
    if names is None:
        return shot.get("lead", True), others_in(project, shot)
    names = _merge_cast_names(project, names)
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


def linked_cast_direction(project: dict, shot: dict, previous: dict) -> str:
    """Describe only the visible cast while preserving the previous performance's identity."""
    requirements = review_requirements(project, shot, 'start')
    people = requirements['people']
    # Legacy shots may not have a planned roster. Fall back to the same visible
    # cast inference used by the frame, not every character in the film.
    if shot.get('start_cast') is None:
        lead, others = starting_cast(project, shot)
        lead_key = _cast_identity_key(project, director.lead_name(project.get('cast', '')) or 'Lead')
        people = {name: description for name, description in people.items()
                  if (_cast_identity_key(project, name) == lead_key and lead)
                  or (_cast_identity_key(project, name) != lead_key and
                      re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', others, re.I))}
    established = {_cast_identity_key(project, name) for name in (previous.get('end_cast') or [])}
    lead_key = _cast_identity_key(project, director.lead_name(project.get('cast', '')) or 'Lead')
    directions = []
    for name, description in people.items():
        key = _cast_identity_key(project, name)
        detail = description.strip() if isinstance(description, str) else ''
        if key == lead_key:
            identity = lead_identity(project)
            if identity and identity.casefold() not in detail.casefold():
                detail = ', '.join(part for part in (detail, identity) if part)
        if key in established:
            count = director.roster_entry_count(name, detail)
            subject = 'person' if count == 1 else 'group'
            text = f'{name}, the same {subject} already in Picture 1'
            if detail and detail.casefold() != name.casefold():
                text += ', ' + detail
        else:
            text = f'{name} ({detail})' if detail and detail.casefold() != name.casefold() else name
        directions.append(text)
    return '; '.join(directions)


def performing_cast(project: dict, shot: dict) -> tuple[bool, str]:
    start, end = shot.get('start_cast'), shot.get('end_cast')
    if start is None or end is None:
        return shot.get('lead', True), others_in(project, shot)
    names = _merge_cast_names(project, start, end)
    return starting_cast(project, {**shot, 'start_cast': names})


def visible_character_names(project: dict, shot: dict) -> list[str]:
    """Canonical named supporting characters visible at the start of a shot."""
    people = cast_list(project)
    _, visible = starting_cast(project, shot)
    entries = [entry.strip().casefold() for entry in visible.split(';') if entry.strip()]
    return [name for name, description in people.items()
            if director.roster_entry_count(name, description) == 1
            and any(entry == name.casefold() or entry.startswith(name.casefold() + ' (') for entry in entries)]


def recurring_character_names(project: dict) -> list[str]:
    """Only make automatic portraits for individual characters used in multiple shots."""
    from collections import Counter
    def performers(shot):
        _, others = performing_cast(project, shot)
        people = cast_list(project)
        entries = [entry.strip().casefold() for entry in others.split(';') if entry.strip()]
        return [name for name, description in people.items()
                if director.roster_entry_count(name, description) == 1
                and any(entry == name.casefold() or entry.startswith(name.casefold() + ' (') for entry in entries)]
    counts = Counter(name for shot in project.get('shots', []) for name in performers(shot))
    return [name for name in cast_list(project) if counts[name] >= 2]


def current_character_reference(project: dict, name: str) -> dict | None:
    """An uploaded reference stays authoritative; generated ones follow their design and look."""
    people = cast_list(project)
    canonical = next((key for key in people if key.casefold() == name.casefold()), None)
    if canonical is None:
        return None
    bank = project.get('character_references') or {}
    reference = next((value for key, value in bank.items() if key.casefold() == canonical.casefold()), None)
    if not isinstance(reference, dict) or not reference.get('image'):
        return None
    if reference.get('source') == 'upload':
        return reference
    review = reference.get('review') or {}
    if not draft_mode(project) and not review.get('director_review') and (
            review.get('status') in ('failed', 'needs_review', 'possible_mismatch')
            or review.get('outcome') == 'content_issue'):
        return None
    prompt = director.cast_prompt(f'{canonical}, {people[canonical]}', project.get('scene', ''), project.get('look', ''))
    legacy = director.legacy_mixed_cast_prompt(f'{canonical}, {people[canonical]}', project.get('look', ''))
    recorded = reference.get('prompt')
    return reference if reference.get('source') == 'generated' and (recorded == prompt or legacy is not None and recorded == legacy) else None


def character_reference_capacity(project: dict, shot: dict) -> int:
    """Return the supporting-character slots left after the lead and prop."""
    if shot.get('frame_source') == 'previous_end':
        return 0
    lead, _ = starting_cast(project, shot)
    # Reserve a slot for a lead whose portrait will be generated before the frame.
    used = int(bool(lead and (project.get('reference') or project.get('cast')))) + int(bool(prop_input(project, shot)))
    return max(0, 2 - used)


def character_reference_candidates(project: dict, shot: dict) -> list[str]:
    """Bound automatically cast identities by the opening-frame picture budget."""
    return visible_character_names(project, shot)[:character_reference_capacity(project, shot)]


def selected_character_references(project: dict, shot: dict) -> list[dict]:
    """Select visible named portraits within the two auxiliary picture slots.

    Lead and prop take precedence; linked shots can use one returning-person portrait.
    """
    if shot.get('frame_source') == 'previous_end':
        return linked_returning_reference(project, shot)
    result = []
    capacity = character_reference_capacity(project, shot)
    for name in visible_character_names(project, shot):
        reference = current_character_reference(project, name)
        if reference and len(result) < capacity:
            result.append({'name': name, 'image': reference['image']})
    return result


def linked_returning_reference(project: dict, shot: dict) -> list[dict]:
    """Use one identity portrait only when a known person is absent from the previous ending."""
    if project.get('frame_backend', 'qwen') != 'qwen':
        return []
    index = next((i for i, item in enumerate(project.get('shots', [])) if item.get('id') == shot.get('id')), -1)
    if index <= 0:
        return []
    prior = project['shots'][index - 1].get('end_cast')
    start = shot.get('start_cast')
    if not isinstance(prior, list) or not isinstance(start, list):
        return []
    prior_keys = {_cast_identity_key(project, name) for name in prior if isinstance(name, str)}
    opening = {_cast_identity_key(project, name) for name in start if isinstance(name, str)}
    opening.update(_cast_identity_key(project, name) for name in shot.get('cast_roster_unresolved', []) if isinstance(name, str))
    for name, description in cast_list(project).items():
        key = _cast_identity_key(project, name)
        if key not in opening or key in prior_keys or director.roster_entry_count(name, description) != 1:
            continue
        staging = shot.get('start_frame') or ''
        escaped = re.escape(name)
        if (re.search(r'(?<!\w)' + escaped + r'\s+(?:is\s+)?(?:offscreen|off-screen|not visible|absent|outside the frame)\b', staging, re.I)
                or re.search(r'\bwithout\s+' + escaped + r'(?!\w)', staging, re.I)):
            continue
        reference = current_character_reference(project, name)
        if reference:
            return [{'name': name, 'image': reference['image']}]
    return []


def returning_character_references(project: dict, shot: dict) -> list[dict]:
    """Portraits for known individuals entering after the opening frame."""
    start, end = shot.get('start_cast'), shot.get('end_cast')
    if not isinstance(start, list) or not isinstance(end, list):
        return []
    present = {_cast_identity_key(project, name) for name in start if isinstance(name, str)}
    arriving = {_cast_identity_key(project, name) for name in end if isinstance(name, str)} - present
    result = []
    for name, description in cast_list(project).items():
        if _cast_identity_key(project, name) not in arriving or director.roster_entry_count(name, description) != 1:
            continue
        reference = current_character_reference(project, name)
        if reference:
            result.append({'name': name, 'image': reference['image']})
        if len(result) == 2:
            break
    return result


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
    state = shot_states(project, shot)[0]
    visible_lead, visible_others = starting_cast(project, shot)
    visible_state = {k: state[k] for k in shot.get("start_checks", state) if k in state}
    character_refs = selected_character_references(project, shot)
    return {"version": 4, "action": shot.get("action", ""), "start_frame": shot.get("start_frame", ""),
            **anchor,
            **({'character_references': character_refs} if character_refs else {}),
            **({'cast_roster_unresolved': list(shot['cast_roster_unresolved'])}
               if shot.get('cast_roster_unresolved') else {}),
            "shot_size": shot.get("shot_size"), "camera_move": shot.get("camera_move"),
            "lead": visible_lead, "others": visible_others,
            "cast": project.get("cast", "") if visible_lead else "",
            "continuity": project.get("continuity", ""), "design": state_design(project),
            "prop": prop_input(project, shot), "image_quality": project.get("image_quality", "fast"),
            "state_before": visible_state, "start_cast": shot.get("start_cast"),
            "start_checks": shot.get("start_checks", []), **world_of(project)}


def visual_inputs_match(recorded: dict | None, current: dict) -> bool:
    """A portrait added later does not retroactively alter an existing take."""
    if not isinstance(recorded, dict):
        return False
    if 'character_references' not in recorded:
        current = {key: value for key, value in current.items() if key != 'character_references'}
    return recorded == current


def video_inputs(project: dict[str, Any], shot: dict[str, Any]) -> dict[str, Any]:
    index = next((i for i, s in enumerate(project["shots"]) if s["id"] == shot["id"]), 0)
    previous_video = project["shots"][index - 1].get("video") if index and shot.get("transition") == "continue" else None
    before, after = shot_states(project, shot)
    keys = set(shot.get("start_checks", before)) | set(shot.get("end_checks", after)) | set(shot.get("state_changes", {}))
    visual = visual_inputs(project, shot)
    frame = current_take(shot, 'keyframe')
    if frame and 'character_references' not in ((frame.get('recipe') or {}).get('visual') or {}):
        visual.pop('character_references', None)
    end_snapshot = (shot.get('endframe') or {}).get('of') or {}
    end_refs = ({'end_character_references': returning_character_references(project, shot)}
                if shot.get('guide_end') and 'end_character_references' in end_snapshot else {})
    return {**visual, **end_refs, "end_state": shot.get("end_state", ""),
            "state_before": {k: before[k] for k in keys if k in before}, "state_after": {k: after[k] for k in keys if k in after},
            **({"end_frame": (shot.get("endframe") or {}).get("name")} if shot.get("guide_end") else {}),
            "end_cast": shot.get("end_cast"), "end_checks": shot.get("end_checks", []),
            "seconds": shot.get("seconds"), "sound": shot.get("sound", ""), "line": shot.get("line", ""),
            "transition": shot.get("transition", "cut"), "keyframe": shot.get("keyframe"), "previous_video": previous_video,
            "guide_end": shot.get("guide_end", False), "end_prop": prop_input(project, shot, "end")}


def ending_inputs(project: dict, shot: dict) -> dict:
    inputs = {**video_inputs(project, shot), "start": shot.get("keyframe")}
    inputs.pop("end_frame", None)
    inputs.pop("end_character_references", None)
    references = returning_character_references(project, shot)
    if references:
        inputs["end_character_references"] = references
    return inputs


def video_stale(project: dict[str, Any], shot: dict[str, Any]) -> bool:
    take = next((t for t in (shot.get("takes") or {}).get("video", []) if t["name"] == shot.get("video")), {})
    return bool(shot.get("video") and (take.get("of") != video_inputs(project, shot)))


def asset_status(project: dict[str, Any]) -> dict[str, Any]:
    return {s["id"]: {"story": story_stale(project, s), "frame": frame_stale(project, s),
                      "video": video_stale(project, s), "sketch": sketch_stale(project, s),
                      "start_lead": starting_cast(project, s)[0],
                      "review": bool(s.get("video") and not review_passed(current_take(s, "video"))),
                      "state_before": shot_states(project, s)[0], "state_after": shot_states(project, s)[1]} for s in project["shots"]}


def sketch_visual_inputs(project: dict[str, Any], shot: dict[str, Any]) -> dict:
    """A text-drawn storyboard does not use supporting-character portraits."""
    result = visual_inputs(project, shot)
    result.pop('character_references', None)
    return result


def sketch_stale(project: dict[str, Any], shot: dict[str, Any]) -> bool:
    take = next((t for t in shot.get("sketches", []) if t["name"] == shot.get("sketch")), {})
    snapshot = take.get('of') or {}
    portrait = snapshot.get('portrait_identity')
    current_portrait = {'reference': project.get('reference'), 'description': lead_identity(project)}
    return bool(shot.get("sketch") and (snapshot.get("visual") != sketch_visual_inputs(project, shot)
                or portrait is not None and portrait != current_portrait
                or take.get("source_frame") and take["source_frame"] != shot.get("keyframe")))


def sketch_of(shot: dict[str, Any], plate: str | None, reference: str | None,
              project: dict[str, Any] | None = None) -> dict[str, Any]:
    """What a storyboard drawing depends on: if any of it changes, the drawing is redrawn before the next frame."""
    return {"action": shot.get("action", ""), "shot_size": shot.get("shot_size"), "camera_move": shot.get("camera_move"),
            "lead": shot.get("lead", True) is not False,
            "others": shot.get("others", ""), "visual": sketch_visual_inputs(project, shot) if project else None}


def frame_stale(project: dict[str, Any], shot: dict[str, Any]) -> bool:
    """The shot's frame no longer matches it (mirrors staleness() in the web app): a new lead, world, action or
    framing. Frames from before a field was recorded aren't flagged for it."""
    take = next((t for t in (shot.get("takes") or {}).get("keyframe", []) if t["name"] == shot.get("keyframe")), None)
    r = (take or {}).get("recipe") or {}
    if not shot.get("keyframe") or r.get("kind") != "shot":
        return False
    drawing = next((t for t in shot.get("sketches", []) if t["name"] == shot.get("sketch")), {})
    traced_current = drawing.get("source_frame") == shot.get("keyframe")
    if r.get("composition_version") != 2 or not visual_inputs_match(r.get("visual"), visual_inputs(project, shot)) or (
            r.get('composition_source') != 'cast_portraits' and r.get("sketch") != shot.get("sketch") and not traced_current):
        return True
    lead = starting_cast(project, shot)[0] and project.get("reference")
    world_changed = (r.get('composition_source') != 'cast_portraits'
                     and not (r.get('world_optional') is True and r.get('world') is None)
                     and r.get("world") != current_plate(project))
    return bool((lead and r.get("lead") != project.get("reference")) or world_changed
                or ("action" in r and r["action"] != shot.get("action", ""))
                or ("shot_size" in r and (r["shot_size"] != shot.get("shot_size")
                                          or r.get("camera_move") != shot.get("camera_move"))))


def current_plate(project: dict[str, Any]) -> str | None:
    """The world plate, but only if it was painted from today's world, look and aspect."""
    unit = project.get("world") or {}
    take = next((t for t in unit.get("takes", []) if t["name"] == unit.get("plate")), None)
    if not take:
        return None
    recorded = take.get('of') or {}
    # Earlier takes used the original scene directly and have no extraction.
    expected = world_plate_inputs(project) if 'environment' in recorded else world_of(project)
    return unit.get("plate") if recorded == expected else None


def sync_dialogue_review(shot: dict[str, Any]) -> None:
    """Expose only evidence for the selected take and current line."""
    quality = shot.setdefault('quality', {})
    take = next((item for item in shot.get('takes', {}).get('video', []) if item['name'] == shot.get('video')), None)
    result = (take or {}).get('dialogue_review')
    if result and result.get('line_hash') == speech.line_fingerprint(shot.get('line') or ''):
        quality['dialogue'] = copy.deepcopy(result)
    else:
        quality.pop('dialogue', None)


def add_take(shot: dict[str, Any], kind: str, name: str, **info: Any) -> None:
    """Record a new keyframe or video take and make it current."""
    takes = shot.setdefault("takes", {}).setdefault(kind, [])
    existing = next((take for take in takes if take['name'] == name), None)
    if existing is not None:
        existing.update(info)
    else:
        takes.append({"name": name, **info})
    if kind == "keyframe":
        shot["keyframe"], shot["video"] = name, None
    else:
        shot["video"] = name
    sync_dialogue_review(shot)


def select_take(shot: dict[str, Any], kind: str, name: str, allow_unreviewed: bool = False) -> None:
    takes = shot.get("takes", {})
    match = next((t for t in takes.get(kind, []) if t["name"] == name), None)
    if not match:
        raise KeyError(f"no {kind} take {name}")
    if match.get("review", {}).get("status") == "needs_review" and not allow_unreviewed:
        raise RuntimeError("This candidate failed visual review. Inspect its findings and regenerate it before using it.")
    if kind == "video":
        shot["video"] = name
        shot["keyframe"] = match.get("keyframe") or shot["keyframe"]
    else:
        # bring back the newest video that was rendered from this keyframe, if any
        shot["keyframe"] = name
        shot["video"] = next((t["name"] for t in reversed(takes.get("video", []))
                              if t.get("keyframe") == name), None)
    sync_dialogue_review(shot)


def ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if not found:
        raise RuntimeError("ffmpeg was not found on PATH; it is needed to stitch the film")
    return found


def drawtext_font() -> str:
    """Use the bundled font rather than platform-specific font discovery."""
    path = (ROOT / 'custom_nodes/comfyui-open-cinema/fonts/Manrope-Variable.ttf').as_posix()
    escaped = path.replace('\\', '\\\\').replace(':', '\\:').replace("'", "'\\''")
    return "fontfile='" + escaped + "'"


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
        self._node_observations = {}
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
        project.setdefault("review_policy", "draft")
        project.setdefault("dialogue_mode", "auto")
        project.setdefault("image_backend", "hidream")
        project.setdefault("frame_backend", "qwen")
        for shot in project["shots"]:  # projects from before takes existed
            shot.setdefault("beat_source", beat_text(project, shot))
            if "takes" not in shot:
                shot["takes"] = {"keyframe": [{"name": shot["keyframe"]}] if shot.get("keyframe") else [],
                                 "video": [{"name": shot["video"], "keyframe": shot.get("keyframe")}]
                                 if shot.get("video") else []}
        project["asset_status"] = asset_status(project)
        project["continuity_status"] = plan_status(project)
        project["continuity_fixes"] = continuity_auto_fixes(project)
        project["film_review"] = film_review(project)
        project["world_plate_current"] = bool(current_plate(project))
        return project

    def choose_take(self, project_id: str, shot_id: str, kind: str, name: str) -> dict[str, Any]:
        with self.lock:
            project = self.load(project_id)
            select_take(self._shot(project, shot_id), kind, name, allow_unreviewed=draft_mode(project))
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
            project.pop("film_review", None)
            project.pop("world_plate_current", None)
            temporary.write_text(json.dumps(project, indent=2), encoding="utf-8")
            temporary.replace(folder / "project.json")
        return {**project, "film_now": film_inputs(project), "asset_status": asset_status(project), "continuity_status": plan_status(project),
                "continuity_fixes": continuity_auto_fixes(project), "film_review": film_review(project),
                "world_plate_current": bool(current_plate(project))}

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
        mode = data.get("ai_mode", "fast")
        if mode not in ("normal", "fast"):
            raise ValueError("Choose Normal or Fast AI mode")
        defaults = {"image_backend": "klein" if mode == "fast" else "hidream",
                    "frame_backend": "klein" if mode == "fast" else "qwen",
                    "image_quality": "fast" if mode == "fast" else "detailed"}
        data = {**defaults, **data}
        if data.get("review_policy", "draft") not in ("draft", "strict"):
            raise ValueError("Choose draft or strict review policy")
        if data.get("dialogue_mode", "auto") not in director.DIALOGUE_MODES:
            raise ValueError("Choose a valid dialogue direction")
        if data.get("image_backend", "hidream") not in ("hidream", "klein"):
            raise ValueError("Choose a supported image backend")
        if data.get("frame_backend", "qwen") not in ("qwen", "klein"):
            raise ValueError("Choose a supported frame editor")
        project = {"id": uuid.uuid4().hex[:10], "title": data.get("title") or "Untitled film",
                   "review_policy": data.get("review_policy", "draft"),
                   "dialogue_mode": data.get("dialogue_mode", "auto"),
                   "image_backend": data.get("image_backend", "hidream"),
                   "frame_backend": data.get("frame_backend", "qwen"),
                   "scene": data.get("scene", ""), "look": data.get("look", "Anamorphic blockbuster"),
                   "aspect": data.get("aspect", "16:9"), "continuity": data.get("continuity", ""),
                   "ai_mode": mode, "image_quality": data["image_quality"],
                   "cast": data.get("cast", ""),
                   "reference": None, "film": None, "created": time.time(),
                   "shots": [new_shot(**s) for s in data.get("shots", [])] or [new_shot()]}
        return self.save(project)

    def update(self, project_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Apply edits from the UI; generated media stays owned by the server."""
        if "ai_mode" in data and data["ai_mode"] not in ("normal", "fast"):
            raise ValueError("Choose Normal or Fast AI mode")
        if "review_policy" in data and data["review_policy"] not in ("draft", "strict"):
            raise ValueError("Choose draft or strict review policy")
        if "dialogue_mode" in data and data["dialogue_mode"] not in director.DIALOGUE_MODES:
            raise ValueError("Choose a valid dialogue direction")
        if "image_backend" in data and data["image_backend"] not in ("hidream", "klein"):
            raise ValueError("Choose a supported image backend")
        if "frame_backend" in data and data["frame_backend"] not in ("qwen", "klein"):
            raise ValueError("Choose a supported frame editor")
        with self.lock:
            project = self.load(project_id)
            if "ai_mode" in data and data["ai_mode"] != project.get("ai_mode", "normal"):
                fast = data["ai_mode"] == "fast"
                data = {**data, "image_backend": "klein" if fast else "hidream",
                        "frame_backend": "klein" if fast else "qwen",
                        "image_quality": "fast" if fast else "detailed"}
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
                        "logline", "palette", "auto_render", "characters", "image_quality", "image_backend", "frame_backend", "ai_mode", "review_policy", "dialogue_mode"):
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
                    sync_dialogue_review(shot)
                    shots.append(shot)
                project["shots"] = shots
            if data.get("accept_continuity") and current_revision and project.get("continuity_plan"):
                project["continuity_plan"].update(of=continuity_inputs(project), acknowledged=True)
                for shot in project["shots"]:
                    shot.pop("cast_roster_unresolved", None)  # Director explicitly accepted the roster.
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

    def set_character_reference(self, project_id: str, name: str, filename: str, data: bytes) -> dict[str, Any]:
        """Store a director-supplied portrait without overwriting any previous file."""
        if not data:
            raise ValueError('Choose an image for this character')
        suffix = Path(filename).suffix.lower()
        if suffix not in {'.png', '.jpg', '.jpeg', '.webp'}:
            raise ValueError('Choose a PNG, JPEG or WebP image')
        with self.lock:
            project = self.load(project_id)
            people = cast_list(project)
            canonical = next((key for key in people if key.casefold() == name.strip().casefold()), None)
            if not canonical:
                raise ValueError('Add this named character to Other characters first')
            if director.roster_entry_count(canonical, people[canonical]) != 1:
                raise ValueError('Character references are for individuals, not groups')
            target = self.path(project_id) / f'character_{uuid.uuid4().hex[:10]}{suffix}'
            target.write_bytes(data)
            bank = project.setdefault('character_references', {})
            previous = next((key for key in bank if key.casefold() == canonical.casefold()), None)
            if previous and previous != canonical:
                bank.pop(previous)
            bank[canonical] = {'image': target.name, 'source': 'upload', 'description': people[canonical]}
            return self.save(project)

    def queue_character_reference(self, project_id: str, name: str, automatic: bool = False,
                                  priority: float | None = None) -> dict:
        project = self.load(project_id)
        people = cast_list(project)
        canonical = next((key for key in people if key.casefold() == name.strip().casefold()), None)
        if not canonical or director.roster_entry_count(canonical, people[canonical]) != 1:
            raise ValueError('Choose a named individual from Other characters')
        return self.enqueue('character_reference', project_id, label=f'Casting {canonical}',
                            character=canonical, automatic=automatic, _priority=priority)

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
            snapshot.pop('end_character_references', None)  # Uploaded frames do not use generated portraits.
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
            observations = getattr(self, '_node_observations', None)
            if observations is None:
                observations = self._node_observations = {}
            if message.get('type') == 'studio_socket_disconnected':
                # A missing node transition makes the open span unknowable.
                observations.clear()
                return
            if message.get("type") == "studio_submitted":
                for running in self.jobs:
                    if running["state"] == "running":
                        running["prompt_id"] = prompt
                        running.pop("progress", None)
                        running.pop("node", None)
                        classes = {str(node): kind for node, kind in data.get('node_classes', {}).items()
                                   if isinstance(kind, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', kind)}
                        observations.clear()
                        observations[prompt] = {'classes': classes, 'active': None}
            job = next((j for j in self.jobs if j.get("prompt_id") == prompt and j["state"] == "running"), None)
            if job:
                if message.get("type") == "progress":
                    job["progress"] = {"value": data.get("value"), "max": data.get("max")}
                if message.get("type") == "executing":
                    job["node"] = data.get("node")
                if message.get('type') in ('executing', 'execution_success', 'execution_error', 'execution_interrupted'):
                    observation = observations.get(prompt)
                    if observation:
                        now = time.monotonic()
                        active = observation.get('active')
                        if active:
                            elapsed = max(0.0, now - active[1])
                            timings = job.setdefault('timing', {}).setdefault('observed_nodes', {})
                            node_timing = timings.setdefault(active[0], {'seconds': 0.0, 'spans': 0})
                            node_timing['seconds'] += elapsed
                            node_timing['spans'] += 1
                        node = data.get('node') if message.get('type') == 'executing' else None
                        kind = observation['classes'].get(str(node)) if node is not None else None
                        observation['active'] = (kind, now) if kind else None
                        if message.get('type') != 'executing' or node is None:
                            observations.pop(prompt, None)
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
            extra = {k: old[k] for k in ("mode", "target", "count", "redraw", "prop", "value", "character", "candidate_kind",
                     "render_after", "draw_after", "redo_keyframe", "reroll", "candidate_name", "reuse_candidate", "review_policy") if k in old}
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
        if kind == 'review_frame' and failed.get('review_policy') == 'draft':
            return  # a failed deferred check must not stop a playable draft
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
        rank = {"sketch": 0, "keyframe": 1, "repair_frame": 1, "review_frame": 1, "video": 2, "review": 3}
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
                _priority: float | None = None, **extra: Any) -> dict[str, Any]:
        queued_project = self.load(project_id)
        mode = queued_project.get("ai_mode", "normal")
        if hasattr(self, "setup"):
            self.setup.require(kind, extra.get("target"), mode=mode,
                               image_backend=queued_project.get("image_backend", "hidream"),
                               frame_backend=queued_project.get("frame_backend", "qwen"))
        job = {"id": uuid.uuid4().hex[:8], "kind": kind, "project": project_id, "shot": shot_id,
               "label": label or kind, "state": "queued", "error": None, "elapsed": 0.0, "created": time.time(),
               **extra, "ai_mode": mode, "image_backend": queued_project.get("image_backend", "hidream"),
               "frame_backend": queued_project.get("frame_backend", "qwen"),
               "review_policy": extra.get('review_policy', queued_project.get("review_policy", "draft")), "base_label": label or kind}
        with self.lock:
            existing = next((j for j in self.jobs if j["project"] == project_id and j.get("shot") == shot_id and
                             j["kind"] == kind and j["state"] in ("queued", "running") and
                             (kind != 'review_frame' or j.get('review_policy') == job['review_policy']) and
                             all(j.get(k) == extra.get(k) for k in ("mode", "target", "prop", "value", "character", "candidate_name"))), None)
            if existing:
                return existing
            self.jobs.append(job)
            self.jobs = self.jobs[-200:]
            self._save_jobs()
        priority = _priority if _priority is not None else (2 if kind in ('review', 'review_frame') and job['review_policy'] == 'strict' else PRIORITY.get(kind, 2))
        self.queue.put((priority, next(self.order), job))
        return job

    def _queue_followup(self, kind: str, project_id: str, shot_id: str | None = None, label: str = "", **extra):
        """Keep completed work and expose a retryable downstream step when setup is incomplete."""
        try:
            return self.enqueue(kind, project_id, shot_id, label, **extra)
        except RuntimeError as error:
            return self._blocked_followup(kind, project_id, shot_id, label, str(error), **extra)

    def _blocked_followup(self, kind: str, project_id: str, shot_id: str | None, label: str, reason: str, **extra):
        project = self.load(project_id)
        with self.lock:
            existing = next((j for j in self.jobs if j['project'] == project_id and j.get('shot') == shot_id and
                             j['kind'] == kind and j['state'] == 'blocked' and j.get('setup_blocked') and
                             all(j.get(k) == extra.get(k) for k in ('mode','target','prop','value','character'))), None)
            if existing:
                existing['error'] = reason
                self._save_jobs()
                return existing
            job = {'id':uuid.uuid4().hex[:8], 'kind':kind, 'project':project_id, 'shot':shot_id,
                   'label':label or kind, 'base_label':label or kind, 'state':'blocked', 'error':reason,
                   'elapsed':0.0, 'created':time.time(), 'setup_blocked':True,
                   'ai_mode':project.get('ai_mode','normal'), 'image_backend':project.get('image_backend','hidream'),
                   'review_policy':project.get('review_policy','draft'), **extra}
            self.jobs.append(job)
            self.jobs = self.jobs[-200:]
            self._save_jobs()
            return job

    def _run_resume_film(self, job: dict[str, Any], tick) -> None:
        self.queue_film(job['project'])

    def _run_resume_board(self, job: dict[str, Any], tick) -> None:
        self.queue_sketches(job['project'])

    def queue_film(self, project_id: str, redo_keyframes: bool = False,
                   only: set[str] | None = None, render_started_at: float | None = None) -> list[dict[str, Any]]:
        """Everything missing or out of date, in dependency order (`only`: just these shots).

        Drafts render the first shot early, then batch remaining images and
        videos to limit model swaps. Strict mode keeps normal review ordering.
        Paused shots are skipped, a step
        already waiting in the queue isn't queued again, and the film is cut only
        when every shot will have a video.
        """
        render_started_at = time.time() if render_started_at is None else render_started_at
        if hasattr(self, "setup"):
            setup_project = self.load(project_id)
            self.setup.require("film", mode=setup_project.get("ai_mode", "normal"),
                               image_backend=setup_project.get("image_backend", "hidream"),
                               frame_backend=setup_project.get("frame_backend", "qwen"))
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
                pending.setdefault('render_started_at', render_started_at)
                return [pending]
            return [self.enqueue("plan_continuity", project_id, label="Planning continuity", render_after=True,
                                 render_started_at=render_started_at)]
        if not plan_usable(project):
            raise RuntimeError("Review scene continuity on Story: replan it, or confirm your edited states before rendering.")
        with self.lock:
            cleared_setup = False
            for prior in self.jobs:
                if prior['project'] == project_id and prior['state'] == 'blocked' and prior.get('setup_blocked'):
                    prior.update(state='cancelled', error='Resumed with current setup')
                    cleared_setup = True
            if cleared_setup:
                self._save_jobs()
            waiting = {(j["kind"], j["shot"]) for j in self.jobs if j["project"] == project_id
                       and j["state"] in ("queued", "running")}
            waiting_frames = {(j['shot'], j.get('review_policy', 'draft')) for j in self.jobs
                              if j['project'] == project_id and j['kind'] == 'review_frame'
                              and j['state'] in ('queued', 'running')}
        held = set()  # paused shots, and one-take shots that start from one
        for index, shot in enumerate(project["shots"]):
            if shot.get("paused") or ((shot.get("transition") == "continue" or shot.get("frame_source") == "previous_end") and index > 0
                                      and project["shots"][index - 1]["id"] in held):
                held.add(shot["id"])
        wanted = lambda shot: shot["id"] not in held and (only is None or shot["id"] in only)  # noqa: E731
        # For a fresh full draft, make the first shot playable before preparing
        # the rest of the film. Restrict this to the first shot (which has no
        # predecessor) and never overtake an already queued dependency.
        first = project['shots'][0] if project['shots'] else None
        preview_first = bool(draft_mode(project) and only is None and first and wanted(first)
            and (redo_keyframes or not first.get('video') or video_stale(project, first) or frame_stale(project, first))
            and not any((kind, first['id']) in waiting for kind in ('sketch', 'keyframe', 'video')))
        # A non-wide opening frame uses the storyboard and cast, not the world
        # image. Let that draft play before painting the shared plate, then
        # retain the plate job for later shots and other film assets.
        defer_world = bool(preview_first and first.get('shot_size') not in director.WIDE_SIZES
                           and first.get('frame_source') != 'previous_end'
                           and not current_plate(project) and ('world', None) not in waiting)
        jobs = []
        if project.get("cast", "").strip() and (not project.get("reference") or cast_stale(project)) and ("cast", None) not in waiting:
            jobs.append(self.enqueue("cast", project_id, None, "Casting"))
        elif project.get("reference") and not lead_identity(project) and ("describe_lead", None) not in waiting:
            jobs.append(self.enqueue("describe_lead", project_id, None, "Describing the lead's face"))
        if not defer_world and not current_plate(project) and ("world", None) not in waiting:
            jobs.append(self.enqueue("world", project_id, None, "Painting the world", auto=True))
        # Generate one reusable reference per recurring named individual. Keep
        # the lead and explicit prop slots authoritative, and never cast crowds.
        first_visible = set(character_reference_candidates(project, first)) if preview_first else set()
        for name in recurring_character_names(project):
            if current_character_reference(project, name):
                continue
            useful = any(wanted(shot) and name in character_reference_candidates(project, shot)
                         for shot in project['shots'])
            if useful:
                jobs.append(self.queue_character_reference(project_id, name, automatic=True,
                            priority=1 if name in first_visible else 1.5 if preview_first else 1))
        jobs.extend(self.queue_sketches(project_id, [s["id"] for s in project["shots"] if wanted(s)],
                                        first_preview=first['id'] if preview_first else None))
        # Resume a deferred image check after interruption without rebuilding the image.
        frame_review_policy = 'draft' if draft_mode(project) else 'strict'
        for index, shot in enumerate(project["shots"]):
            take = current_take(shot, "keyframe")
            if wanted(shot) and take and review_pending(take) and (shot['id'], frame_review_policy) not in waiting_frames:
                jobs.append(self.enqueue("review_frame", project_id, shot["id"], f"Checking frame {index + 1}",
                                         candidate_name=take["name"], review_policy=frame_review_policy))
        if any(s.get("frame_source") == "previous_end" for s in project["shots"]):
            # A later frame needs the preceding completed performance. Preserve dependency order
            # instead of batching all image work ahead of all animation.
            upstream_changed = False
            for index, shot in enumerate(project["shots"]):
                dependent = shot.get("frame_source") == "previous_end" or shot.get("transition") == "continue"
                redo = wanted(shot) and (redo_keyframes or not shot.get("video") or video_stale(project, shot)
                       or frame_stale(project, shot) or upstream_changed and dependent)
                if redo and ("video", shot["id"]) not in waiting:
                    jobs.append(self.enqueue("video", project_id, shot["id"], f"Shot {index+1}", redo_keyframe=redo_keyframes,
                                             render_started_at=render_started_at,
                                             defer_world=bool(defer_world and index == 0),
                                             _priority=1.25 if preview_first and index == 0 else None))
                elif wanted(shot) and shot.get("video") and (not take_usable(project, current_take(shot, "video")) or review_pending(current_take(shot, 'video'))) and ("review",shot["id"]) not in waiting:
                    jobs.append(self.enqueue("review",project_id,shot["id"],f"Review shot {index+1}", candidate_name=shot['video']))
                upstream_changed = redo
            coming = {j["shot"] for j in self.jobs if j["project"] == project_id and j["kind"] == "video" and j["state"] in ("queued","running")}
            if not held and all(s.get("video") or s["id"] in coming for s in project["shots"]) and ("stitch",None) not in waiting:
                jobs.append(self.enqueue("stitch",project_id,None,"Final cut"))
            if defer_world:
                jobs.append(self.enqueue("world", project_id, None, "Painting the world", auto=True, _priority=1.5))
            return jobs
        for index, shot in enumerate(project["shots"]):
            continues = shot["transition"] == "continue" and index > 0
            if not continues and wanted(shot) and ("keyframe", shot["id"]) not in waiting and \
                    (redo_keyframes or not shot.get("keyframe") or frame_stale(project, shot)):
                jobs.append(self.enqueue("keyframe", project_id, shot["id"], f"Keyframe {index + 1}", reuse_candidate=not redo_keyframes,
                                         defer_world=bool(defer_world and index == 0),
                                         _priority=1.25 if preview_first and index == 0 else None))
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
                jobs.append(self.enqueue("video", project_id, shot["id"], f"Shot {index + 1}",
                                         render_started_at=render_started_at,
                                         defer_world=bool(defer_world and index == 0),
                                         _priority=1.4 if preview_first and index == 0 else None))
            elif wanted(shot) and shot.get("video") and (not take_usable(project, current_take(shot, "video")) or review_pending(current_take(shot, 'video'))) and ("review", shot["id"]) not in waiting:
                jobs.append(self.enqueue("review", project_id, shot["id"], f"Review shot {index + 1}", candidate_name=shot['video']))
            previous_redone = redo
        with self.lock:
            coming = {j["shot"] for j in self.jobs if j["project"] == project_id and j["kind"] == "video"
                      and j["state"] in ("queued", "running")}
        if not held and all(s.get("video") or s["id"] in coming for s in project["shots"]) and \
                ("stitch", None) not in waiting:
            jobs.append(self.enqueue("stitch", project_id, None, "Final cut"))
        if defer_world:
            jobs.append(self.enqueue("world", project_id, None, "Painting the world", auto=True, _priority=1.5))
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
            jobs = [dict(j) for j in self.jobs if project_id in (None, j["project"])]
        # Reflect the real global priority queue, not insertion order or the
        # number of jobs in this film. Running work is displayed separately.
        if hasattr(self, 'queue'):
            with self.queue.mutex:
                waiting = sorted((entry for entry in self.queue.queue if entry[2].get('state') == 'queued'),
                                 key=lambda entry: (entry[0], entry[1]))
                positions = {entry[2]['id']: index + 1 for index, entry in enumerate(waiting)}
            for job in jobs:
                if job['state'] == 'queued' and job['id'] in positions:
                    job['queue_position'] = positions[job['id']]
                    prerequisite_kinds = {'keyframe': ('sketch',), 'video': ('keyframe', 'sketch')}.get(job['kind'], ())
                    prerequisites = [other for other in jobs if other['project'] == job['project'] and
                        other.get('shot') == job.get('shot') and other['kind'] in prerequisite_kinds and
                        other['state'] in ('running','queued') and
                        (other['state'] == 'running' or positions.get(other['id'], float('inf')) < positions[job['id']])]
                    if prerequisites:
                        first = min(prerequisites, key=lambda other: -1 if other['state']=='running' else positions[other['id']])
                        job['waiting_for'] = first.get('base_label') or first['label']
        return jobs

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
                with graphs.using_writer(job.get("ai_mode", "normal")), using_review_policy(job.get("review_policy")):
                    getattr(self, f"_run_{job['kind']}")(job, tick)
                with self.lock:
                    if job.get('stopped'):
                        job['state'], job['error'] = 'cancelled', 'Stopped by you'
                    else:
                        job['state'] = 'done'
            except Exception as error:  # surface every failure in the UI
                if job.get("stopped"):  # its shot was paused while it ran
                    job["state"], job["error"] = "cancelled", "Stopped by you"
                    job["elapsed"] = time.monotonic() - started
                    self._save_jobs()
                    if timing is not None:
                        timing.metrics = None
                    with self.lock:
                        getattr(self, '_node_observations', {}).pop(job.get('prompt_id'), None)
                    continue
                job["state"], job["error"] = ("needs_review" if "needs review" in str(error).lower() else "failed"), str(error)
                traceback.print_exc()
                with self.lock:
                    self._block_dependents(job)
            job["elapsed"] = time.monotonic() - started
            if timing is not None:
                timing.metrics = None
            with self.lock:
                getattr(self, '_node_observations', {}).pop(job.get('prompt_id'), None)
            self._save_jobs()

    # ---------- pipeline steps ----------
    def _upload(self, project_id: str, filename: str) -> str:
        return self.comfy.upload(self.path(project_id) / filename, f"oc_{project_id}_{filename}")

    def _submit_for_job(self, graph: dict, job: dict | None = None):
        """Do not submit new GPU work after Stop/Pause takes the job lock."""
        if job is None:
            return self.comfy.submit(graph)
        with self.lock:
            if job.get('stopped'):
                raise ComfyError('interrupted')
            return self.comfy.submit(graph)

    def _run_for_job(self, graph: dict, tick, job: dict):
        """Run a saved-output graph while keeping Stop atomic with submission."""
        record = self.comfy.wait(self._submit_for_job(graph, job), on_tick=tick)
        files = [item for output in record.get('outputs', {}).values()
                 for key in ('images', 'videos', 'gifs', 'video', 'audio')
                 for item in output.get(key, [])
                 if isinstance(item, dict) and item.get('type', 'output') == 'output']
        if not files:
            raise ComfyError('Graph finished without saving any file')
        return files

    def _render_checked(self, graph: dict[str, Any], seed: int, tick, job: dict | None = None) -> tuple[list, int, dict]:
        """One explicit attempt, always retaining a candidate and its review for the director."""
        record = self.comfy.wait(self._submit_for_job(graph, job), on_tick=tick)
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

    def _text_graph(self, graph: dict, output: str, tick, job: dict | None = None) -> dict:
        record = self.comfy.wait(self._submit_for_job(graph, job), on_tick=tick, timeout=900)
        text = "".join(record.get("outputs", {}).get(output, {}).get("text", []))
        return json.loads(text)

    def _run_plan_continuity(self, job: dict, tick) -> None:
        project = self.load(job["project"])
        if any(not s.get("action", "").strip() for s in project["shots"]):
            raise RuntimeError("Write the shots before planning continuity")
        source = continuity_inputs(project)
        try:
            graph = graphs.continuity_graph(json.dumps(source), len(project["shots"]))
            try:
                plan = self._text_graph(graph, "plan", tick, job=job)
            except ComfyError as error:
                # Retry only a known malformed model-produced ledger, not
                # interruptions, transport failures, or GPU execution errors.
                if "Scene state must be an object with at most 32 named facts" not in str(error):
                    raise
                job["label"] = "Planning continuity · retrying invalid scene state"
                self._metric("continuity_retries")
                retry = graphs.continuity_graph(json.dumps(source), len(project["shots"]))
                for key in ("3", "repair"):
                    retry[key]["inputs"].update({"sampling_mode": "on", "sampling_mode.temperature": 0.4,
                        "sampling_mode.top_k": 64, "sampling_mode.top_p": 0.95, "sampling_mode.min_p": 0.05,
                        "sampling_mode.repetition_penalty": 1.05, "sampling_mode.seed": random.randrange(1, 2**31)})
                plan = self._text_graph(retry, "plan", tick, job=job)
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
            corrections = []
            for conflict in director.cast_roster_conflicts(source, plan):
                row = plan['shots'][conflict['index'] - 1]
                name = conflict['name']
                # An explicit absent state is a genuine contradiction, not an
                # invitation to invent a new state or silently change the cast.
                contradictory = any(
                    re.match(r'(?i)^' + re.escape(name) + r'\b.*\b(?:presence|location|position)\b', key)
                    and value.strip().casefold() in ('absent', 'offscreen', 'off-screen', 'none')
                    for key, value in plan['initial'].items())
                if conflict['explicit'] and not contradictory:
                    row['start_cast'].append(name)
                    corrections.append({'shot': conflict['index'], 'name': name})
                else:
                    row.setdefault('cast_roster_unresolved', []).append(name)
                    plan['issues'].append(
                        f"Shot {conflict['index']}: the opening mentions {name}, but its visible cast is uncertain; check the opening direction.")
            fresh["scene_state"] = plan["initial"]
            fresh.pop("continuity_error", None)
            fresh["continuity_plan"] = {"of": source, "design": plan["design"], "environment": plan.get("environment", []),
                                        "issues": plan["issues"], "cast_corrections": corrections, "acknowledged": False}
            fresh["continuity_rev"] = fresh.get("continuity_rev", 0) + 1
            for shot, row in zip(fresh["shots"], plan["shots"]):
                shot["state_changes"] = row["changes"]
                for key in ("start_checks", "end_checks", "start_cast", "end_cast"):
                    shot[key] = row[key]
                shot['cast_roster_unresolved'] = row.get('cast_roster_unresolved', [])
            self.save(fresh)
        if plan["issues"] and not draft_mode(fresh):
            raise RuntimeError("Continuity needs review: " + "; ".join(plan["issues"]))
        if job.get("render_after"):
            try:
                self.queue_film(project["id"], render_started_at=job.get('render_started_at'))
            except RuntimeError as error:
                self._blocked_followup('resume_film', project['id'], None, 'Resume film', str(error))
        elif job.get("draw_after"):
            try:
                self.queue_sketches(project["id"])
            except RuntimeError as error:
                self._blocked_followup('resume_board', project['id'], None, 'Resume storyboard', str(error))

    def _require_plan(self, project_id: str, tick) -> dict:
        project = self.load(project_id)
        if plan_status(project) == "missing":
            self._run_plan_continuity({"project": project_id}, tick)
            project = self.load(project_id)
        if not plan_usable(project):
            raise RuntimeError("Review scene continuity on Story before generating media")
        return project

    def _metric(self, key):
        metrics = getattr(getattr(self.comfy, '_timing', None), 'metrics', None)
        if metrics is not None:
            metrics[key] = metrics.get(key, 0) + 1

    def _checked_review(self, project, name, contracts, graph_for, tick, job=None):
        """Reuse exact evidence; malformed reviewers get one retry, never a repaint."""
        source = self.path(project['id']) / name
        digest = hashlib.sha256()
        with source.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        identity = {'content': digest.hexdigest(), 'contracts': contracts, 'look': project['look'],
                    'review_version': director.REVIEW_VERSION, 'prompt_version': director.REVIEW_PROMPT_VERSION,
                    'writer': graphs._writer_mode.get()}
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        cached = self.load(project['id']).get('review_cache', {}).get(key)
        if cached and valid_review_result(cached):
            self._metric('review_cache_hits')
            return copy.deepcopy(cached)
        graph = graph_for(self._upload(project['id'], name))
        review = None
        for attempt in range(2):
            try:
                review = (self._text_graph(graph, 'review', tick) if job is None
                          else self._text_graph(graph, 'review', tick, job=job))
                if not valid_review_result(review):
                    raise ValueError('Reviewer returned no valid result')
            except (ValueError, TypeError, ComfyError) as error:
                # Older running ComfyUI instances can still raise at the
                # observation node before the structured parser sees JSON.
                # Do not misclassify network, GPU, or other execution failures
                # as inconclusive reviews.
                if isinstance(error, ComfyError) and not re.search(
                    r'(?:Expecting .+|Extra data|Invalid control character|Unterminated string starting at):? line \d+ column \d+ \(char \d+\)',
                    str(error), re.IGNORECASE):
                    raise
                review = director.review_result([{'category':'reviewer_error', 'code':'invalid_review_output',
                    'severity':'warning', 'message':'The visual check returned incomplete evidence; the generated asset is preserved.'}], diagnostic=str(error))
            if review_outcome(review) != 'reviewer_error' or attempt:
                break
            self._metric('reviewer_retries')
            # A fresh seed avoids reusing malformed ComfyUI text outputs and
            # offers a new response when extra output budget alone is not enough.
            # Short count checks and the image inputs stay cached.
            graph = copy.deepcopy(graph)
            for node in graph.values():
                if node.get('class_type') == 'TextGenerate' and node['inputs'].get('max_length', 0) >= 100:
                    node['inputs']['max_length'] = min(4096, node['inputs']['max_length'] * 2)
                    node['inputs'].update({'sampling_mode':'on', 'sampling_mode.temperature':0.35,
                        'sampling_mode.top_k':64, 'sampling_mode.top_p':0.95,
                        'sampling_mode.min_p':0.05, 'sampling_mode.repetition_penalty':1.05,
                        'sampling_mode.seed':random.randrange(1, 2**63)})
        # Inconclusive/error results are deliberately not persistent cache hits.
        if review_outcome(review) in ('passed', 'content_issue'):
            with self.lock:
                fresh = self.load(project['id'])
                cache = fresh.setdefault('review_cache', {})
                cache[key] = copy.deepcopy(review)
                while len(cache) > 128:
                    cache.pop(next(iter(cache)))
                self.save(fresh)
        return review

    def _review_image(self, project: dict, shot: dict, name: str, tick, phase="start", job: dict | None = None) -> dict:
        required = review_requirements(project, shot, phase)
        graph_for = lambda uploaded: graphs.visual_review_graph(uploaded, json.dumps(required),
                  director.look_for_state(project['look'], required['state']))
        review = (self._checked_review(project, name, {'phase':phase, 'requirements':required}, graph_for, tick)
                  if job is None else self._checked_review(project, name, {'phase':phase, 'requirements':required},
                                                           graph_for, tick, job=job))
        if required['unresolved_facts'] or required['unresolved_cast']:
            extra = {key:value for key,value in review.items() if key not in ('version','status','outcome','issues','findings')}
            review = director.review_result(review.get('issues', []) + [
                {'category':'uncertain','code':'unresolved_scene_fact','severity':'warning',
                 'message': f'{key}: the script has not established a checkable state.'} for key in required['unresolved_facts']] + [
                {'category':'uncertain','code':'unresolved_cast_presence' if person in required['uncertain_cast_presence'] else 'unresolved_cast_identity','severity':'warning',
                 'message': (f'{person}: the opening direction does not establish whether this character is visible.'
                             if person in required['uncertain_cast_presence'] else
                             f'{person}: no appearance description is available for identity review.')} for person in required['unresolved_cast']], **extra)
        review["of"] = visual_inputs(project, shot)
        return review

    def _review_video(self, project: dict, shot: dict, name: str, tick, job: dict | None = None) -> dict:
        contracts = [json.dumps(review_requirements(project, shot, phase)) for phase in ("start", "middle", "end")]
        graph_for = lambda uploaded: graphs.video_review_graph(uploaded, *contracts,
                director.look_for_state(project['look'], review_requirements(project, shot, 'start')['state']))
        review = (self._checked_review(project, name, {'phases':contracts}, graph_for, tick) if job is None
                  else self._checked_review(project, name, {'phases':contracts}, graph_for, tick, job=job))
        unresolved = set().union(*(set(review_requirements(project, shot, phase)['unresolved_facts']) for phase in ('start','middle','end')))
        unresolved_cast = set().union(*(set(review_requirements(project, shot, phase)['unresolved_cast']) for phase in ('start','middle','end')))
        uncertain_presence = set().union(*(set(review_requirements(project, shot, phase)['uncertain_cast_presence']) for phase in ('start','middle','end')))
        if unresolved or unresolved_cast:
            extra = {key:value for key,value in review.items() if key not in ('version','status','outcome','issues','findings')}
            review = director.review_result(review.get('issues', []) + [
                {'category':'uncertain','code':'unresolved_scene_fact','severity':'warning',
                 'message':f'{key}: the script has not established a checkable state.'} for key in sorted(unresolved)] + [
                {'category':'uncertain','code':'unresolved_cast_presence' if person in uncertain_presence else 'unresolved_cast_identity','severity':'warning',
                 'message': (f'{person}: the opening direction does not establish whether this character is visible.'
                             if person in uncertain_presence else
                             f'{person}: no appearance description is available for identity review.')} for person in sorted(unresolved_cast)], **extra)
        review["of"] = video_inputs(project, shot)
        review["sample_positions"] = [0, 1/3, 2/3, 1]
        return review

    def _record_candidate(self, project_id: str, shot_id: str, kind: str, name: str, review: dict, **info) -> None:
        """Drafts retain flags; a flagged candidate never displaces a current approved take."""
        with self.lock:
            fresh = self.load(project_id)
            current = self._shot(fresh, shot_id)
            current.setdefault("quality", {})[kind] = {"name": name, **review}
            approved = current_take(current, kind)
            expected = review.get('of') or info.get('of')
            approved_current = review_passed(approved) and (approved.get('review', {}).get('of') or approved.get('of')) == expected
            if review["status"] == "passed" or draft_mode(fresh) and not approved_current:
                add_take(current, kind, name, review=review, **info)
            else:
                takes = current.setdefault("takes", {}).setdefault(kind, [])
                existing = next((take for take in takes if take['name'] == name), None)
                if existing is not None:
                    existing.update(review=review, **info)
                else:
                    takes.append({"name": name, "review": review, **info})
            self.save(fresh)
        if review["status"] != "passed" and not draft_mode(fresh):
            raise RuntimeError(f"{kind.title()} needs review: " + "; ".join(review["findings"][:4]))

    def _run_review(self, job: dict, tick) -> None:
        project = self._require_plan(job["project"], tick)
        shot = self._shot(project, job["shot"])
        name = job.get('candidate_name') or shot.get('video')
        if not name:
            raise RuntimeError("Render a clip before reviewing it")
        candidate = next((take for take in shot.get('takes', {}).get('video', []) if take['name'] == name), None)
        if not candidate or candidate.get('of') != video_inputs(project, shot):
            raise RuntimeError('This clip is out of date. Render the updated shot before reviewing it.')
        review = self._review_video(project, shot, name, tick)
        dialogue = speech.check(self.path(project['id']) / name, shot.get('line', ''), candidate.get('dialogue_review')) if shot.get('line', '').strip() else None
        with self.lock:
            fresh = self.load(project["id"])
            current = self._shot(fresh, shot["id"])
            take = next(t for t in current["takes"]["video"] if t["name"] == name)
            if (take.get('review') or {}).get('director_review'):
                # A later automated review cannot revoke an explicit director
                # decision. Keep its evidence separately for inspection.
                take['latest_automated_review'] = review
                if dialogue:
                    take['dialogue_review'] = dialogue
                sync_dialogue_review(current)
                self.save(fresh)
                return
            if draft_mode(fresh) and current.get('video') == name and take.get('of') == video_inputs(fresh, current):
                suggestion = temporal_drift_suggestion(review)
                if suggestion:
                    review['repair_suggestion'] = suggestion
            take["review"] = review
            if dialogue:
                take['dialogue_review'] = dialogue
            current.setdefault("quality", {})["video"] = {"name": name, **review}
            if job.get('candidate_name') and review_passed(take) and take.get('of') == video_inputs(fresh, current):
                select_take(current, 'video', name)
            sync_dialogue_review(current)
            self.save(fresh)
        if review["status"] != "passed" and not draft_mode(fresh):
            raise RuntimeError("Video needs review: " + "; ".join(review["findings"][:4]))

    def accept_review(self, project_id: str, shot_id: str, kind: str, name: str, reason: str) -> dict:
        """An explicit director decision, kept alongside the model's original evidence."""
        if kind not in ("keyframe", "endframe", "video", "sketch"):
            raise ValueError("Inspect the candidate and enter a reason before accepting it")
        with self.lock:
            project = self.load(project_id)
            if not reason.strip() and not draft_mode(project):
                raise ValueError("Enter a reason for a strict-review override")
            reason = reason.strip() or 'Kept for this cut after visual inspection'
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
                if 'portrait_identity' in ((review or {}).get('of') or {}):
                    expected['portrait_identity'] = {'reference': project.get('reference'), 'description': lead_identity(project)}
            if not review or review.get("of") != expected or not plan_usable(project):
                raise RuntimeError("The candidate's inputs are out of date; regenerate it before accepting")
            if take not in candidates:
                candidates.append(take)
            review.update(status="passed", version=director.REVIEW_VERSION, director_review={"reason": reason, "time": time.time()},
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
                                      negative=director.image_negative(project["look"]),
                                      backend=job.get("image_backend", project.get("image_backend", "hidream")),
                                      preview=project.get("image_quality", "fast") == "fast")
        files = self.comfy.run(graph, on_tick=tick)
        name = f"cast_{uuid.uuid4().hex[:6]}.png"
        self.comfy.download(files[0], self.path(project["id"]) / name)
        with self.lock:
            project = self.load(job["project"])
            project["reference"], project["reference_prompt"] = name, prompt
            project["reference_backend"] = job.get("image_backend", project.get("image_backend", "hidream"))
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
        self._check_visual_anchor(project_id, reference, project.get("look", ""), tick)

    def _check_visual_anchor(self, project_id: str, reference: str, look: str, tick) -> None:
        """Advisory style check; never block a film or equate model uncertainty with a defect."""
        answer = ""
        try:
            graph = graphs.people_check_graph(self._upload(project_id, reference), director.anchor_review_question(look))
            record = self.comfy.wait(self.comfy.submit(graph), on_tick=tick, timeout=600)
            answer = "".join(record.get("outputs", {}).get("answer", {}).get("text", [])).strip().upper().rstrip(".!")
        except ComfyError as error:
            if "interrupt" in str(error).lower():
                raise
        except Exception:
            pass  # visual evidence is optional; the original reference and the film stay available
        status = {"YES": "possible_match", "NO": "possible_mismatch"}.get(answer, "uncertain")
        with self.lock:
            fresh = self.load(project_id)
            if fresh.get("reference") == reference and fresh.get("look", "") == look:
                fresh["visual_anchor_review"] = {"name": reference, "look": look, "status": status}
                self.save(fresh)

    def _run_describe_lead(self, job: dict[str, Any], tick) -> None:
        self._describe_lead(job["project"], tick)

    def _make_world(self, project_id: str, tick, job: dict[str, Any] | None = None) -> str:
        """Paint a location plate; keep uncertain evidence distinct from an empty result."""
        project = self.load(project_id)
        source = world_plate_inputs(project)
        world = project.get("world") or {}
        seed = (world.get("seed") or random.randrange(1, 2**31)) + 1_000_003 * len(world.get("takes", []))
        environment = source.get('environment')
        prompt = director.world_plate_prompt('; '.join(environment) if environment else project["scene"], project["look"])
        folder = self.path(project_id)
        for attempt in range(3):
            if job:
                job["label"] = "Painting the world" + (f" · try {attempt + 1}" if attempt else "")
            files = self.comfy.run(graphs.keyframe_graph(prompt, seed + attempt, project["aspect"],
                                                         f"open-cinema/{project_id}/world",
                                                         negative=director.image_negative(project["look"]),
                                                         backend=(job or {}).get("image_backend", project.get("image_backend", "hidream")),
                                                         preview=project.get("image_quality", "fast") == "fast"), on_tick=tick)
            name = f"world_{uuid.uuid4().hex[:6]}.png"
            self.comfy.download(files[0], folder / name)
            if job:
                job["label"] = "Painting the world · checking it's empty"
            answer = ''
            try:
                record = self.comfy.wait(self.comfy.submit(graphs.people_check_graph(
                    self._upload(project_id, name), director.PEOPLE_CHECK)), on_tick=tick, timeout=600)
                answer = ''.join(record.get('outputs', {}).get('answer', {}).get('text', [])).strip().upper().rstrip('.!')
            except ComfyError as error:
                if 'interrupt' in str(error).lower():
                    raise
            except Exception:
                pass  # retain the image with inconclusive evidence, not a false clean result
            empty = {'NO': True, 'YES': False}.get(answer)
            # Only affirmative evidence of people justifies a new GPU render.
            if empty is not False or attempt == 2:
                break
        with self.lock:
            fresh = self.load(project_id)
            unit = fresh.get('world') or {}
            fresh['world'] = unit
            unit.setdefault("seed", seed)
            unit.setdefault("takes", []).append({"name": name, "prompt": prompt, "seed": seed + attempt,
                                                 "of": source, "empty": empty,
                                                 "image_backend": (job or {}).get("image_backend", project.get("image_backend", "hidream"))})
            same_world = world_plate_inputs(fresh) == source
            if same_world and (empty is True or draft_mode(fresh)):
                unit["plate"] = name
            self.save(fresh)
        if not same_world:
            raise RuntimeError('The world changed while the plate was painting. Your edits and the earlier plate were kept; paint again.')
        if empty is not True and not draft_mode(fresh):
            detail = 'The check was inconclusive' if empty is None else 'The check found someone after three attempts'
            raise RuntimeError(f'World plate needs review: {detail}. Inspect the saved plate or paint another.')
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
            self._run_cast({**job, "project": project["id"]}, tick)
            project = self.load(job["project"])
        index = next(i for i, s in enumerate(project["shots"]) if s["id"] == job["shot"])
        shot = project["shots"][index]
        if story_stale(project, shot):
            raise RuntimeError("The story beat changed. Rewrite this shot or confirm it still tells the beat.")
        planned_visual = visual_inputs(project, shot)
        # Resume with the best current candidate before spending GPU time on a new image.
        candidates = list(shot.get('takes', {}).get('keyframe', [])) if job.get('reuse_candidate') else []
        if job.get('reuse_candidate'):
            candidates += [item for item in shot.get('frame_repairs', []) if item.get('phase') == 'start']
        requested_backend = job.get('frame_backend', project.get('frame_backend', 'qwen'))
        candidates = [item for item in candidates if item.get('review', {}).get('of') == planned_visual
                      and (item.get('recipe', {}).get('frame_backend') or 'qwen') == requested_backend
                      and (self.path(project['id']) / item['name']).is_file()]
        if candidates:
            order = {'passed':0, 'uncertain':1, 'reviewer_error':2, 'content_issue':3}
            candidate = min(reversed(candidates), key=lambda item: order.get(review_outcome(item.get('review', {})), 4))
            review = candidate['review']
            if review.get('version') != director.REVIEW_VERSION:
                review = self._review_image(project, shot, candidate['name'], tick)
            if review_outcome(review) != 'content_issue' or draft_mode(project):
                self._metric('candidate_reuse')
                self._record_candidate(project['id'], shot['id'], 'keyframe', candidate['name'], review,
                                       recipe=candidate.get('recipe', {'kind':'shot','visual':planned_visual}), seed=shot['seed'])
                return
        look, scene, aspect = project["look"], project["scene"], project["aspect"]
        look = director.look_for_state(look, review_requirements(project, shot, "start")["state"])
        continuity = state_design(project)
        prefix = f"open-cinema/{project['id']}/key_{shot['id']}"
        plate = current_plate(project)
        world_optional = bool(not plate and job.get('defer_world') and draft_mode(project) and index == 0
                              and shot.get('shot_size') not in director.WIDE_SIZES
                              and shot.get('frame_source') != 'previous_end')
        if not plate and not world_optional:
            plate = self._make_world(project["id"], tick, job)
        lead, visible_others = starting_cast(project, shot)
        reference = project.get("reference") if lead else None
        if reference and not lead_identity(project):  # a new portrait: describe its face before painting it
            job["label"] = f"Keyframe {index + 1} · describing the lead"
            self._describe_lead(project["id"], tick)
            project = self.load(job["project"])
        sketch = self._current_sketch(project, shot, plate, reference)
        if not sketch:  # the storyboard drawing sets the composition, so it's drawn (or redrawn) first
            job["label"] = f"Keyframe {index + 1} · drawing the storyboard"
            sketch = self._draw_sketch(project["id"], shot["id"], tick, job)
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
            if not previous.get("video") or video_stale(project, previous) or not take_usable(project, current_take(previous, "video")):
                raise RuntimeError("Render and review the preceding shot before using its final frame")
            source = self._last_frame(project["id"], previous["video"])
        prop = prop_input(project, shot)
        if prop and not prop["image"]:
            raise RuntimeError("Generate the prop reference for its starting state on Story first")
        characters = selected_character_references(project, shot)
        if previous_end and job.get('frame_backend', project.get('frame_backend', 'qwen')) != 'qwen':
            characters = []
        # The graph accepts two supporting pictures after its opening image.
        # Lead, explicit prop, then named people take precedence over a wide
        # world reference; the setting remains described in the prompt.
        occupied = int(bool(reference)) + int(bool(prop)) + len(characters)
        use_world_reference = not previous_end and shot["shot_size"] in director.WIDE_SIZES and occupied < 2
        prompt = director.shot_prompt(shot["action"], shot["shot_size"], look, continuity, has_cast=bool(reference),
                                      camera_move=shot["camera_move"], lead=lead,
                                      world=scene.strip(), identity=identity,
                                      cast=project.get("cast", ""), storyboard=bool(sketch) and not previous_end,
                                      others=visible_others, line=shot.get("line", ""),
                                      start_frame=shot.get("start_frame", ""), world_reference=use_world_reference,
                                      world_picture_index=(occupied + 2) if use_world_reference else None,
                                      cast_uncertain=bool(shot.get('cast_roster_unresolved')) or
                                          ('start_cast' in shot and shot['start_cast'] is None))
        prompt += " " + director.state_direction(review_requirements(project, shot, 'start')['state'])
        if previous_end:
            requirements = review_requirements(project, shot, "start")
            cast_direction = linked_cast_direction(project, shot, previous)
            prompt = director.following_frame_prompt(shot.get("start_frame") or shot["action"], shot["shot_size"],
                cast_direction, requirements["state"], look=look, camera_move=shot.get("camera_move", ""),
                expected_count=None if requirements['unresolved_cast'] else requirements['count'])
        # The previous performance remains the visual anchor. A returning person
        # absent from that frame can use one separate identity-only portrait.
        refs = [] if previous_end or not reference else [self._upload(project['id'], reference)]
        if previous_end and job.get('frame_backend', project.get('frame_backend', 'qwen')) == 'qwen':
            for character in characters:
                refs.append(self._upload(project['id'], character['image']))
                prompt += (f" Picture {len(refs) + 1} is an identity reference for {character['name']}. "
                           f"If {character['name']} is visible, match their face, hair and clothes from this picture; "
                           "follow the staging for when they appear.")
        if prop and not previous_end:
            refs.append(self._upload(project["id"], prop["image"]))
            prompt += " " + director.prop_reference_direction(len(refs) + 1, prop["name"], prop["description"], prop["state"])
        if not previous_end:
            for character in characters:
                refs.append(self._upload(project['id'], character['image']))
                prompt += f" Picture {len(refs) + 1} is the character {character['name']}; preserve that individual's distinctive face, appearance and wardrobe while following the storyboard pose."
            if use_world_reference:
                refs.append(self._upload(project['id'], plate))
        frame_backend = job.get('frame_backend', project.get('frame_backend', 'qwen'))
        opening_requirements = review_requirements(project, shot, 'start')
        mixed_composition = (not previous_end and bool(reference) and not prop and len(characters) == 1
                             and len(opening_requirements['people']) == 2
                             and len(staging.material_facts(look, opening_requirements['people'])) == 2
                             and not opening_requirements['unresolved_cast'])
        if mixed_composition:
            # A monochrome board can turn both a human and a puppet into the
            # same material. Anchor their distinct identities directly instead.
            source = reference
            refs = [self._upload(project['id'], characters[0]['image'])]
            use_world_reference = False
            prompt = staging.portrait_composition_prompt(
                shot.get('start_frame') or shot['action'], director.SHOT_SIZES.get(shot['shot_size'], shot['shot_size']),
                scene.strip(), look, opening_requirements['people'])
            prompt += ' ' + director.state_direction(opening_requirements['state'])
        camera_direction = staging.camera_direction(shot.get('start_frame', ''),
                                                    opening_requirements['people'])
        if camera_direction:
            prompt = camera_direction + ' ' + prompt
        picture = self._upload(project['id'], source)
        if frame_backend == 'klein':
            graph = graphs.klein_coverage_graph(prompt, seed, picture, prefix, aspect,
                    second_reference=refs[0] if refs else None, third_reference=refs[1] if len(refs) > 1 else None)
        else:
            graph = graphs.coverage_graph(prompt, seed, picture, prefix, aspect,
                    second_reference=refs[0] if refs else None, third_reference=refs[1] if len(refs) > 1 else None,
                    detailed=project.get('image_quality') == 'detailed')
        # The full visual review already runs a neutral count; avoid a duplicate model pass.
        recipe = {"kind": "shot", "world": plate, "lead": reference, "identity": identity, "sketch": sketch,
                  "composition_version": 2, "world_reference": use_world_reference, "frame_backend": frame_backend,
                  "composition_source": "cast_portraits" if mixed_composition else "previous_end" if previous_end else "storyboard",
                  "source_frame": source, "frame_source": shot.get("frame_source", "storyboard"),
                  "visual": visual_inputs(project, shot),
                  "others": shot.get("others", ""), "character_references": characters,
                  "action": shot["action"], "shot_size": shot["shot_size"], "camera_move": shot["camera_move"],
                  "steps": [("FLUX.2 Klein 4B" if frame_backend == 'klein' else "Qwen-Image-Edit 2511") + " · " + ("previous performance" + (" + returning cast" if refs else "") if previous_end else
                            ("cast portraits" if mixed_composition else "the storyboard" + (" + the lead" if reference else "")) +
                            (" + supporting cast" if characters and not mixed_composition else "") +
                            (" + the world" if use_world_reference else "")) +
                            (" · 40 steps" if frame_backend == 'qwen' and project.get("image_quality") == "detailed" else " · 4 steps")]}
        if world_optional:
            recipe['world_optional'] = True
        # Only linked shots with a fully specified, countable cast pay for this
        # inexpensive early check; ordinary draft cuts retain deferred review.
        expected_count = requirements.get('count') if previous_end and not requirements.get('unresolved_cast') else None
        if type(expected_count) is int and expected_count > 0:
            graph = graphs.verify_cast(graph, '11' if frame_backend == 'klein' else '15', expected_count)
            job['label'] = f'Keyframe {index + 1} · reframing and checking visible cast'
        files, seed, cast_review = (self._render_checked(graph, seed, tick, job=job) if previous_end
                                    else self._render_checked(graph, seed, tick))
        name = f"key_{shot['id']}_{uuid.uuid4().hex[:6]}.png"
        self.comfy.download(files[0], self.path(project["id"]) / name)
        known_review, attempted = None, False
        if type(expected_count) is int and expected_count > 0:
            name, prompt, seed, known_review, attempted = self._recover_linked_cast(
                project, shot, name, prompt, seed, recipe, cast_review, expected_count,
                picture, prefix, frame_backend, tick, job, index, refs[0] if previous_end and refs else None)
        self._finish_keyframe(project, shot, name, prompt, seed, recipe, tick, job, index,
                              known_review=known_review, allow_repair=not attempted and known_review is None)

    def _retain_linked_candidate(self, project: dict, shot: dict, name: str, review: dict, **info) -> bool:
        """Keep an inspectable take without changing the selected frame or clip."""
        with self.lock:
            fresh = self.load(project['id'])
            current = self._shot(fresh, shot['id'])
            takes = current.setdefault('takes', {}).setdefault('keyframe', [])
            existing = next((take for take in takes if take['name'] == name), None)
            if existing:
                existing.update(review=review, **info)
            else:
                takes.append({'name': name, 'review': review, **info})
            selected_review = current_take(current, 'keyframe').get('review') or {}
            original_review = current_take(shot, 'keyframe').get('review') or {}
            unchanged = (visual_inputs(project, shot) == visual_inputs(fresh, current)
                         and current.get('keyframe') == shot.get('keyframe') and current.get('video') == shot.get('video')
                         and selected_review.get('director_review') == original_review.get('director_review')
                         and fresh.get('review_policy', 'draft') == project.get('review_policy', 'draft'))
            self.save(fresh)
            return unchanged

    def _recover_linked_cast(self, project: dict, shot: dict, name: str, prompt: str, seed: int, recipe: dict,
                             cast_review: dict, expected: int, picture: str, prefix: str, backend: str,
                             tick, job: dict, index: int, second_reference: str | None = None) -> tuple:
        """Try at most one alternate after two corroborating extra-cast observations."""
        if job.get('stopped'):
            pending = director.review_result([{'category':'uncertain', 'code':'pending_review', 'severity':'warning',
                'message':'Visual checks were interrupted; inspect this frame.'}], of=visual_inputs(project, shot))
            self._retain_linked_candidate(project, shot, name, pending, prompt=prompt, seed=seed, recipe=recipe)
            raise ComfyError('interrupted')
        observed = cast_review.get('observed_count') if isinstance(cast_review, dict) else None
        if (not valid_review_result(cast_review) or cast_review.get('outcome') != 'content_issue'
                or type(observed) is not int or observed <= expected
                or cast_review.get('expected_count') != expected
                or not any(i.get('code') == 'cast_count_mismatch' for i in cast_review.get('issues', []))):
            return name, prompt, seed, None, False
        selected = current_take(shot, 'keyframe')
        if (selected.get('review') or {}).get('director_review'):
            return name, prompt, seed, None, False
        pending = director.review_result([{'category':'uncertain', 'code':'pending_review', 'severity':'warning',
            'message':'Visual checks are queued; this draft frame has not been reviewed.'}])
        pending['of'] = visual_inputs(project, shot)
        if not self._retain_linked_candidate(project, shot, name, pending, prompt=prompt, seed=seed, recipe=recipe):
            raise RuntimeError('The shot changed while rendering. The earlier candidate was kept; render again.')
        job['label'] = f'Keyframe {index + 1} · confirming extra characters'
        original = self._review_image(project, shot, name, tick, job=job)
        evidence = original.get('evidence') if isinstance(original, dict) else None
        count = evidence.get('count') if isinstance(evidence, dict) else None
        valid = valid_review_result(original)
        confirmed = (valid and review_outcome(original) == 'content_issue' and type(count) is int and count == observed
                     and any(i.get('code') == 'cast_count_mismatch' for i in original.get('issues', [])))
        if not confirmed:
            # A passing full review does not erase a contradictory quick count.
            # Malformed evidence is similarly never promoted as a clean result.
            if not valid:
                original = director.review_result([{'category':'reviewer_error','code':'invalid_review_output',
                    'severity':'warning','message':'The visual check returned incomplete evidence; inspect this frame.'}],
                    of=visual_inputs(project, shot))
            else:
                extra = {k:v for k,v in original.items() if k not in ('version','status','outcome','issues','findings')}
                original = director.review_result(original['issues'] + [{'category':'uncertain',
                    'code':'cast_count_disagreement','severity':'warning',
                    'message':'The cast checks did not agree; inspect this frame.'}], **extra)
        if not self._retain_linked_candidate(project, shot, name, original, prompt=prompt, seed=seed, recipe=recipe):
            raise RuntimeError('The shot changed during visual review. The earlier candidate was kept; render again.')
        if not confirmed:
            return name, prompt, seed, original, False
        retry_prompt = prompt + f' Exactly {expected} distinct characters total; each appears only once, with no duplicates.'
        retry_seed = (seed + 1_000_003) % (2**31)
        retry_graph = (graphs.klein_coverage_graph(retry_prompt, retry_seed, picture, prefix, project['aspect'])
                       if backend == 'klein' else graphs.coverage_graph(retry_prompt, retry_seed, picture, prefix,
                           project['aspect'], second_reference=second_reference, detailed=project.get('image_quality') == 'detailed'))
        job['label'] = f'Keyframe {index + 1} · trying one alternate'
        if job.get('stopped'):
            raise ComfyError('interrupted')
        self._metric('reframe_retries')
        files, retry_seed, _ = self._render_checked(retry_graph, retry_seed, tick, job=job)
        alternate = f"key_{shot['id']}_{uuid.uuid4().hex[:6]}.png"
        self.comfy.download(files[0], self.path(project['id']) / alternate)
        if not self._retain_linked_candidate(project, shot, alternate, pending, prompt=retry_prompt, seed=retry_seed,
                                             recipe=recipe, repaired_from=name):
            raise RuntimeError('The shot changed while trying an alternate. Both candidates were kept; render again.')
        if job.get('stopped'):
            raise ComfyError('interrupted')
        job['label'] = f'Keyframe {index + 1} · checking alternate'
        review = self._review_image(project, shot, alternate, tick, job=job)
        if job.get('stopped'):
            self._retain_linked_candidate(project, shot, alternate, review, prompt=retry_prompt, seed=retry_seed,
                                           recipe=recipe, repaired_from=name)
            raise ComfyError('interrupted')
        if valid_review_result(review) and review_outcome(review) == 'passed':
            # A correct person count alone cannot establish the requested
            # viewpoint, and tested vision models also confirmed wrong angles.
            # Preserve the alternate for the director rather than auto-select it.
            extra = {k:v for k,v in review.items() if k not in ('version','status','outcome','issues','findings')}
            review = director.review_result(review['issues'] + [{'category':'uncertain',
                'code':'viewpoint_unverified','severity':'warning',
                'message':'Inspect the alternate camera viewpoint before using it.'}], **extra)
        if not self._retain_linked_candidate(project, shot, alternate, review, prompt=retry_prompt, seed=retry_seed,
                                             recipe=recipe, repaired_from=name):
            raise RuntimeError('The shot changed during visual review. Both candidates were kept; render again.')
        if valid_review_result(review) and review_outcome(review) == 'passed':
            return alternate, retry_prompt, retry_seed, review, True
        self._metric('repair_rejections')
        return name, prompt, seed, original, True

    def _finish_keyframe(self, project: dict, shot: dict, name: str, prompt: str, seed: int, recipe: dict,
                         tick, job: dict, index: int, known_review: dict | None = None,
                         allow_repair: bool = True) -> None:
        """Let draft images render immediately; retain a pending review, never a false pass."""
        def record(review):
            # Stop, edit validation and promotion share the same lock.
            with self.lock:
                if job.get('stopped'):
                    if recipe.get('frame_source') == 'previous_end':
                        self._retain_linked_candidate(project, shot, name, review, prompt=prompt, seed=seed, recipe=recipe)
                    raise ComfyError('interrupted')
                if known_review or recipe.get('frame_source') == 'previous_end':
                    if not self._retain_linked_candidate(project, shot, name, review,
                                                         prompt=prompt, seed=seed, recipe=recipe):
                        raise RuntimeError('The shot changed before selection. The candidate was kept; render again.')
                    if known_review and shot.get('keyframe') and review_outcome(review) != 'passed':
                        raise RuntimeError('Opening frame needs review: the earlier selected take was kept; inspect the new candidates.')
                    self._record_candidate(project['id'], shot['id'], 'keyframe', name, review,
                                           prompt=prompt, seed=seed, recipe=recipe)
                else:
                    self._record_candidate(project['id'], shot['id'], 'keyframe', name, review,
                                           prompt=prompt, seed=seed, recipe=recipe)
        if draft_mode(project):
            review = known_review or director.review_result([{'category':'uncertain', 'code':'pending_review', 'severity':'warning',
                'message':'Visual checks are queued; this draft frame has not been reviewed.'}])
            review['of'] = visual_inputs(project, shot)
            record(review)
            if not known_review:
                with self.lock:
                    if job.get('stopped'):
                        raise ComfyError('interrupted')
                    self.enqueue('review_frame', project['id'], shot['id'], f'Checking frame {index + 1}',
                                 candidate_name=name, review_policy='draft')
            return
        job['label'] = f'Keyframe {index + 1} · checking state and style'
        linked = recipe.get('frame_source') == 'previous_end'
        review = known_review or (self._review_image(project, shot, name, tick, job=job) if linked
                                  else self._review_image(project, shot, name, tick))
        if linked and job.get('stopped'):
            self._retain_linked_candidate(project, shot, name, review, prompt=prompt, seed=seed, recipe=recipe)
            raise ComfyError('interrupted')
        if allow_repair:
            name, review = (self._repair_frame(project, shot, name, review, tick, 'start', job=job) if linked
                            else self._repair_frame(project, shot, name, review, tick, 'start'))
        record(review)

    def _run_review_frame(self, job: dict, tick) -> None:
        """Review the exact draft frame later without regenerating or silently selecting it."""
        project = self._require_plan(job['project'], tick)
        shot = self._shot(project, job['shot'])
        name = job.get('candidate_name') or shot.get('keyframe')
        candidate = next((take for take in shot.get('takes', {}).get('keyframe', []) if take['name'] == name), None)
        snapshot = visual_inputs(project, shot)
        recorded = candidate.get('review', {}).get('of') if candidate else None
        if not candidate or not visual_inputs_match(recorded, snapshot):
            raise RuntimeError('This frame is out of date. Render the updated shot before reviewing it.')
        review = self._review_image(project, shot, name, tick)
        # An image made before the reference bank existed did not use a later portrait.
        if isinstance(recorded, dict) and 'character_references' not in recorded:
            review['of'] = recorded
        if not draft_mode(project):
            repaired_name, review = self._repair_frame(project, shot, name, review, tick, 'start')
            if repaired_name != name:
                self._record_candidate(project['id'], shot['id'], 'keyframe', repaired_name, review,
                                       prompt=candidate.get('prompt', ''), seed=candidate.get('seed'),
                                       recipe=candidate.get('recipe'), repaired_from=name)
                return
        with self.lock:
            fresh = self.load(project['id'])
            current = self._shot(fresh, shot['id'])
            take = next((item for item in current.get('takes', {}).get('keyframe', []) if item['name'] == name), None)
            if not take:
                return
            take['review'] = review
            if current.get('keyframe') == name and visual_inputs(fresh, current) == snapshot:
                current.setdefault('quality', {})['keyframe'] = {'name': name, **review}
            self.save(fresh)
        if review['status'] != 'passed' and not draft_mode(project):
            raise RuntimeError('Opening frame needs review: ' + '; '.join(review.get('findings', [])[:4]))

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
        phase = 'start' if kind == 'keyframe' else 'end'
        review = candidate['review']
        if review_outcome(review) != 'content_issue' or review.get('version') != director.REVIEW_VERSION:
            review = self._review_image(project, shot, candidate['name'], tick, phase)
        name, review = self._repair_frame(project, shot, candidate["name"], review, tick, phase)
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
                approved = current.get('endframe') or {}
                protected = review_passed(approved) and approved.get('of') == expected
                if review["status"] == "passed" or draft_mode(fresh) and not protected:
                    current["endframe"] = take
                self.save(fresh)
            if review["status"] != "passed" and not draft_mode(fresh):
                raise RuntimeError("Ending frame still needs review: " + "; ".join(review["findings"][:4]))

    def _repair_frame(self, project: dict, shot: dict, name: str, review: dict, tick, phase: str,
                      job: dict | None = None) -> tuple[str, dict]:
        """Repair confirmed defects only, with a budget and no candidate regression."""
        best_name, best_review = name, review
        budget = 1 if draft_mode(project) else 2
        for attempt in range(budget):
            issues = review.get('issues') or []
            confirmed = [item for item in issues if item.get('category') == 'content_issue']
            # Unknown evidence and malformed output cannot justify changing pixels.
            if review_outcome(review) != 'content_issue' or not confirmed:
                break
            with self.lock:
                fresh = self.load(project["id"])
                self._shot(fresh, shot["id"]).setdefault("frame_repairs", []).append(
                    {"name": name, "phase": phase, "review": review})
                self.save(fresh)
            prop = prop_input(project, shot, phase)
            prompt = director.frame_repair_prompt(shot.get("start_frame" if phase == "start" else "end_state", ""),
                         json.dumps(review_requirements(project, shot, phase)), json.dumps([item['message'] for item in confirmed]))
            self._metric('image_repairs')
            graph = graphs.coverage_graph(prompt, (shot["seed"] + 97 * (attempt + 1)) % 2**31,
                    self._upload(project["id"], name), f"open-cinema/{project['id']}/repair_{shot['id']}", project["aspect"],
                    keep_layout=True, detailed=True)
            files = self.comfy.run(graph, on_tick=tick) if job is None else self._run_for_job(graph, tick, job)
            name = f"repair_{phase}_{shot['id']}_{uuid.uuid4().hex[:6]}.png"
            self.comfy.download(files[0], self.path(project["id"]) / name)
            if job and job.get('stopped'):
                pending = director.review_result([{'category':'uncertain','code':'pending_review','severity':'warning',
                    'message':'Visual checks were interrupted; inspect this candidate.'}])
                with self.lock:
                    fresh = self.load(project['id'])
                    self._shot(fresh, shot['id']).setdefault('frame_repairs', []).append(
                        {'name':name, 'phase':phase, 'review':pending, 'not_selected':True})
                    self.save(fresh)
                raise ComfyError('interrupted')
            review = (self._review_image(project, shot, name, tick, phase) if job is None
                      else self._review_image(project, shot, name, tick, phase, job=job))
            new_issues = [item for item in review.get('issues', []) if item.get('category') == 'content_issue']
            # A reviewer error or uncertainty is not evidence that a repair improved the image.
            old_codes = {item.get('code') for item in confirmed}
            new_codes = {item.get('code') for item in new_issues}
            improved = review_outcome(review) == 'passed' or (review_outcome(review) == 'content_issue'
                and new_codes <= old_codes and len(new_issues) < len(confirmed))
            if improved:
                best_name, best_review = name, review
            else:
                self._metric('repair_rejections')
                with self.lock:
                    fresh = self.load(project['id'])
                    self._shot(fresh, shot['id']).setdefault('frame_repairs', []).append(
                        {'name':name, 'phase':phase, 'review':review, 'not_selected':True})
                    self.save(fresh)
                break
        return best_name, best_review

    def _run_character_reference(self, job: dict, tick) -> None:
        """Cast one named supporting individual without replacing a newer user edit."""
        project = self.load(job['project'])
        people = cast_list(project)
        canonical = next((name for name in people if name.casefold() == str(job.get('character', '')).casefold()), None)
        if not canonical or director.roster_entry_count(canonical, people[canonical]) != 1:
            raise RuntimeError('This character is no longer a named individual in the film')
        if job.get('automatic') and current_character_reference(project, canonical):
            return
        bank = project.get('character_references') or {}
        previous = copy.deepcopy(next((v for k, v in bank.items() if k.casefold() == canonical.casefold()), None))
        prompt = director.cast_prompt(f'{canonical}, {people[canonical]}', project.get('scene', ''), project.get('look', ''))
        seed = random.randrange(1, 2**31)
        graph = graphs.keyframe_graph(prompt, seed, project['aspect'],
                    f"open-cinema/{project['id']}/character", size=graphs.CAST_SIZE,
                    negative=director.image_negative(project.get('look', '')),
                    backend=job.get('image_backend', project.get('image_backend', 'hidream')),
                    preview=project.get('image_quality', 'fast') == 'fast')
        files = self.comfy.run(graph, on_tick=tick)
        name = f'character_{uuid.uuid4().hex[:10]}.png'
        self.comfy.download(files[0], self.path(project['id']) / name)
        with self.lock:
            fresh = self.load(project['id'])
            current_people = cast_list(fresh)
            current_name = next((key for key in current_people if key.casefold() == canonical.casefold()), None)
            current_bank = fresh.setdefault('character_references', {})
            old_key = next((key for key in current_bank if key.casefold() == canonical.casefold()), None)
            current_reference = current_bank.get(old_key) if old_key else None
            if not current_name or current_reference != previous or director.cast_prompt(
                    f'{current_name}, {current_people[current_name]}', fresh.get('scene', ''), fresh.get('look', '')) != prompt:
                raise RuntimeError('Character direction or reference changed during casting; the newer edit was kept')
            if old_key and old_key != current_name:
                current_bank.pop(old_key)
            current_bank[current_name] = {'image': name, 'source': 'generated', 'prompt': prompt,
                                          'description': current_people[current_name], 'look': fresh.get('look', ''), 'seed': seed}
            self.save(fresh)

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
                graphs.keyframe_graph(prompt, seed, "1:1", prefix, backend=job.get("image_backend", project.get("image_backend", "hidream")),
                                      preview=project.get("image_quality", "fast") == "fast")
        files = self.comfy.run(graph, on_tick=tick)
        name = f"prop_{prop['id']}_{uuid.uuid4().hex[:6]}.png"
        self.comfy.download(files[0], self.path(project["id"]) / name)
        with self.lock:
            fresh = self.load(project["id"])
            current = next(p for p in fresh.get("props", []) if p["id"] == prop["id"])
            current.setdefault("variants", {})[state] = {"name": name, "of": prop_design(project, prop)}
            self.save(fresh)

    def _ending_frame(self, project: dict, shot: dict, start: str, tick, job: dict | None = None) -> str:
        snapshot = {**ending_inputs(project, shot), "start": start}
        cached = shot.get("endframe") or {}
        selected_name = cached.get('name')
        selected_approval = (cached.get('review') or {}).get('director_review')
        upload_snapshot = {key: value for key, value in snapshot.items() if key != 'end_character_references'}
        if (cached.get("of") == snapshot or cached.get('source') == 'upload' and cached.get('of') == upload_snapshot) and take_usable(project, cached):
            return cached["name"]
        prop = prop_input(project, shot, "end")
        if prop and not prop["image"]:
            raise RuntimeError("Generate the prop reference for its ending state on Story first")
        visible = review_requirements(project, shot, "end")["state"]
        prompt = director.ending_frame_prompt(shot["action"], shot.get("end_state", ""), project["look"], visible, state_design(project))
        references = snapshot.get('end_character_references', [])
        uploaded = []
        for reference in references:
            uploaded.append(self._upload(project['id'], reference['image']))
            prompt += (f" Picture {len(uploaded) + 1} is {reference['name']}; preserve that person's "
                       "face, hair, clothing and distinguishing features while following the ending action.")
        graph = graphs.coverage_graph(prompt, take_seed(shot, "video"), self._upload(project["id"], start),
                    f"open-cinema/{project['id']}/end_{shot['id']}", project["aspect"], keep_layout=True,
                    second_reference=uploaded[0] if uploaded else None,
                    third_reference=uploaded[1] if len(uploaded) > 1 else None,
                    detailed=project.get("image_quality") == "detailed")
        files = self.comfy.run(graph, on_tick=tick) if job is None else self._run_for_job(graph, tick, job)
        name = f"end_{shot['id']}_{uuid.uuid4().hex[:6]}.png"
        self.comfy.download(files[0], self.path(project["id"]) / name)
        if job and job.get('stopped'):
            pending = director.review_result([{'category':'uncertain','code':'pending_review','severity':'warning',
                'message':'Visual checks were interrupted; inspect this candidate.'}])
            with self.lock:
                fresh = self.load(project['id'])
                self._shot(fresh, shot['id']).setdefault('endframes', []).append({'name':name,'of':snapshot,'review':pending})
                self.save(fresh)
            raise ComfyError('interrupted')
        review = (self._review_image(project, shot, name, tick, 'end') if job is None
                  else self._review_image(project, shot, name, tick, 'end', job=job))
        # Drafts keep the first reviewed ending so the user can see a playable
        # result promptly; strict mode retains the existing repair workflow.
        if not draft_mode(project):
            name, review = (self._repair_frame(project, shot, name, review, tick, 'end') if job is None
                            else self._repair_frame(project, shot, name, review, tick, 'end', job=job))
        review["of"] = snapshot
        with self.lock:
            fresh = self.load(project["id"])
            current = self._shot(fresh, shot["id"])
            candidate = {"name": name, "of": snapshot, "review": review, "prompt": prompt}
            current.setdefault("endframes", []).append(candidate)
            if job and job.get('stopped'):
                self.save(fresh)
                raise ComfyError('interrupted')
            current_end = current.get('endframe') or {}
            current_snapshot = {**ending_inputs(fresh, current), "start": current.get('keyframe')}
            if (current_snapshot != snapshot or current_end.get('name') != selected_name
                    or (current_end.get('review') or {}).get('director_review') != selected_approval):
                self.save(fresh)
                raise RuntimeError('The shot or ending selection changed while rendering. The candidate was kept; render again.')
            current.setdefault("quality", {})["endframe"] = {"name": name, **review}
            approved = current.get('endframe') or {}
            protected = review_passed(approved) and approved.get('of') == snapshot
            if review["status"] == "passed" or draft_mode(fresh) and not protected:
                current["endframe"] = candidate
            self.save(fresh)
        if review["status"] != "passed" and not draft_mode(fresh):
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
        expected_cast = review_requirements(project, shot, 'start')['count'] if "start_cast" in shot else director.character_count(lead, visible_others)
        portrait_identity = lead_identity(project) if lead and reference else ''
        cast_direction = project.get("cast", "")
        if portrait_identity:
            cast_direction = director._join(cast_direction, 'Portrait appearance: ' + portrait_identity)
        prompt = director.sketch_prompt(shot["action"], shot["shot_size"], shot["camera_move"], has_cast=bool(reference),
                                        lead=lead, world=project["scene"], cast=cast_direction,
                                        continuity="", start_frame=shot.get("start_frame", ""),
                                        others=visible_others, expected_cast=expected_cast,
                                        cast_uncertain=bool(shot.get('cast_roster_unresolved')) or
                                            ('start_cast' in shot and shot['start_cast'] is None))
        prompt += " " + director.sketch_state_prompt(review_requirements(project, shot, 'start')['state'])
        seed = (shot["seed"] + 7_777 * len(shot.get("sketches", []))) % 2**31
        prop = prop_input(project, shot)
        if prop:
            prompt += " Exact recurring prop geometry: " + prop["description"] + ". Depict every named colour as a grey value only."
        frame = current_take(shot, "keyframe")
        source_frame = shot.get("keyframe") if review_passed(frame) and visual_inputs_match(frame.get("review", {}).get("of"), visual_inputs(project, shot)) else None
        if source_frame:
            prompt = director.sketch_from_frame_prompt()
            graph = graphs.frame_storyboard_graph(self._upload(project_id, source_frame), seed, project["aspect"],
                      f"open-cinema/{project_id}/sketch_{shot_id}", expected_cast)
        else:
            graph = graphs.storyboard_graph(prompt, seed, project["aspect"],
                      f"open-cinema/{project_id}/sketch_{shot_id}", expected_cast,
                      backend=(job or {}).get("image_backend", project.get("image_backend", "hidream")),
                      preview=project.get("image_quality", "fast") == "fast")
        if job:
            job["detail"] = "Drawing a planning thumbnail, then checking visible cast. One attempt; flagged results are kept."
        files, seed, review = self._render_checked(graph, seed, tick)
        name = f"sketch_{shot_id}_{uuid.uuid4().hex[:6]}.png"
        self.comfy.download(files[0], self.path(project_id) / name)
        snapshot = sketch_of(shot, plate, reference, project)
        if not source_frame and portrait_identity:
            snapshot['portrait_identity'] = {'reference': reference, 'description': portrait_identity}
        review["of"] = snapshot
        with self.lock:
            fresh = self.load(project_id)
            current = self._shot(fresh, shot_id)
            current.setdefault("sketches", []).append({"name": name, "prompt": prompt, "seed": seed,
                                                       "source_frame": source_frame,
                                                       "image_backend": (job or {}).get("image_backend", project.get("image_backend", "hidream")),
                                                       "of": snapshot, "review": review})
            unchanged = (snapshot['visual'] == sketch_visual_inputs(fresh, current)
                         and (not source_frame or source_frame == current.get('keyframe'))
                         and ('portrait_identity' not in snapshot or snapshot['portrait_identity'] ==
                              {'reference': fresh.get('reference'), 'description': lead_identity(fresh)}))
            if unchanged:
                current.setdefault("quality", {})["sketch"] = {"name": name, **review}
                if review["status"] == "passed" or draft_mode(fresh):
                    current["sketch"] = name
            self.save(fresh)
        if not unchanged:
            raise RuntimeError('The shot or portrait changed while drawing. The earlier candidate was kept; draw again.')
        if review["status"] != "passed" and not draft_mode(fresh):
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

    def queue_sketches(self, project_id: str, shot_ids: list[str] | None = None, redraw: bool = False,
                       first_preview: str | None = None) -> list[dict[str, Any]]:
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
                jobs.append(self.enqueue("sketch", project_id, shot["id"], f"Storyboard {index + 1}", redraw=redraw,
                                         _priority=1.5 if first_preview and shot['id'] != first_preview else None))
        return jobs

    def _last_frame(self, project_id: str, video: str) -> str:
        name = f"{Path(video).stem}_last.png"
        # Decode the final second and reverse it so the selected frame is actually the last
        # decoded frame, including for variable frame rates and clips shorter than a second.
        subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-sseof", "-1", "-i",
                        str(self.path(project_id) / video), "-vf", "reverse", "-frames:v", "1", "-update", "1",
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
        linked = shot.get('frame_source') == 'previous_end' or shot.get('transition') == 'continue'
        if linked and job.get('stopped'):
            raise ComfyError('interrupted')
        if story_stale(project, shot):
            raise RuntimeError("The story beat changed. Rewrite this shot or confirm it still tells the beat.")
        if shot.get("transition") != "continue" and (job.get("redo_keyframe") or not shot.get("keyframe") or frame_stale(project, shot)):
            job['reuse_candidate'] = not job.get('redo_keyframe', False)
            self._run_keyframe(job, tick)
            project = self.load(job["project"])
            shot = project["shots"][index]
            if linked and job.get('stopped'):
                raise ComfyError('interrupted')
        project_snapshot = copy.deepcopy(project)
        job["label"] = f"Shot {index + 1}"
        selected_guard = None
        if shot["transition"] == "continue" and index > 0:
            previous = project["shots"][index - 1]
            if not previous.get("video"):
                raise RuntimeError(f"Shot {index + 1} continues shot {index}, which has no video yet")
            start = self._last_frame(project["id"], previous["video"])
            with self.lock:
                if linked and job.get('stopped'):
                    raise ComfyError('interrupted')
                fresh = self.load(project["id"])
                current = self._shot(fresh, shot["id"])
                add_take(current, "keyframe", start,
                         recipe={"kind": "continue", "lead": None, "anchor": None, "from": previous["id"],
                                 "steps": [f"Last frame of shot {index}"]})
                # Keep the local snapshot aligned with the derived take.  Its
                # recipe, rather than the previous opening frame's recipe,
                # determines which character references the video depends on.
                shot['takes'] = copy.deepcopy(current['takes'])
                shot['video'] = current.get('video')
                if linked:
                    selected_guard = (start, None,
                        copy.deepcopy((current_take(current, 'keyframe').get('review') or {}).get('director_review')), None)
                self.save(fresh)
        else:
            start = shot.get("keyframe")
            if not start:
                raise RuntimeError(f"Shot {index + 1} has no keyframe yet")
            if linked:
                selected_guard = (start, shot.get('video'),
                    copy.deepcopy((current_take(shot, 'keyframe').get('review') or {}).get('director_review')),
                    copy.deepcopy((current_take(shot, 'video').get('review') or {}).get('director_review')))
        shot["keyframe"] = start
        frame_take = current_take(shot, "keyframe")
        if not take_usable(project, frame_take) or not visual_inputs_match(frame_take.get("review", {}).get("of"), visual_inputs(project, shot)):
            job["label"] = f"Shot {index + 1} · checking opening frame"
            opening_review = (self._review_image(project, shot, start, tick, job=job) if linked
                              else self._review_image(project, shot, start, tick))
            with self.lock:
                fresh = self.load(project["id"])
                current = self._shot(fresh, shot["id"])
                for take in current.get("takes", {}).get("keyframe", []):
                    if take["name"] == start:
                        take["review"] = opening_review
                current.setdefault("quality", {})["keyframe"] = {"name": start, **opening_review}
                self.save(fresh)
            if opening_review["status"] != "passed" and not draft_mode(project):
                raise RuntimeError("Opening frame needs review: " + "; ".join(opening_review["findings"][:4]))
        fresh = self.load(project["id"])
        if not plan_usable(fresh) or video_inputs(fresh, self._shot(fresh, shot["id"])) != video_inputs(project, shot):
            raise RuntimeError("The shot changed during opening-frame review. Render again to use the latest direction.")
        motion_lead, motion_others = performing_cast(project, shot)
        prompt = director.motion_prompt(shot["action"], shot["camera_move"], shot.get("sound", ""),
                                        director.look_for_state(project["look"], review_requirements(project, shot, "start")["state"]),
                                        director._join(project.get("cast", ""), lead_identity(project)).rstrip(".") if motion_lead else "",
                                        shot["shot_size"], state_design(project),
                                        motion_lead, motion_others, shot.get("line", ""),
                                        shot.get("start_frame", ""), shot.get("end_state", ""))
        end_facts = review_requirements(project, shot, 'end')['state']
        visible_changes = {key:value for key,value in shot.get('state_changes', {}).items() if key in end_facts}
        prompt += " " + director.state_direction(review_requirements(project, shot, 'start')['state'], visible_changes)
        prompt += " " + director.cast_transition_direction(shot.get("start_cast"), shot.get("end_cast"))
        seed = take_seed(shot, "video")
        # the zoomed end frame also pins the subject to its first pose, so a shot with someone acting in it
        # comes out as a zooming still: only empty wide views get the guide
        guide = (director.CAMERA_PATHS.get(shot["camera_move"])
                 if shot.get("lead") is False and not others_in(project, shot)
                 and shot["shot_size"] in director.WIDE_SIZES else None)
        if shot.get("guide_end"):
            job["label"] = f"Shot {index + 1} · preparing guided ending"
            end, end_strength = self._ending_frame(project, shot, start, tick, job=job), 1.0
            shot["endframe"] = self._shot(self.load(project["id"]), shot["id"])["endframe"]
            job["label"] = f"Shot {index + 1} · rendering video"
        else:
            end, end_strength = (self._path_guide(project["id"], start, guide), guide[3]) if guide else (None, 1.0)
        def selection_state(current):
            return (current.get('keyframe'), current.get('video'),
                    (current_take(current, 'keyframe').get('review') or {}).get('director_review'),
                    (current_take(current, 'video').get('review') or {}).get('director_review'))
        guarded_inputs = None
        if linked:
            with self.lock:
                if job.get('stopped'):
                    raise ComfyError('interrupted')
                fresh = self.load(project['id'])
                current = self._shot(fresh, shot['id'])
                guarded_inputs = video_inputs(fresh, current)
                if selection_state(current) != selected_guard or guarded_inputs != video_inputs(project, shot):
                    raise RuntimeError('The shot changed before rendering. Your current selection was kept; render again.')
        graph = graphs.shot_graph(self._upload(project["id"], start), prompt, seed, project["aspect"],
                                  float(shot["seconds"]), f"open-cinema/{project['id']}/shot_{shot['id']}",
                                  end_image=end and self._upload(project["id"], end), end_strength=end_strength,
                                  performance=job.get("ai_mode", "normal"))
        files = self._run_for_job(graph, tick, job) if linked else self.comfy.run(graph, on_tick=tick)
        name = f"shot_{shot['id']}_{uuid.uuid4().hex[:6]}.mp4"
        self.comfy.download(files[0], self.path(project["id"]) / name)
        job["label"] = f"Shot {index + 1} · reviewing four video samples"
        if duration(self.path(project['id']) / name) <= 0:
            raise RuntimeError('Generated clip has no playable duration; regenerate this shot')
        # Keep a completed linked clip inspectable before the optional reviews,
        # without selecting it if Stop lands at a stage boundary.
        if linked:
            pending = director.review_result([{'category':'uncertain','code':'pending_review','severity':'warning',
                'message':'Visual checks are queued; this draft is not yet reviewed.'}])
            pending['of'] = video_inputs(project, shot)
            with self.lock:
                fresh = self.load(project['id'])
                current = self._shot(fresh, shot['id'])
                current.setdefault('takes', {}).setdefault('video', []).append({'name':name, 'review':pending,
                    'prompt':prompt, 'seed':seed, 'keyframe':start, 'performance_mode':job.get('ai_mode','normal'),
                    'of':{**video_inputs(project_snapshot, shot), 'keyframe':start}})
                self.save(fresh)
                if job.get('stopped'):
                    raise ComfyError('interrupted')
        if draft_mode(project):
            review = director.review_result([{'category':'uncertain', 'code':'pending_review', 'severity':'warning',
                'message':'Visual checks are queued; this draft is not yet reviewed.'}])
            review['of'] = video_inputs(project, shot)
        else:
            review = (self._review_video(project, shot, name, tick, job=job) if linked
                      else self._review_video(project, shot, name, tick))
        dialogue = speech.check(self.path(project['id']) / name, shot.get('line', '')) if not draft_mode(project) and shot.get('line', '').strip() else None
        with self.lock:
            if linked and job.get('stopped'):
                raise ComfyError('interrupted')
            if linked:
                fresh = self.load(project['id'])
                current = self._shot(fresh, shot['id'])
                if selection_state(current) != selected_guard or video_inputs(fresh, current) != guarded_inputs:
                    raise RuntimeError('The shot changed while rendering. The new clip and your current selection were kept; render again.')
            self._record_candidate(project["id"], shot["id"], "video", name, review, prompt=prompt, seed=seed, keyframe=start,
                                   performance_mode=job.get("ai_mode", "normal"),
                                   of={**video_inputs(project_snapshot, shot), "keyframe": start}, dialogue_review=dialogue)
        with self.lock:
            fresh = self.load(project['id'])
            selected = self._shot(fresh, shot['id'])
            if selected.get('video') == name and take_usable(fresh, current_take(selected, 'video')) and not video_stale(fresh, selected):
                job.setdefault('timing', {})['playable_at'] = time.time()
        if draft_mode(project):
            job['label'] = f'Shot {index + 1} · draft saved'
            with self.lock:
                if linked and job.get('stopped'):
                    raise ComfyError('interrupted')
                self.enqueue('review', project['id'], shot['id'], f'Checking shot {index + 1}',
                             review_policy=job.get('review_policy', 'draft'), candidate_name=name)

    def _run_master(self, job: dict[str, Any], tick) -> None:
        """1080p master: SeedVR2 each shot (a whole film doesn't fit in RAM), then cut them like the film."""
        project = self.load(job["project"])
        if not project.get("film"):
            raise RuntimeError("Cut the film before mastering it")
        if film_review(project)['stale']:
            raise RuntimeError('The cut changed. Create an updated cut before mastering it.')
        if not draft_mode(project) and film_review(project)['findings']:
            raise RuntimeError('Resolve the flagged shots before strict mastering')
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
                       title_clip=title_master, draft=bool(film_review(project)['findings']))
        with self.lock:
            project = self.load(job["project"])
            project["master"], project["master_of"] = name, project.get("film")
            self.save(project)

    def _run_stitch(self, job: dict[str, Any], tick) -> None:
        project = self.load(job["project"])
        if not plan_usable(project):
            raise RuntimeError("Review scene continuity before cutting the film")
        if not draft_mode(project) and any(not review_passed(current_take(s, "video")) or
               current_take(s, "video").get("review", {}).get("of") != video_inputs(project, s) for s in project["shots"]):
            raise RuntimeError("Every clip needs a current passing video review before the final cut")
        if any(story_stale(project, s) or frame_stale(project, s) or video_stale(project, s) for s in project["shots"]):
            raise RuntimeError("The script or staging changed. Render film to update affected shots before cutting.")
        videos = [s.get("video") for s in project["shots"]]
        if not videos or not all(videos):
            raise RuntimeError("Every shot needs a rendered video before the final cut")
        folder = self.path(project["id"])
        if any(not (folder / video).is_file() or duration(folder / video) <= 0 for video in videos):
            raise RuntimeError('A clip is missing or unreadable. Regenerate the affected shot before assembly.')
        name = f"film_{uuid.uuid4().hex[:6]}.mp4"
        _, _, width, height = graphs.ASPECTS[project["aspect"]]
        cut_from = film_inputs(project)
        marked_draft = bool(film_review(project)['findings'])
        self._assemble(project, [folder / v for v in videos], name, width, height, job, tick,
                       title_clip=self._title_clip(project), draft=marked_draft)
        wave = self._waveform(project["id"], name)
        with self.lock:
            project = self.load(job["project"])
            project["film"], project["film_of"], project["film_wave"] = name, cut_from, wave
            project['film_marked_draft'] = marked_draft
            self.save(project)

    def _run_review_reel(self, job: dict, tick) -> None:
        """A short playable reel of flagged current clips; full findings remain in Studio."""
        project = self.load(job['project'])
        if not project.get('film') or project.get('film_of') != film_inputs(project):
            raise RuntimeError('Create an up-to-date draft before building its review reel')
        flags = film_review(project)['findings']
        flagged_ids = {item['shot'] for item in flags if item.get('shot')}
        shots = [(index, shot) for index, shot in enumerate(project['shots'], 1) if shot['id'] in flagged_ids]
        if not shots:
            raise RuntimeError('There are no flagged shots in this cut')
        folder = self.path(project['id'])
        name = f'review_reel_{uuid.uuid4().hex[:6]}.mp4'
        args, filters, inputs = [], [], []
        for stream, (index, shot) in enumerate(shots):
            path = folder / shot['video']
            length = duration(path)
            if length <= 0:
                raise RuntimeError(f'Shot {index} is unreadable')
            segment = min(4.0, length)
            args += ['-ss', f'{max(0, (length-segment)/2):.3f}', '-t', f'{segment:.3f}', '-i', str(path)]
            filters.append(f'[{stream}:v]scale=640:352:force_original_aspect_ratio=decrease,pad=640:352:(ow-iw)/2:(oh-ih)/2,fps=24,setsar=1,setpts=PTS-STARTPTS,drawtext={drawtext_font()}:text=Shot {index:02d} - review:fontsize=20:fontcolor=white:box=1:boxcolor=black@0.65:boxborderw=8:x=16:y=16[v{stream}]')
            filters.append(f'[{stream}:a]aresample=48000,asetpts=PTS-STARTPTS[a{stream}]')
            inputs.append(f'[v{stream}][a{stream}]')
        filters.append(''.join(inputs) + f'concat=n={len(shots)}:v=1:a=1[v][a]')
        subprocess.run([ffmpeg(), '-y', '-loglevel', 'error', *args, '-filter_complex', ';'.join(filters),
                        '-map', '[v]', '-map', '[a]', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
                        '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-movflags', '+faststart', str(folder / name)], check=True)
        with self.lock:
            fresh = self.load(project['id'])
            if fresh.get('film') != project['film'] or film_inputs(fresh) != film_inputs(project):
                raise RuntimeError('The cut changed during reel assembly; build the updated reel again')
            fresh['review_reel'], fresh['review_reel_of'] = name, project['film']
            self.save(fresh)

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
                  title_clip: Path | None = None, draft: bool = False) -> None:
        """The cut: dressed shots, transitions, credits, finish, loudness — one ffmpeg pass."""
        dressed = self._dress(project, clips, job, tick)
        transitions = [s["transition"] for s in project["shots"]]
        if title_clip:  # the in-world title opens the film and dissolves into the first shot
            dressed, transitions = [title_clip] + dressed, ["cut", "dissolve"] + transitions[1:]
        credits = self._credits(project, clips[-1], width, height, tick)
        if credits:
            dressed, transitions = dressed + [credits], transitions + ["cut"]
        inputs, graph = cut_filter(dressed, transitions, bool(project.get("finish")), (width, height))
        output = '[v]'
        if draft:
            graph += f';[v]drawtext={drawtext_font()}:text=DRAFT - REVIEW PENDING:fontsize=20:fontcolor=white@0.8:box=1:boxcolor=black@0.45:boxborderw=6:x=16:y=h-th-16[draftv]'
            output = '[draftv]'
        subprocess.run([ffmpeg(), "-y", "-loglevel", "error", *inputs, "-filter_complex", graph,
                        "-map", output, "-map", "[a]", "-c:v", "libx264", "-crf", crf, "-preset", preset,
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
            self._queue_followup("cast", job["project"], None, "Casting the new lead")
        if repaint:  # a new world needs its own plate before any shot is made in it
            self._queue_followup("world", job["project"], None, "Painting the world", auto=True)
        if fill:
            self._queue_followup("write_shots", job["project"], None, "Writing shots for the new beats", mode="board",
                         count=int(job.get("count", 3)))
        if storyboard:  # a new story on an empty board: write its shots, which then get drawn
            self._queue_followup("write_shots", job["project"], None, "Writing the shots", mode="board",
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
            write_beats=write, characters=project.get("characters", ""), dialogue_mode=project.get("dialogue_mode", "auto"),
            idea=project.get("idea", ""))
        record = self.comfy.wait(self.comfy.submit(graph), on_tick=tick, timeout=900)
        if mode == "beat":
            return self._place_in_story(job, record)
        written = json.loads("".join(record["outputs"].get("shots", {}).get("text", ["[]"])) or "[]")
        if not written:
            raise RuntimeError("Gemma's reply had no shots in it")
        if project.get("dialogue_mode", "auto") == "silent":
            for shot in written:
                shot["line"] = ""
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
            if any(fresh.get(k) != project.get(k) for k in ("beats", "scene", "cast", "characters", "continuity", "look", "dialogue_mode", "idea")):
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
            if fresh["shots"][0].get("frame_source") == "previous_end":
                fresh["shots"][0]["frame_source"] = "storyboard"
            self.save(fresh)
        if not fresh.get("continuity_plan"):
            self._queue_followup("plan_continuity", job["project"], label="Planning continuity",
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
