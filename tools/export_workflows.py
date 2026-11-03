"""Write the app's ComfyUI graphs to workflows/ as laid-out canvas workflows (and workflows/api/ as API JSON).

    python tools/export_workflows.py        # ComfyUI running on :8288 for the canvas versions

Drag a file onto the ComfyUI canvas to run that step by hand: groups show what each input is for.
"""

import json
import os
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
        director.cast_prompt(CAST, SCENE, LOOK), 7, "16:9", "open-cinema/cast", size=graphs.CAST_SIZE,
        negative=director.image_negative(LOOK)),
    "01_world_plate_hidream_o1.json": graphs.keyframe_graph(
        director.world_plate_prompt(SCENE, LOOK), 101, "16:9", "open-cinema/world",
        negative=director.image_negative(LOOK)),
    "02_shot_frame_qwen_image_edit_2511.json": graphs.coverage_graph(
        director.shot_prompt(CLOSE, "Medium close-up", LOOK, CONTINUITY, has_cast=True, camera_move="Orbit left",
                             world=SCENE.split(". ")[0], identity=IDENTITY, storyboard=True, world_reference=False),
        202, "oc_storyboard_sketch.jpg", "open-cinema/shot_frame", "16:9", second_reference="oc_lead_portrait.jpg"),
    # Retain the published filename for existing links; the canvas now uses independent HiDream composition.
    "14_storyboard_sketch_qwen_image_edit_2511.json": graphs.storyboard_graph(
        director.sketch_prompt("He holds the lens up to the sun on the glass terrace; the city drifts behind him.",
                               "Medium close-up", "Static", world=SCENE, cast=CAST, continuity=CONTINUITY),
        1414, "16:9", "open-cinema/storyboard", expected_cast=1),
    "03_shot_ltx25_i2v_audio.json": graphs.shot_graph(
        "oc_shot_keyframe.jpg", director.motion_prompt(ACTION, "Dolly in", "howling wind, crackling furnace", LOOK,
                                                       director._join(CAST, IDENTITY), "Wide", CONTINUITY),
        303, "16:9", 4, "open-cinema/shot"),
    "04_shot_ltx25_keyframe_to_keyframe.json": graphs.shot_graph(
        "oc_shot_keyframe.jpg", director.motion_prompt("The camera glides along the glass terrace toward the lead.",
                                                       "Truck right", "wind, glass chiming"), 404, "16:9", 5,
        "open-cinema/k2k", end_image="oc_world_plate.jpg"),
    "24_fast_shot_ltx25_i2v_audio.json": graphs.shot_graph(
        "oc_shot_keyframe.jpg", director.motion_prompt(ACTION, "Dolly in", "howling wind, crackling furnace", LOOK,
                                                       director._join(CAST, IDENTITY), "Wide", CONTINUITY),
        303, "16:9", 4, "open-cinema/fast_shot", performance="fast"),
    "25_fast_shot_ltx25_keyframe_to_keyframe.json": graphs.shot_graph(
        "oc_shot_keyframe.jpg", director.motion_prompt("The camera glides along the glass terrace toward the lead.",
                                                       "Truck right", "wind, glass chiming"), 404, "16:9", 5,
        "open-cinema/fast_k2k", end_image="oc_world_plate.jpg", performance="fast"),
}
examples["02_shot_frame_qwen_image_edit_2511.json"] = graphs.verify_cast(
    examples["02_shot_frame_qwen_image_edit_2511.json"], "15", 1)

# The same keyframe-to-keyframe shot, with the motion prompt written by the Open Cinema Shot node.
director_shot = graphs.shot_graph("oc_shot_keyframe.jpg", "", 505, "16:9", 5, "open-cinema/director",
                                  end_image="oc_world_plate.jpg")
director_shot["40"] = graphs.node(
    "OpenCinemaShot", scene=SCENE, action="The camera rises over the glass terrace as the furnace flares.",
    shot_size="Wide", camera_move="Crane up", look=LOOK, sound="wind, the roar of the furnace",
    continuity=CONTINUITY, cast=CAST)
