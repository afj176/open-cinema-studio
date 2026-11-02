"""Create an isolated known-bad clip fixture and calibrate live state review on saved images."""
import copy
import argparse
import os
import json
import shutil
import sys
from pathlib import Path

from qa_story_staging import api

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import studio
from comfy import Comfy


def fixture(source_id):
    source = api("projects/" + source_id)
    original = source["shots"][3]
    shot_fields = {k: original.get(k, "") for k in studio.director.SHOT_FIELDS}
    shot_fields.update(beat=1, action="Mina passes the red lantern to Tavi", start_frame="Mina and Tavi stand together; Mina holds the lantern",
                       end_state="Tavi holds the lantern", lead=True, others="Tavi")
    project = api("projects", {"title": "Scratch - continuity rejection calibration",
                  **{k: source[k] for k in ("scene", "cast", "continuity", "aspect")},
                  "look": "2D illustrated animation", "shots": [shot_fields]})
    folder = ROOT / "projects" / project["id"]
    for name in (original["keyframe"], original["video"], source["reference"]):
        shutil.copy2(ROOT / "projects" / source["id"] / name, folder / name)
    project.update(reference=source["reference"], characters=source["characters"], auto_render=False,
                   beats=["Mina gives the lantern to Tavi"], scene_state={"Lantern · held by": "Mina", "Lantern · light": "lit"})
    shot = project["shots"][0]
    shot.update(keyframe=original["keyframe"], video=original["video"], beat_source=project["beats"][0],
                state_changes={"Lantern · held by": "Tavi"}, start_cast=["Mina", "Tavi"], end_cast=["Mina", "Tavi"],
                start_checks=["Lantern · held by", "Lantern · light"], end_checks=["Lantern · held by", "Lantern · light"])
    project["continuity_plan"] = {"of": studio.continuity_inputs(project), "issues": [], "design": "One red paper lantern; Mina wears yellow; Tavi wears green and a red scarf"}
    project["continuity_rev"] = 1
    shot["takes"] = {"keyframe": [{"name": shot["keyframe"], "recipe": {"kind": "upload"}}],
                     "video": [{"name": shot["video"], "keyframe": shot["keyframe"], "of": studio.video_inputs(project, shot)}]}
    (folder / "project.json").write_text(json.dumps(project, indent=2), encoding="utf-8")
    output = ROOT / "runtime" / "continuity-qa"
    output.mkdir(exist_ok=True)
    (output / "project.txt").write_text(project["id"])
    print(project["id"], flush=True)
    print(api(f"projects/{project['id']}/shots/{shot['id']}/review", {}), flush=True)


def calibrate():
    output = ROOT / "runtime" / "continuity-qa"
    project_id = (output / "project.txt").read_text().strip()
    project = api("projects/" + project_id)
    shot = project["shots"][0]
    client = Comfy(os.environ.get('COMFYUI_URL', 'http://127.0.0.1:8288'))
    uploaded = client.upload(ROOT / "projects" / project_id / shot["keyframe"], "oc_qa_review.png")
    results = {}
    for label, light in (("lit_control", "lit"), ("unlit_mismatch", "unlit")):
        expected = {"state": {"Lantern · light": light}, "count": 2, "allowed_counts": [2],
                    "people": {"lead": project["cast"], **studio.cast_list(project)}}
        graph = studio.graphs.visual_review_graph(uploaded, json.dumps(expected), project["look"])
        record = client.wait(client.submit(graph), timeout=900)
        results[label] = json.loads("".join(record["outputs"]["review"]["text"]))
        print(label, json.dumps(results[label]), flush=True)
    (output / "image-calibration.json").write_text(json.dumps(results, indent=2), encoding="utf-8")


def production(source_id):
    source = api("projects/" + source_id)
    beats = ["Mina lifts an unlit red paper lantern from the stream bank.",
             "Mina lights the candle inside the lantern.", "Mina passes the lit lantern to Tavi beside the bridge."]
    staging = [
        ("Mina bends and lifts the unlit lantern by its black top handle", "Mina stands beside the stream; the unlit lantern rests on a flat rock, her empty hand reaches toward its top handle", "Mina holds the unlit lantern at waist height", ""),
        ("Mina lights the small candle through the open side of the lantern", "Mina holds the unlit lantern by its black top handle in her left hand, a burning match in her right hand beside the candle opening", "The candle inside the lantern burns and casts a warm amber glow; Mina still holds the top handle", ""),
        ("Mina passes the lantern handle into Tavi's open hand", "Mina on the left holds the lit lantern between them; Tavi on the right already stands beside her with an open hand under its top handle", "Tavi holds the lantern by its top handle; Mina's hands are empty", "Tavi"),
    ]
    shots = [{"beat": i+1, "action": a, "start_frame": start, "end_state": end, "others": others,
              "lead": True, "shot_size": "Medium", "camera_move": "Static", "seconds": 5,
              "sound": "Quiet stream and paper rustling", "line": "", "transition": "cut"}
             for i, (a, start, end, others) in enumerate(staging)]
    project = api("projects", {"title": "Scratch - state-aware paper-cut test", "shots": shots,
                              **{k: source[k] for k in ("scene", "look", "cast", "continuity", "aspect")}})
    folder = ROOT / "projects" / project["id"]
    for filename in (source["reference"], source["world"]["plate"]):
        shutil.copy2(ROOT / "projects" / source["id"] / filename, folder / filename)
    project.update({k: source[k] for k in ("reference", "world", "lead_identity", "lead_identity_of", "characters")})
    project.update(beats=beats, auto_render=False)
    for shot, beat in zip(project["shots"], beats):
        shot["beat_source"] = beat
    (folder / "project.json").write_text(json.dumps(project, indent=2), encoding="utf-8")
    output = ROOT / 'runtime' / 'continuity-qa'
    output.mkdir(parents=True, exist_ok=True)
    (output / "production-project.txt").write_text(project["id"], encoding='utf-8')
    print(project["id"], flush=True)
    print(api(f"projects/{project['id']}/plan-continuity", {}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['fixture', 'production', 'calibrate'])
    parser.add_argument('--source-project', help='Existing source film containing the expected lantern fixture assets')
    args = parser.parse_args()
    if args.mode != 'calibrate' and not args.source_project:
        parser.error('--source-project is required; no private fixture is assumed')
    if args.mode == 'calibrate':
        calibrate()
    else:
        (fixture if args.mode == 'fixture' else production)(args.source_project)
