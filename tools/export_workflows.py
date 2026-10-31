"""Write the app's ComfyUI graphs to workflows/ as API-format JSON.

    python tools/export_workflows.py

Load them in ComfyUI (drag the file onto the canvas) to run a single step by hand.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "custom_nodes" / "comfyui-open-cinema"))

import director  # noqa: E402
import graphs  # noqa: E402

SCENE = ("A storm-battered lighthouse on a black rock coast at dusk. The keeper is a woman in a yellow oilskin coat "
         "carrying a brass storm lantern.")
OUT = ROOT / "workflows"
OUT.mkdir(exist_ok=True)

CAST = "A woman in her forties with auburn hair, weathered face, yellow oilskin coat and hood."

examples = {
    "00_cast_portrait_hidream_o1.json": graphs.keyframe_graph(
        director.cast_prompt(CAST, SCENE, "Anamorphic blockbuster"), 7, "16:9", "open-cinema/cast",
        size=graphs.CAST_SIZE),
    "01_keyframe_hidream_o1.json": graphs.keyframe_graph(
        director.keyframe_prompt(SCENE, "She stands alone on the wet rocks as waves explode behind her.",
                                 "Extreme wide", "Anamorphic blockbuster"), 101, "16:9", "open-cinema/keyframe"),
    "02_coverage_qwen_image_edit_2511.json": graphs.coverage_graph(
        director.coverage_prompt("The keeper raises her lantern and squints out to sea.", "Close-up",
                                 "Anamorphic blockbuster", "yellow oilskin coat, brass lantern", has_cast=True),
        202, "establishing_keyframe.png", "open-cinema/coverage", "16:9", second_reference="cast_portrait.png"),
    "03_shot_ltx25_i2v_audio.json": graphs.shot_graph(
        "shot_keyframe.png", director.motion_prompt("The keeper raises her lantern and squints out to sea.",
                                                    "Push in (slow)", "rain hammering the hood, wind",
                                                    "Anamorphic blockbuster", CAST, "Close-up"),
        303, "16:9", 4, "open-cinema/shot"),
    "04_shot_ltx25_keyframe_to_keyframe.json": graphs.shot_graph(
        "start.png", director.motion_prompt("The camera glides from the rocks up to the lighthouse lamp.",
                                            "Crane up", "wind, waves"), 404, "16:9", 5, "open-cinema/k2k",
        end_image="end.png"),
}

# The same keyframe-to-keyframe shot, with the motion prompt written by the Open Cinema Shot node.
director_shot = graphs.shot_graph("start.png", "", 505, "16:9", 5, "open-cinema/director", end_image="end.png")
director_shot["40"] = graphs.node(
    "OpenCinemaShot", scene=SCENE, action="The camera rises from the rocks as the great lighthouse lamp blazes to life.",
    shot_size="Wide", camera_move="Crane up", look="Anamorphic blockbuster",
    sound="wind, crashing waves, the mechanical clunk of the lamp", continuity="", cast=CAST)
director_shot["9"]["inputs"]["text"] = ["40", 2]
examples["05_director_node_keyframe_to_keyframe.json"] = director_shot
examples["06_master_1080p_seedvr2.json"] = graphs.master_graph("film.mp4", "open-cinema/master")
examples["07_motion_title_over_shot.json"] = graphs.motion_overlay_graph(
    "shot.mp4", "open-cinema/title", "OpenCinemaTitleOverlay", title="The Colossus Pass",
    subtitle="A film made with open models", look="70mm epic", start=0.5, hold=3.2)
examples["08_motion_kinetic_cards.json"] = graphs.cards_graph(
    "Two stone kings.\nOne storm.\nOne last beacon.\nMade with open models | HiDream-O1 · Qwen-Image-Edit · LTX 2.5",
    "70mm epic", 1280, 704, "open-cinema/cards", 1.1)
examples["09_inworld_title_frame.json"] = graphs.title_frame_graph(
    director.title_frame_prompt("The Colossus Pass", director.TITLE_MATERIALS["70mm epic"]), 909,
    "establishing_keyframe.png", "open-cinema/inworld_title", "The Colossus Pass", "70mm epic")

for name, graph in examples.items():
    (OUT / name).write_text(json.dumps(graph, indent=2), encoding="utf-8")
    print("wrote", OUT / name)