director_shot["9"]["inputs"]["text"] = ["40", 2]
examples["05_director_node_keyframe_to_keyframe.json"] = director_shot
examples["06_master_1080p_seedvr2.json"] = graphs.master_graph("oc_example_film.mp4", "open-cinema/master")
examples["07_motion_title_over_shot.json"] = graphs.motion_overlay_graph(
    "oc_example_shot.mp4", "open-cinema/title", "OpenCinemaTitleOverlay", title="Glass Eye",
    subtitle="A film made with open models", look=LOOK, start=0.5, hold=3.2)
examples["08_motion_kinetic_cards.json"] = graphs.cards_graph(
    "A city of glass.\nA wind no one can see.\nOne lens to find it.\n"
    "Made with open models | HiDream-O1 · Qwen-Image-Edit · LTX 2.5 · SeedVR2 · Gemma 4", LOOK, 1280, 704,
    "open-cinema/cards", 1.1)
examples["10_ai_lead_writer_gemma4.json"] = graphs.lead_writer_graph("write", "Glass Eye", SCENE, LOOK, seed=7)
examples["11_ai_story_writer_gemma4.json"] = graphs.story_writer_graph(
    "everything", "a young glassblower in a floating desert city makes a lens that can see the wind", "", "", "", "",
    "", seed=7)
examples["09_inworld_title_frame.json"] = graphs.title_frame_graph(
    director.title_frame_prompt("Glass Eye", director.TITLE_MATERIALS.get(LOOK, "")), 909,
    "oc_world_plate.jpg", "open-cinema/inworld_title", "Glass Eye", LOOK)
examples["15_trailer_score_ltx25.json"] = graphs.score_graph(
    "oc_title_card.jpg", director.score_prompt(LOOK, "Glass Eye"), 1515, 18, "open-cinema/trailer_score")
examples["12_world_plate_people_check_gemma4.json"] = graphs.people_check_graph("oc_world_plate.jpg", director.PEOPLE_CHECK)
BEATS = ["The glass city drifts above the dunes at dawn, steam vents sighing",
         "The artisan's lens cracks in the furnace heat",
         "He finds a shard that bends the sunlight into rainbows",
         "On the terrace he raises the new lens to the sun",
         "Through it, the invisible desert wind becomes ribbons of light"]
examples["13_ai_shot_writer_gemma4.json"] = graphs.shot_writer_graph(
    "board", "Glass Eye", "In a sun-drenched glass city, a young artisan must craft a vision-lens capable of perceiving "
    "the invisible currents of the desert wind.", SCENE, LOOK, CAST, CONTINUITY, "", count=5, seed=7,
    beats=director.beat_list_text(BEATS), write_beats="1, 2, 3, 4, 5")

# What each canvas should say: groups (title, colour role, node ids), node titles and a note.
examples["16_scene_state_gemma4.json"] = graphs.continuity_graph(json.dumps({
    "scene": SCENE, "look": LOOK, "cast": CAST, "continuity": CONTINUITY,
    "shots": [{"index": 1, "action": CLOSE, "start_frame": "The lead holds the lens at chest height",
               "end_state": "The lead raises the lens to eye level"}]}), 1)
REVIEW_EXPECTED = json.dumps({"state": {}, "count": 1, "allowed_counts": [1], "people": {"lead": CAST}})
examples["17_frame_state_review_gemma4.json"] = graphs.visual_review_graph("oc_shot_keyframe.jpg", REVIEW_EXPECTED, LOOK, optimize=False)
examples["18_video_continuity_review_gemma4.json"] = graphs.video_review_graph(
    "oc_example_shot.mp4", REVIEW_EXPECTED, REVIEW_EXPECTED, REVIEW_EXPECTED, LOOK, optimize=False)

