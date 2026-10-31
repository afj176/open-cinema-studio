"""Write the app's ComfyUI graphs to workflows/ as laid-out canvas workflows (and workflows/api/ as API JSON).

    python tools/export_workflows.py        # ComfyUI running on :8288 for the canvas versions

Drag a file onto the ComfyUI canvas to run that step by hand: groups show what each input is for.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "custom_nodes" / "comfyui-open-cinema"))
sys.path.insert(0, str(ROOT / "tools"))

import canvas  # noqa: E402
import director  # noqa: E402
import graphs  # noqa: E402

# The example film is Glass Eye, so prompts match the images shipped in workflows/inputs/.
SCENE = ("The city drifts above a sea of ochre sand, structures of blown, iridescent glass clinging to massive, "
         "slow-moving buoyancy platforms. Harsh, bleached sunlight refracts through crystalline spires and colossal, "
         "dormant steam vents.")
OUT = ROOT / "workflows"
OUT.mkdir(exist_ok=True)

CAST = ("Slender build, early twenties, sharp cheekbones framed by dark, tightly braided hair. He wears a tunic of deep "
        "indigo linen cinched with a leather sash. He clutches a delicate, glowing crucible.")
CONTINUITY = "Thin build, indigo linen, dark braids, glowing crucible"
IDENTITY = ("Medium brown skin, oval face with defined jawline, dark brown eyes, black braids, early 20s, "
            "slender build")
LOOK = "Golden hour"
ACTION = "The young glassblower lifts a molten lens toward the sun as wind whips sand across the glass terrace."
CLOSE = "Close on his hands turning the glowing lens; light fractures into rainbows across his face."

examples = {
    "00_cast_portrait_hidream_o1.json": graphs.keyframe_graph(
        director.cast_prompt(CAST, SCENE, LOOK), 7, "16:9", "open-cinema/cast", size=graphs.CAST_SIZE),
    "01_keyframe_hidream_o1.json": graphs.keyframe_graph(
        director.keyframe_prompt(director._join(SCENE, "The lead: " + IDENTITY + ", " + CONTINUITY), ACTION, "Wide",
                                 LOOK, "Dolly in"), 101, "16:9", "open-cinema/keyframe"),
    "02_coverage_qwen_image_edit_2511.json": graphs.coverage_graph(
        director.coverage_prompt(CLOSE, "Medium close-up", LOOK, CONTINUITY, has_cast=True, camera_move="Orbit left",
                                 world=SCENE.split(". ")[0], identity=IDENTITY),
        202, "oc_anchor_frame.jpg", "open-cinema/coverage", "16:9", second_reference="oc_lead_portrait.jpg"),
    "03_shot_ltx25_i2v_audio.json": graphs.shot_graph(
        "oc_shot_keyframe.jpg", director.motion_prompt(ACTION, "Dolly in", "howling wind, crackling furnace", LOOK,
                                                       director._join(CAST, IDENTITY), "Wide", CONTINUITY),
        303, "16:9", 4, "open-cinema/shot"),
    "04_shot_ltx25_keyframe_to_keyframe.json": graphs.shot_graph(
        "oc_shot_keyframe.jpg", director.motion_prompt("The camera glides along the glass terrace toward the lead.",
                                                       "Truck right", "wind, glass chiming"), 404, "16:9", 5,
        "open-cinema/k2k", end_image="oc_hidream_frame.jpg"),
}

# The same keyframe-to-keyframe shot, with the motion prompt written by the Open Cinema Shot node.
director_shot = graphs.shot_graph("oc_shot_keyframe.jpg", "", 505, "16:9", 5, "open-cinema/director",
                                  end_image="oc_hidream_frame.jpg")
director_shot["40"] = graphs.node(
    "OpenCinemaShot", scene=SCENE, action="The camera rises over the glass terrace as the furnace flares.",
    shot_size="Wide", camera_move="Crane up", look=LOOK, sound="wind, the roar of the furnace",
    continuity=CONTINUITY, cast=CAST)
director_shot["9"]["inputs"]["text"] = ["40", 2]
examples["05_director_node_keyframe_to_keyframe.json"] = director_shot
examples["06_master_1080p_seedvr2.json"] = graphs.master_graph("film.mp4", "open-cinema/master")
examples["07_motion_title_over_shot.json"] = graphs.motion_overlay_graph(
    "shot.mp4", "open-cinema/title", "OpenCinemaTitleOverlay", title="The Colossus Pass",
    subtitle="A film made with open models", look="70mm epic", start=0.5, hold=3.2)
examples["08_motion_kinetic_cards.json"] = graphs.cards_graph(
    "Two stone kings.\nOne storm.\nOne last beacon.\nMade with open models | HiDream-O1 · Qwen-Image-Edit · LTX 2.5",
    "70mm epic", 1280, 704, "open-cinema/cards", 1.1)
examples["10_ai_lead_writer_gemma4.json"] = graphs.lead_writer_graph(
    "write", "The Colossus Pass", SCENE, "70mm epic", seed=7)
examples["11_ai_story_writer_gemma4.json"] = graphs.story_writer_graph(
    "everything", "two stone kings guard the last mountain pass before a storm", "", "", "", "", "", seed=7)
examples["09_inworld_title_frame.json"] = graphs.title_frame_graph(
    director.title_frame_prompt("The Colossus Pass", director.TITLE_MATERIALS["70mm epic"]), 909,
    "oc_anchor_frame.jpg", "open-cinema/inworld_title", "The Colossus Pass", "70mm epic")

examples["12_identity_pass_qwen_edit_2511.json"] = graphs.identity_graph(
    director.identity_prompt(CONTINUITY, IDENTITY), 1212, "oc_hidream_frame.jpg", "oc_lead_portrait.jpg",
    "open-cinema/identity", "16:9")

# What each canvas should say: groups (title, colour role, node ids), node titles and a note.
LEAD = ("The lead → Picture 2", "lead", ["16", "17"])
EDIT_TITLES = {"8": "Instruction (sees Picture 1 + 2)", "10": "Negative (empty)", "16": "Lead portrait",
               "17": "Scale lead", "7": "Scale Picture 1", "15": "Save frame"}
ANNOTATE = {
    "00_cast_portrait_hidream_o1.json": dict(
        titles={"9": "Save lead portrait"},
        note="## 1 · The lead\nHiDream-O1 paints a casting portrait from the lead description, on a plain grey "
             "backdrop.\n\nThis portrait is the identity source of truth: it goes in as **Picture 2** of every "
             "frame that has the lead."),
    "01_keyframe_hidream_o1.json": dict(
        note="## 2a · World frame\nHiDream-O1 paints the anchor shot from text: framing, action, world and look. "
             "It can't see the lead's portrait, so the studio follows it with **12 · identity pass**."),
    "12_identity_pass_qwen_edit_2511.json": dict(
        groups=[("HiDream frame → Picture 1", "anchor", ["6", "7"]), LEAD],
        titles={**EDIT_TITLES, "6": "HiDream world frame", "12": "Start from Picture 1 (keeps its layout)"},
        note="## 2b · Identity pass\nQwen-Image-Edit-2511 recasts the person in HiDream's frame (**Picture 1**) "
             "as the lead (**Picture 2**), keeping composition, pose, light and world.\n\nThe result is the "
             "**anchor**: every other shot takes its world and light from it."),
    "02_coverage_qwen_image_edit_2511.json": dict(
        groups=[("Anchor frame → Picture 1", "anchor", ["6", "7"]), LEAD],
        titles={**EDIT_TITLES, "6": "Anchor frame", "12": "Empty canvas (new composition)"},
        note="## 3 · Coverage shot\nA new camera setup of the same film. **Picture 1** is the anchor frame (world, "
             "light, grade); **Picture 2** is the lead (face, hair, wardrobe).\n\nIt samples onto an empty canvas so "
             "the camera really moves instead of copying Picture 1's layout."),
    "03_shot_ltx25_i2v_audio.json": dict(
        note="## 4 · Motion\nLTX 2.5 animates a frame into a shot with sound, in two stages (half resolution, then "
             "a x2 latent upscale)."),
}

def install_into_runtime() -> None:
    """The studio's own ComfyUI: example inputs go to its input folder, canvases to its Workflows sidebar."""
    import shutil
    inputs, sidebar = ROOT / "runtime" / "comfy-input", ROOT / "runtime" / "comfy-user" / "default" / "workflows" / "open-cinema"
    if not inputs.parent.is_dir():
        return
    inputs.mkdir(exist_ok=True)
    sidebar.mkdir(parents=True, exist_ok=True)
    for image in (OUT / "inputs").glob("*.jpg"):
        shutil.copy2(image, inputs / image.name)
    for flow in OUT.glob("*.json"):
        shutil.copy2(flow, sidebar / flow.name)
    print("installed into", sidebar)


info = None
try:
    info = canvas.object_info()
except OSError:
    print("ComfyUI isn't running on :8288, so only the API versions are written")
(OUT / "api").mkdir(exist_ok=True)
for name, graph in sorted(examples.items()):
    (OUT / "api" / name).write_text(json.dumps(graph, indent=2), encoding="utf-8")
    if info:
        (OUT / name).write_text(json.dumps(canvas.to_canvas(graph, info, **ANNOTATE.get(name, {})), indent=1),
                                encoding="utf-8")
    print("wrote", name)
if info:
    install_into_runtime()