LEAD = ("The lead → Picture 2", "lead", ["16", "17"])
EDIT_TITLES = {"8": "Instruction (sees Picture 1 + 2)", "10": "Negative (empty)", "16": "Lead portrait",
               "17": "Scale lead", "7": "Scale Picture 1", "15": "Save frame"}
prop_graph = graphs.keyframe_graph("", 1919, "1:1", "open-cinema/prop")
prop_graph["prop_brief"] = graphs.node("OpenCinemaPropBrief", description="A folded brass compass with a round ivory dial and blue needle", state="closed", look=LOOK)
prop_graph["4"]["inputs"]["text"] = ["prop_brief", 0]
examples["19_prop_reference_hidream_o1.json"] = prop_graph
end_graph = graphs.coverage_graph("", 2020, "oc_shot_keyframe.jpg", "open-cinema/ending", "16:9", keep_layout=True)
end_graph["ending_brief"] = graphs.node("OpenCinemaEndingBrief", action="The glassblower lowers the lens", end_state="The lens rests on the workbench; his hands are empty", look=LOOK, state_json=json.dumps({"Lens held by":"nobody"}), design=CONTINUITY)
end_graph["8"]["inputs"]["prompt"] = ["ending_brief", 0]
examples["20_shot_ending_qwen_image_edit_2511.json"] = end_graph
repair_graph = graphs.coverage_graph("", 2121, "oc_shot_keyframe.jpg", "open-cinema/repair", "16:9", keep_layout=True, detailed=True)
repair_graph["repair_brief"] = graphs.node("OpenCinemaFrameRepairBrief", staging="The glassblower stands alone with the lens resting on the workbench", requirements_json=json.dumps({"state":{"Lens held by":"nobody"},"count":1,"visible_names":["Glassblower"]}), findings_json="[]")
repair_graph["8"]["inputs"]["prompt"] = ["repair_brief", 0]
examples["21_frame_repair_qwen_full.json"] = repair_graph
examples["22_following_shot_qwen_image_edit_2511.json"] = graphs.coverage_graph(
    director.following_frame_prompt("His hands hold the same lens above the workbench", "Close-up", CAST,
                                   {"Lens held by":"the lead"}),
    2222, "oc_shot_keyframe.jpg", "open-cinema/following_shot", "16:9")

examples["23_storyboard_from_approved_frame.json"] = graphs.frame_storyboard_graph(
    "oc_shot_keyframe.jpg", 2323, "16:9", "open-cinema/frame_storyboard", expected_cast=1)

ANNOTATE = {
    "23_storyboard_from_approved_frame.json": dict(note="## Align the board with an approved shot\nTrace an accepted opening frame into a monochrome planning drawing. This preserves the performed cast and prop state. Before any frame is approved, workflow 14 still plans independent compositions from text."),
    "22_following_shot_qwen_image_edit_2511.json": dict(note="## Carry the performance forward\nUse the preceding accepted video's final frame as Picture 1. The new shot follows its written staging and camera size while preserving cast, prop design and physical condition. The studio serializes shots with this source so the previous video exists before creating the next frame."),
    "21_frame_repair_qwen_full.json": dict(note="## Precise state repair\nThe full Qwen editor uses 40 steps and CFG 4 without Lightning. Supply only the required visible people and physical facts, then review the resulting image with 17 before animation. Repairs preserve the input viewpoint; the studio allows two attempts and retains failed candidates."),
    "19_prop_reference_hidream_o1.json": dict(note="## Prop reference\nDefine permanent object design and its current state. Inspect the result, then use it as an authoritative reference in shot frames. Use Qwen to edit an existing reference for another state without redesigning the object."),
    "20_shot_ending_qwen_image_edit_2511.json": dict(note="## Guided ending\nEdit the approved opening frame into the required final state, preserving cast and set. Review with 17 using end requirements, then connect the accepted result to the end image in 04. The studio performs these same steps when Guide motion with a reviewed end frame is enabled."),
    "16_scene_state_gemma4.json": dict(note="## Scene state\nSeparates immutable design from changing state. "
        "Each shot inherits all preceding changes. Review issues before rendering. Select the shot index on State Ledger; "
        "connect its state_before, state_changes, start_cast, end_cast, start_checks, end_checks and design outputs to the corresponding "
        "Open Cinema Shot inputs (design → continuity). The studio uses the same planner and state rules."),
    "17_frame_state_review_gemma4.json": dict(note="## Frame review\nInspect cast, style and expected visible facts before animation. "
        "Edit expected_json.state with the selected shot's visibly testable starting facts. Every requested fact needs evidence. "
        "Uncertain or malformed replies do not pass. This workflow reports evidence; the studio preserves rejected candidates without promoting them."),
    "18_video_continuity_review_gemma4.json": dict(note="## Video review\nFour independent samples: first frame, one third, two thirds, last frame. "
        "Start and end requirements include their states; middle requirements include unchanged facts and allowed cast counts. "
        "All four reviews must pass. Sampling is not a guarantee about unsampled frames. The studio blocks a new final cut when any clip lacks a current passing review."),
    "00_cast_portrait_hidream_o1.json": dict(
        titles={"9": "Save lead portrait"},
        note="## 1 · The lead\nHiDream-O1 paints a casting portrait from the lead description, on a plain grey "
             "backdrop.\n\nThis portrait is the identity source of truth: it goes in as **Picture 2** of every "
             "frame that has the lead."),
    "01_world_plate_hidream_o1.json": dict(
        titles={"9": "Save world plate"},
        note="## 2 · The world\nHiDream-O1 paints the film's world as an **empty location plate**: nobody is in "
             "it.\n\nIt goes in as **Picture 1** of every shot, so the only face any shot ever sees is the lead's "
             "(Picture 2). The studio checks the plate is empty with **12 · people check** and re-rolls if not."),
    "13_ai_shot_writer_gemma4.json": dict(
        titles={"2": "Shots brief (board · next · rewrite)", "3": "Gemma 4 12B (8-bit) writes the shots",
                "shots": "Shots (JSON for the studio)", "storyboard": "Storyboard"},
        note="## 0b · The shots\nGemma 4 12B (8-bit) turns the story **beats** (written by 11 · story writer) into shots: "
             "the beat each shot tells, what the camera sees, the shot size, the camera move, the length, the sound, "
             "and whether the lead is in it.\n\n**mode**: *board* writes one shot for each beat in `write_beats` "
             "(around the kept shots in `shots`), or `count` shots that start or continue the film; *next* writes "
             "the shot after `shots`; *rewrite* writes shot `index` again. Sizes and moves are snapped to the "
             "studio's presets. Each shot is then drawn by **14 · storyboard**."),
    "14_storyboard_sketch_qwen_image_edit_2511.json": dict(
        titles={"4": "Staging, cast, location and framing", "mono": "Enforce monochrome", "11": "Save storyboard"},
        note="## 2c · The storyboard\nHiDream-O1 composes a pencil drawing from written staging, without copying "
             "the world plate or the previous panel. Describe the frozen starting pose, all participants and prop "
             "ownership. The grayscale node guarantees monochrome pixels.\n\nThis drawing becomes **Picture 1** "
             "in 02 · shot frame. The legacy filename is retained for compatibility."),
    "12_world_plate_people_check_gemma4.json": dict(
        titles={"2": "World plate", "3": "Is anyone in it? (YES / NO)"},
        note="## 2b · People check\nGemma 4 12B (8-bit) looks at the world plate and answers YES or NO. A plate with "
             "anyone in it would put a second face into every shot, so the studio re-rolls it."),
    "02_shot_frame_qwen_image_edit_2511.json": dict(
        groups=[("The storyboard → Picture 1", "sketch", ["6", "7"]), LEAD],
        titles={**EDIT_TITLES, "8": "Instruction (sees Picture 1 + 2)", "6": "Storyboard drawing", "12": "Empty canvas"},
        note="## 3 · A shot\n**Picture 1** sets composition, blocking, subject scale and props. **Picture 2** "
             "supplies the lead's identity. Tighter shots omit the world image because its wide layout can "
             "overwhelm the storyboard. Wide shots may add it as Picture 3. Supporting cast are described in the prompt."),
    "06_master_1080p_seedvr2.json": dict(
        note="## 6 · The 1080p master\nSeedVR2 upscales the cut to 1080p. The example input is the first seconds "
             "of Glass Eye (`oc_example_film.mp4`)."),
    "07_motion_title_over_shot.json": dict(
        note="## 5 · The main title\nThe kinetic title is drawn over the opening shot in the film's look and "
             "colours (example: Glass Eye's shot 2, `oc_example_shot.mp4`)."),
    "15_trailer_score_ltx25.json": dict(
        note="## 7 · The trailer score\nLTX 2.5 renders one long, small shot from the film's dark title card "
             "(`oc_title_card.jpg`): with nothing moving in frame, its audio comes out as music. The studio keeps "
             "only the sound and cuts the trailer's cards and shots on its hits."),
    "03_shot_ltx25_i2v_audio.json": dict(
        note="## 4 · Motion\nLTX 2.5 animates a frame into a shot with sound, in two stages (half resolution, then "
             "a x2 latent upscale)."),
    "24_fast_shot_ltx25_i2v_audio.json": dict(
        note="## Fast motion preview\nLTX 2.5 runs a single distilled pass with synchronized audio at half the standard width and height (640×352 for 16:9). This is a lower-detail draft; the studio scales mixed-resolution shots to the cut size. No additional model is required."),
    "25_fast_shot_ltx25_keyframe_to_keyframe.json": dict(
        note="## Fast guided motion preview\nSingle-stage LTX 2.5 with starting and ending image guides and synchronized audio. Output is half the standard width and height; use workflow 04 for standard-quality guided motion."),
}

def install_into_runtime() -> None:
    """The studio's own ComfyUI: example inputs go to its input folder, canvases to its Workflows sidebar."""
    import shutil
    inputs = Path(os.environ.get('COMFYUI_INPUT_DIR', ROOT / 'runtime/comfy-input')).expanduser()
    user = Path(os.environ.get('COMFYUI_USER_DIR', ROOT / 'runtime/comfy-user')).expanduser()
    sidebar = user / 'default' / 'workflows' / 'open-cinema'
    if not inputs.parent.is_dir():
        return
    inputs.mkdir(exist_ok=True)
    sidebar.mkdir(parents=True, exist_ok=True)
    for example in [*(OUT / "inputs").glob("*.jpg"), *(OUT / "inputs").glob("*.mp4")]:
        shutil.copy2(example, inputs / example.name)
    for flow in OUT.glob("*.json"):
        shutil.copy2(flow, sidebar / flow.name)
    print("installed into", sidebar)


info = None
try:
    info = canvas.object_info()
except OSError:
    print("ComfyUI object_info unavailable (set COMFYUI_URL for another endpoint); only API versions are written")
(OUT / "api").mkdir(exist_ok=True)
for name, graph in sorted(examples.items()):
    (OUT / "api" / name).write_text(json.dumps(graph, indent=2), encoding="utf-8")
    if info:
        annotation = dict(ANNOTATE.get(name, {}))
        writers = [key for key, value in graph.items() if value['class_type'] == 'OpenCinemaWriter']
        if writers:
            annotation['titles'] = {**annotation.get('titles', {}), **{key: 'AI mode · Normal 12B / Fast E4B' for key in writers}}
            annotation['note'] = annotation.get('note', '') + '\n\nAI mode: Normal uses Gemma 4 12B at 8-bit; Fast uses E4B. Change the Open Cinema Writer mode widget. Image and video models stay the same. Cast-review findings retain the saved candidate; inspect it before using it downstream.'
        (OUT / name).write_text(json.dumps(canvas.to_canvas(graph, info, **annotation), indent=1),
                                encoding="utf-8")
    print("wrote", name)
if info:
    install_into_runtime()
