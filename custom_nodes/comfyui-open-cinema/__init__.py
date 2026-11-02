"""Open Cinema: camera-direction nodes for building multi-shot films in ComfyUI."""

WEB_DIRECTORY = './web'

from .director import (CAMERA_MOVES, LOOKS, SHOT_SIZES, cast_prompt, motion_prompt, shot_prompt,
                       world_plate_prompt)


class OpenCinemaShot:
    """One shot of a shot list: the world plate, the shot frame (world plate = Picture 1, lead = Picture 2),
    the motion, and the lead's casting portrait prompts."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "scene": ("STRING", {"multiline": True, "default": "A rain-soaked neon alley at night."}),
            "action": ("STRING", {"multiline": True, "default": "A detective in a trench coat lights a cigarette."}),
            "shot_size": (list(SHOT_SIZES), {"default": "Medium"}),
            "camera_move": (list(CAMERA_MOVES), {"default": "Dolly in"}),
            "look": (list(LOOKS), {"default": "Anamorphic blockbuster"}),
            "sound": ("STRING", {"multiline": True, "default": "rain on metal, distant sirens"}),
        }, "optional": {
            "continuity": ("STRING", {"multiline": True, "default": ""}),
            "lead_in_shot": ("BOOLEAN", {"default": True}),
            "cast": ("STRING", {"multiline": True, "default": "",
                                "tooltip": "Describe the lead. When set, the shot prompt expects the lead's "
                                           "portrait as Picture 2."}),
            "others": ("STRING", {"multiline": True, "default": "",
                                  "tooltip": "Everyone else in the shot, with what they look like, e.g. "
                                             "'Mara (an old woman in a grey shawl)'."}),
            "line": ("STRING", {"default": "", "tooltip": 'What is said aloud: Speaker: "words" (Lead or a name).'}),
            "custom_look": ("STRING", {"multiline": True, "default": "",
                                       "tooltip": "Optional free-form film look; overrides the preset for all prompts."}),
            "start_frame": ("STRING", {"multiline": True, "default": ""}),
            "end_state": ("STRING", {"multiline": True, "default": ""}),
            "storyboard": ("BOOLEAN", {"default": False,
                                       "tooltip": "When enabled: Picture 1 = storyboard, Picture 2 = lead if present, last picture = world."}),
            "world_reference": ("BOOLEAN", {"default": True,
                                             "tooltip": "Disable for tighter storyboard shots and omit the world image; its wide layout can overwhelm blocking."}),
            "state_before": ("STRING", {"multiline": True, "default": "{}"}),
            "state_changes": ("STRING", {"multiline": True, "default": "{}"}),
            "start_cast": ("STRING", {"default": "null"}),
            "end_cast": ("STRING", {"default": "null"}),
            "start_checks": ("STRING", {"default": "null"}),
            "end_checks": ("STRING", {"default": "null"}),
        }}

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("world_plate_prompt", "shot_prompt", "motion_prompt", "cast_prompt")
    FUNCTION = "build"
    CATEGORY = "Open Cinema"

    def build(self, scene, action, shot_size, camera_move, look, sound, continuity="", lead_in_shot=True, cast="",
              others="", line="", custom_look="", start_frame="", end_state="", storyboard=False, world_reference=True,
              state_before="{}", state_changes="{}", start_cast="null", end_cast="null",
              start_checks="null", end_checks="null"):
        import json
        from .director import state_map, state_direction, cast_transition_direction, look_for_state
        look = custom_look.strip() or look
        before = state_map(json.loads(state_before))
        changes = state_map(json.loads(state_changes))
        frame_look = look_for_state(look, before)
        first_keys, last_keys = json.loads(start_checks), json.loads(end_checks)
        motion_keys = list(dict.fromkeys(first_keys + last_keys)) if first_keys is not None and last_keys is not None else None
        opening = " " + state_direction(before, visible_keys=first_keys) if before else ""
        movement = " " + state_direction(before, changes, motion_keys) if before else ""
        if start_cast != "null" or end_cast != "null":
            movement += " " + cast_transition_direction(json.loads(start_cast), json.loads(end_cast))
        return (world_plate_prompt(scene, look),
                shot_prompt(action, shot_size, frame_look, continuity, has_cast=bool(cast.strip()) and lead_in_shot,
                            camera_move=camera_move, lead=lead_in_shot, world=scene.split(". ")[0], others=others,
                            line=line, start_frame=start_frame, storyboard=storyboard, world_reference=world_reference) + opening,
                motion_prompt(action, camera_move, sound, frame_look, cast, shot_size, continuity, lead_in_shot, others, line,
                              start_frame, end_state) + movement,
                cast_prompt(cast, scene, look))


class OpenCinemaShotLength:
    """Seconds to an LTX-valid frame count (8n+1)."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"seconds": ("FLOAT", {"default": 4.0, "min": 1.0, "max": 20.0, "step": 0.5}),
                             "fps": ("INT", {"default": 24, "min": 8, "max": 60})}}

    RETURN_TYPES = ("INT", "FLOAT")
    RETURN_NAMES = ("frames", "fps")
    FUNCTION = "frames"
    CATEGORY = "Open Cinema"

    def frames(self, seconds, fps):
        return (max(9, round(seconds * fps / 8) * 8 + 1), float(fps))


class OpenCinemaMonochrome:
    """Storyboard drawings have an actual grayscale pixel contract, independent of model compliance."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"images": ("IMAGE",)}}

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "render"
    CATEGORY = "Open Cinema"

    def render(self, images):
        grey = images[..., :1] * 0.2126 + images[..., 1:2] * 0.7152 + images[..., 2:3] * 0.0722
        return (grey.repeat(1, 1, 1, 3),)


class OpenCinemaWriter:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"mode": (["normal", "fast"], {"default": "normal",
            "tooltip": "Normal: Gemma 4 12B INT8. Fast: Gemma 4 E4B FP8. No silent fallback."})}}
    RETURN_TYPES = ("CLIP",)
    FUNCTION = "load"
    CATEGORY = "Open Cinema/Writing"

    def load(self, mode):
        from nodes import CLIPLoader
        models = {"normal": "gemma4_12b_int8_convrot.safetensors", "fast": "gemma4_e4b_it_fp8_scaled.safetensors"}
        if mode not in models:
            raise ValueError("Choose normal or fast")
        return CLIPLoader().load_clip(models[mode], type="stable_diffusion", device="default")


class OpenCinemaCastReview:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"observed": ("STRING", {"forceInput": True}),
                             "expected": ("INT", {"default": 1, "min": 0, "max": 50})}}
    RETURN_TYPES = ("STRING",)
    FUNCTION = "review"
    CATEGORY = "Open Cinema/Continuity"

    def review(self, observed, expected):
        import json, re
        from .director import REVIEW_VERSION
        answer = observed.strip().rstrip(".")
        count = int(answer) if re.fullmatch(r"\d+", answer) else None
        findings = [] if count == expected else [f"Expected {expected} visible characters; the reviewer counted {count if count is not None else 'an uncertain number'}. Inspect the drawing before using it."]
        return (json.dumps({"version": REVIEW_VERSION, "status": "needs_review" if findings else "passed",
                           "findings": findings, "expected_count": expected, "observed_count": count}),)


class OpenCinemaValidateCast:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"images": ("IMAGE",), "observed": ("STRING", {"forceInput": True}),
                             "expected": ("INT", {"default": 1, "min": 0, "max": 50})}}

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "validate"
    CATEGORY = "Open Cinema"

    def validate(self, images, observed, expected):
        import re
        answer = observed.strip().rstrip(".")
        if not re.fullmatch(r"\d+", answer):
            raise ValueError("Cast count could not be verified: " + observed[:120])
        if int(answer) != expected:
            raise ValueError(f"Cast count mismatch: expected {expected}, observed {answer}. Redraw this shot.")
        return (images,)


# ---------------------------------------------------------------- motion graphics

def _to_numpy(images):
    return images.detach().cpu().float().numpy()


def _to_tensor(frames):
    import torch
    return torch.from_numpy(frames.astype("float32"))


def _split_lines(text):
    """'LABEL | TEXT' per line; a line without a bar is just TEXT."""
    texts, labels = [], []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        label, bar, body = raw.partition("|")
        texts.append((body if bar else label).strip())
        labels.append(label.strip() if bar else "")
    return texts, labels


LOOK_INPUT = ("STRING", {"default": "70mm epic", "multiline": True,
                          "tooltip": "A preset name or a free-form film look. Custom looks use default graphics styling unless a palette is provided."})
PALETTE_INPUT = ("STRING", {"default": "",
                            "tooltip": "Optional custom colours 'bg,ink,accent,glow' (hex); empty uses the look's palette"})


class OpenCinemaTitleOverlay:
    """Main title over footage: glowing line streak, title slam on impact, typed subtitle, HUD."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "images": ("IMAGE",), "fps": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 120.0}),
            "title": ("STRING", {"default": "The Colossus Pass"}),
            "subtitle": ("STRING", {"default": "A film made with open models"}),
            "look": LOOK_INPUT,
            "start": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 10.0, "step": 0.05}),
            "hold": ("FLOAT", {"default": 3.2, "min": 0.5, "max": 20.0, "step": 0.1}),
        }, "optional": {"palette": PALETTE_INPUT}}

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "render"
    CATEGORY = "Open Cinema/Motion"

    def render(self, images, fps, title, subtitle, look, start, hold, palette=""):
        from . import motion
        return (_to_tensor(motion.title_overlay(_to_numpy(images), fps, title, subtitle, look, start, hold,
                                                palette=palette)),)


class OpenCinemaShotStamp:
    """HUD slate on a shot: corner brackets and a typed label with one highlighted phrase."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "images": ("IMAGE",), "fps": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 120.0}),
            "text": ("STRING", {"default": "SHOT 03 · LOW ANGLE · TILT UP"}),
            "highlight": ("STRING", {"default": "TILT UP"}),
            "look": LOOK_INPUT,
        }, "optional": {"palette": PALETTE_INPUT}}

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "render"
    CATEGORY = "Open Cinema/Motion"

    def render(self, images, fps, text, highlight, look, palette=""):
        from . import motion
        return (_to_tensor(motion.stamp_overlay(_to_numpy(images), fps, text, highlight, look, palette=palette)),)


class OpenCinemaCards:
    """Full-frame kinetic type cards, hard cut on each line. One line per card: 'LABEL | TEXT'."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "lines": ("STRING", {"multiline": True, "default": "Two kings.\nOne beacon.\nThe Colossus Pass"}),
            "look": LOOK_INPUT,
            "width": ("INT", {"default": 1280, "min": 256, "max": 4096, "step": 16}),
            "height": ("INT", {"default": 704, "min": 256, "max": 4096, "step": 16}),
            "fps": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 120.0}),
            "seconds_per_card": ("FLOAT", {"default": 1.1, "min": 0.3, "max": 10.0, "step": 0.05}),
            "seed": ("INT", {"default": 5, "min": 0, "max": 2**31 - 1}),
        }, "optional": {"palette": PALETTE_INPUT}}

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "render"
    CATEGORY = "Open Cinema/Motion"

    def render(self, lines, look, width, height, fps, seconds_per_card, seed, palette=""):
        from . import motion
        texts, labels = _split_lines(lines)
        if not texts:
            raise ValueError("Open Cinema Cards needs at least one line of text")
        frames = motion.cards(texts, fps, width, height, look, seconds_per_card,
                              labels if any(labels) else None, seed, palette=palette)
        return (_to_tensor(frames),)


class OpenCinemaTitlePreview:
    """One representative title frame in a look, for quick previews."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"title": ("STRING", {"default": "The Colossus Pass"}), "look": LOOK_INPUT,
                             "width": ("INT", {"default": 1280, "min": 256, "max": 4096, "step": 16}),
                             "height": ("INT", {"default": 704, "min": 256, "max": 4096, "step": 16})},
                "optional": {"palette": PALETTE_INPUT}}

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "render"
    CATEGORY = "Open Cinema/Motion"

    def render(self, title, look, width, height, palette=""):
        import numpy as np
        from . import motion
        frame = np.asarray(motion.preview(look, title, width, height, palette=palette), dtype="float32")[None] / 255.0
        return (_to_tensor(frame),)


class OpenCinemaTypeSheet:
    """The title set in the look's typeface on a plain sheet: a spelling-perfect reference image for
    image-edit models (e.g. Picture 2 when carving an in-world title)."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"title": ("STRING", {"default": "The Colossus Pass"}), "look": LOOK_INPUT,
                             "width": ("INT", {"default": 1344, "min": 256, "max": 4096, "step": 16}),
                             "height": ("INT", {"default": 768, "min": 256, "max": 4096, "step": 16})}}

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "render"
    CATEGORY = "Open Cinema/Motion"

    def render(self, title, look, width, height):
        import numpy as np
        from . import motion
        frame = np.asarray(motion.type_sheet(title, look, width, height), dtype="float32")[None] / 255.0
        return (_to_tensor(frame),)


class OpenCinemaLeadBrief:
    """Writes the instruction for an LLM (e.g. Gemma 4 12B (8-bit) in TextGenerate) to create the film's lead:
    from the world, refining a draft, from a casting photo, or just the continuity notes."""

    @classmethod
    def INPUT_TYPES(cls):
        from .director import LEAD_MODES
        return {"required": {
            "mode": (list(LEAD_MODES), {"default": "write"}),
            "title": ("STRING", {"default": "The Colossus Pass"}),
            "world": ("STRING", {"multiline": True, "default": ""}),
            "look": LOOK_INPUT,
        }, "optional": {
            "draft": ("STRING", {"multiline": True, "default": "",
                                 "tooltip": "Your draft (refine) or the lead description (continuity)"}),
        }}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("prompt",)
    FUNCTION = "build"
    CATEGORY = "Open Cinema"

    def build(self, mode, title, world, look, draft=""):
        from .director import lead_brief
        return (lead_brief(mode, title, world, look, draft),)


class OpenCinemaStoryBrief:
    """Writes the instruction for an LLM to develop the whole story page (title, logline, world, look,
    palette, lead, continuity) or one field of it, consistent with what is already established."""

    @classmethod
    def INPUT_TYPES(cls):
        from .director import STORY_TARGETS
        return {"required": {"target": (list(STORY_TARGETS), {"default": "everything"}),
                             "idea": ("STRING", {"multiline": True, "default": ""})},
                "optional": {"title": ("STRING", {"default": ""}), "logline": ("STRING", {"default": ""}),
                             "world": ("STRING", {"multiline": True, "default": ""}),
                             "look": ("STRING", {"default": ""}),
                             "lead": ("STRING", {"multiline": True, "default": ""}),
                             "beats": ("STRING", {"multiline": True, "default": ""}),
                             "count": ("INT", {"default": 3, "min": 1, "max": 8}),
                             "characters": ("STRING", {"multiline": True, "default": ""}),
                             "creative_seed": ("INT", {"default": 0, "min": 0, "max": 2147483647,
                                                       "tooltip": "Changes the loose starting points for an empty spark."}),
                             "avoid_title_words": ("STRING", {"default": "",
                                                             "tooltip": "Optional recurring title words to avoid on an empty spark."})}}

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("prompt", "director_idea")
    FUNCTION = "build"
    CATEGORY = "Open Cinema"

    def build(self, target, idea, title="", logline="", world="", look="", lead="", beats="", count=3, characters="", creative_seed=0, avoid_title_words=""):
        from .director import story_brief
        return (story_brief(target, idea, title, logline, world, look, lead, beats, count, characters, creative_seed, avoid_title_words), idea)


class OpenCinemaParseStory:
    """Splits the LLM's reply into the story fields. Palette is 'bg,ink,accent,glow' hex."""

    @classmethod
    def INPUT_TYPES(cls):
        from .director import STORY_TARGETS
        return {"required": {"text": ("STRING", {"forceInput": True})},
                "optional": {"target": (list(STORY_TARGETS), {"default": "everything"}),
                             "idea": ("STRING", {"default": "", "forceInput": True})}}

    RETURN_TYPES = ("STRING",) * 10
    RETURN_NAMES = ("title", "logline", "world", "look", "palette", "lead", "continuity", "trailer", "beats",
                    "characters")
    FUNCTION = "parse"
    CATEGORY = "Open Cinema"

    def parse(self, text, target="everything", idea=""):
        from .director import parse_story
        fields = parse_story(text, target, idea)
        return tuple(fields.get(k, "") for k in self.RETURN_NAMES)


class OpenCinemaShotsBrief:
    """Writes the instruction for an LLM to plan the storyboard from the story beats: the shots for some beats
    or the whole film ("board"), the shot that comes next ("next"), or one shot again ("rewrite"). `beats` is the
    story, one numbered beat per line; `shots` the board so far (it stays as it is); `write_beats` e.g. "2, 3"."""

    @classmethod
    def INPUT_TYPES(cls):
        from .director import SHOT_MODES
        return {"required": {"mode": (list(SHOT_MODES), {"default": "board"}),
                             "count": ("INT", {"default": 5, "min": 1, "max": 8}),
                             "index": ("INT", {"default": 1, "min": 1, "max": 99})},
                "optional": {"title": ("STRING", {"default": ""}), "logline": ("STRING", {"default": ""}),
                             "world": ("STRING", {"multiline": True, "default": ""}),
                             "look": ("STRING", {"default": ""}),
                             "lead": ("STRING", {"multiline": True, "default": ""}),
                             "continuity": ("STRING", {"default": ""}),
                             "beats": ("STRING", {"multiline": True, "default": ""}),
                             "shots": ("STRING", {"multiline": True, "default": ""}),
                             "write_beats": ("STRING", {"default": ""}),
                             "characters": ("STRING", {"multiline": True, "default": ""})}}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("prompt",)
    FUNCTION = "build"
    CATEGORY = "Open Cinema"

    def build(self, mode, count, index, title="", logline="", world="", look="", lead="", continuity="", beats="",
              shots="", write_beats="", characters=""):
        from .director import shot_brief
        return (shot_brief(mode, title, logline, world, look, lead, continuity, shots, index, count, beats,
                           write_beats, characters),)


class OpenCinemaParseShots:
    """Splits the LLM's reply into shots: JSON for the studio, a readable storyboard, and any new story beats
    the writer added (one per line) when the film ran past the story."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"text": ("STRING", {"forceInput": True})},
                "optional": {"lead_description": ("STRING", {"multiline": True, "default": ""})}}

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("shots_json", "storyboard", "new_beats")
    FUNCTION = "parse"
    CATEGORY = "Open Cinema"

    def parse(self, text, lead_description=""):
        import json
        from .director import parse_new_beats, parse_shots
        shots = parse_shots(text, lead_description)
        board = "\n\n".join(f"{n + 1}. {'Beat ' + str(s['beat']) + ' · ' if s['beat'] else ''}"
                             f"{s['shot_size']} · {s['camera_move']} · {s['seconds']:g}s"
                             f"{'' if s['lead'] else ' · no lead'}{' · one take' if s['transition'] == 'continue' else ''}"
                             f"\n{s['action']}\nSound: {s['sound']}" for n, s in enumerate(shots))
        return (json.dumps(shots), board, "\n".join(parse_new_beats(text)))


class OpenCinemaReviewShotsBrief:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"brief": ("STRING", {"forceInput": True}),
                             "draft": ("STRING", {"forceInput": True})}}

    RETURN_TYPES = ("STRING",)
    FUNCTION = "build"
    CATEGORY = "Open Cinema"

    def build(self, brief, draft):
        from .director import shot_review_brief
        return (shot_review_brief(brief, draft),)


class OpenCinemaParseLead:
    """Splits the LLM's reply into the lead description and the continuity notes."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"text": ("STRING", {"forceInput": True})}}

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("lead", "continuity")
    FUNCTION = "parse"
    CATEGORY = "Open Cinema"

    def parse(self, text):
        from .director import parse_lead
        return parse_lead(text)


class OpenCinemaContinuityBrief:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"context_json": ("STRING", {"multiline": True})}}
    RETURN_TYPES = ("STRING",)
    FUNCTION = "build"
    CATEGORY = "Open Cinema/Continuity"

    def build(self, context_json):
        from .director import continuity_brief
        return (continuity_brief(context_json),)


class OpenCinemaParseContinuity:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"text": ("STRING", {"forceInput": True}), "shot_count": ("INT", {"default": 1, "min": 1})}}
    RETURN_TYPES = ("STRING",)
    FUNCTION = "parse"
    CATEGORY = "Open Cinema/Continuity"

    def parse(self, text, shot_count):
        import json
        from .director import parse_continuity
        return (json.dumps(parse_continuity(text, shot_count)),)


class OpenCinemaStateLedger:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"plan_json": ("STRING", {"forceInput": True}), "shot_index": ("INT", {"default": 1, "min": 1})}}
    RETURN_TYPES = ("STRING",) * 7
    RETURN_NAMES = ("state_before", "state_changes", "start_cast", "end_cast", "design", "start_checks", "end_checks")
    FUNCTION = "resolve"
    CATEGORY = "Open Cinema/Continuity"

    def resolve(self, plan_json, shot_index):
        import json
        from .director import parse_continuity
        raw = json.loads(plan_json)
        plan = parse_continuity(plan_json, len(raw["shots"]))
        if not 1 <= shot_index <= len(plan["shots"]):
            raise ValueError("Shot index outside the continuity plan")
        before = dict(plan["initial"])
        for previous in plan["shots"][:shot_index - 1]:
            before.update(previous["changes"])
        shot = plan["shots"][shot_index - 1]
        return (json.dumps(before), json.dumps(shot["changes"]), json.dumps(shot["start_cast"]),
                json.dumps(shot["end_cast"]), plan["design"], json.dumps(shot["start_checks"]), json.dumps(shot["end_checks"]))


class OpenCinemaVisualReviewBrief:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"expected_json": ("STRING", {"multiline": True}), "look": ("STRING", {"multiline": True}),
                             "phase": (["start", "middle", "end"], {"default": "start"})},
                "optional": {"style_only": ("BOOLEAN", {"default": False})}}
    RETURN_TYPES = ("STRING",)
    FUNCTION = "build"
    CATEGORY = "Open Cinema/Continuity"

    def build(self, expected_json, look, phase, style_only=False):
        import json
        from .director import visual_review_brief
        if style_only:
            expected_json = json.dumps({**json.loads(expected_json), "state": {}})
        return (visual_review_brief(expected_json, look, phase),)


class OpenCinemaStateEvidenceBrief:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"text": ("STRING", {"forceInput": True}), "expected_json": ("STRING", {"multiline": True})}}
    RETURN_TYPES = ("STRING",)
    FUNCTION = "build"
    CATEGORY = "Open Cinema/Continuity"

    def build(self, text, expected_json):
        from .director import state_evidence_brief
        return (state_evidence_brief(text, expected_json),)


class OpenCinemaParseVisualReview:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"text": ("STRING", {"forceInput": True}), "expected_json": ("STRING", {"multiline": True})},
                "optional": {"observed_count": ("STRING", {"forceInput": True}),
                             "state_audit": ("STRING", {"forceInput": True})}}
    RETURN_TYPES = ("STRING", "BOOLEAN")
    RETURN_NAMES = ("review", "passed")
    FUNCTION = "parse"
    CATEGORY = "Open Cinema/Continuity"

    def parse(self, text, expected_json, observed_count=None, state_audit=None):
        import json
        from .director import parse_visual_review
        review = parse_visual_review(text, expected_json, observed_count, state_audit)
        return (json.dumps(review), review["status"] == "passed")


class OpenCinemaReviewSamples:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"images": ("IMAGE",)}}
    RETURN_TYPES = ("IMAGE",) * 4
    RETURN_NAMES = ("start", "one_third", "two_thirds", "end")
    FUNCTION = "sample"
    CATEGORY = "Open Cinema/Continuity"

    def sample(self, images):
        if len(images) < 4:
            raise ValueError("Video review requires at least four frames")
        return tuple(images[index:index + 1] for index in (0, round((len(images)-1)/3), round(2*(len(images)-1)/3), len(images)-1))


class OpenCinemaCombineReviews:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {f"review_{i}": ("STRING", {"forceInput": True}) for i in range(1, 5)}}
    RETURN_TYPES = ("STRING", "BOOLEAN")
    RETURN_NAMES = ("review", "passed")
    FUNCTION = "combine"
    CATEGORY = "Open Cinema/Continuity"

    def combine(self, **kwargs):
        import json
        from .director import combine_visual_reviews
        review = combine_visual_reviews([json.loads(kwargs[f"review_{i}"]) for i in range(1, 5)])
        return (json.dumps(review), review["status"] == "passed")


class OpenCinemaTitleBrief:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {key: ("STRING", {"multiline": True}) for key in ("idea", "story", "avoid_words")}}
    RETURN_TYPES = ("STRING",)
    FUNCTION = "build"
    CATEGORY = "Open Cinema/Writing"

    def build(self, idea, story, avoid_words):
        from .director import title_brief
        return (title_brief(idea, story, avoid_words),)


class OpenCinemaFactBrief:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"expected_json": ("STRING", {"multiline": True})}}
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("keys", "prompts")
    OUTPUT_IS_LIST = (True, True)
    FUNCTION = "build"
    CATEGORY = "Open Cinema/Continuity"

    def build(self, expected_json):
        from .director import fact_observation_brief, json_object
        keys = list(json_object(expected_json).get("state", {}))
        return (keys or [""], [fact_observation_brief(key) for key in keys] or ["Describe the visible materials briefly."])


class OpenCinemaAppendObservation:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {key: ("STRING", {"forceInput": True}) for key in ("text", "key", "observation")}}
    RETURN_TYPES = ("STRING",)
    INPUT_IS_LIST = True
    FUNCTION = "append"
    CATEGORY = "Open Cinema/Continuity"

    def append(self, text, observation, key):
        import json
        from .director import json_object
        if len(key) != len(observation):
            raise ValueError("Each required fact needs its own visual observation")
        result = json_object(text[0])
        result["state"] = [{"key": k, "verdict": "observed", "observed": value.strip()} for k, value in zip(key, observation) if k]
        return (json.dumps(result),)


class OpenCinemaReviewRequirements:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"expected_json": ("STRING", {"multiline": True})}}
    RETURN_TYPES = ("STRING",)
    FUNCTION = "build"
    CATEGORY = "Open Cinema/Continuity"

    def build(self, expected_json):
        return (expected_json,)


class OpenCinemaEndingBrief:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {key: ("STRING", {"multiline": True}) for key in ("action", "end_state", "look", "state_json", "design")}}
    RETURN_TYPES = ("STRING",)
    FUNCTION = "build"
    CATEGORY = "Open Cinema/Continuity"

    def build(self, action, end_state, look, state_json, design):
        import json
        from .director import ending_frame_prompt
        return (ending_frame_prompt(action, end_state, look, json.loads(state_json), design),)


class OpenCinemaFrameRepairBrief:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {key: ("STRING", {"multiline": True}) for key in ("staging", "requirements_json", "findings_json")}}
    RETURN_TYPES = ("STRING",)
    FUNCTION = "build"
    CATEGORY = "Open Cinema/Continuity"

    def build(self, staging, requirements_json, findings_json):
        from .director import frame_repair_prompt
        return (frame_repair_prompt(staging, requirements_json, findings_json),)


class OpenCinemaPropBrief:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {key: ("STRING", {"multiline": True}) for key in ("description", "state", "look")}}
    RETURN_TYPES = ("STRING",)
    FUNCTION = "build"
    CATEGORY = "Open Cinema/Assets"

    def build(self, description, state, look):
        from .director import prop_prompt
        return (prop_prompt(description, state, look),)


class OpenCinemaSelectTitle:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {key: ("STRING", {"multiline": True}) for key in ("text", "avoid_words", "idea")}}
    RETURN_TYPES = ("STRING",)
    FUNCTION = "select"
    CATEGORY = "Open Cinema/Writing"

    def select(self, text, avoid_words, idea):
        from .director import select_title
        return (select_title(text, avoid_words, idea),)


class OpenCinemaContinuityRepairBrief:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"text": ("STRING", {"forceInput": True}), "context_json": ("STRING", {"multiline": True}),
                             "shot_count": ("INT", {"default": 1, "min": 1})}}
    RETURN_TYPES = ("STRING",)
    FUNCTION = "build"
    CATEGORY = "Open Cinema/Continuity"

    def build(self, text, context_json, shot_count):
        from .director import continuity_repair_brief
        return (continuity_repair_brief(text, context_json, shot_count),)


NODE_CLASS_MAPPINGS = {"OpenCinemaShot": OpenCinemaShot, "OpenCinemaShotLength": OpenCinemaShotLength,
                       "OpenCinemaWriter": OpenCinemaWriter, "OpenCinemaCastReview": OpenCinemaCastReview,
                       "OpenCinemaFrameRepairBrief": OpenCinemaFrameRepairBrief,
                       "OpenCinemaReviewRequirements": OpenCinemaReviewRequirements, "OpenCinemaEndingBrief": OpenCinemaEndingBrief,
                       "OpenCinemaFactBrief": OpenCinemaFactBrief, "OpenCinemaAppendObservation": OpenCinemaAppendObservation,
                       "OpenCinemaPropBrief": OpenCinemaPropBrief,
                       "OpenCinemaTitleBrief": OpenCinemaTitleBrief, "OpenCinemaSelectTitle": OpenCinemaSelectTitle,
                       "OpenCinemaContinuityRepairBrief": OpenCinemaContinuityRepairBrief,
                       "OpenCinemaContinuityBrief": OpenCinemaContinuityBrief,
                       "OpenCinemaParseContinuity": OpenCinemaParseContinuity,
                       "OpenCinemaStateLedger": OpenCinemaStateLedger,
                       "OpenCinemaVisualReviewBrief": OpenCinemaVisualReviewBrief,
                       "OpenCinemaStateEvidenceBrief": OpenCinemaStateEvidenceBrief,
                       "OpenCinemaParseVisualReview": OpenCinemaParseVisualReview,
                       "OpenCinemaReviewSamples": OpenCinemaReviewSamples,
                       "OpenCinemaCombineReviews": OpenCinemaCombineReviews,
                       "OpenCinemaMonochrome": OpenCinemaMonochrome,
                       "OpenCinemaReviewShotsBrief": OpenCinemaReviewShotsBrief,
                       "OpenCinemaValidateCast": OpenCinemaValidateCast,
                       "OpenCinemaLeadBrief": OpenCinemaLeadBrief, "OpenCinemaParseLead": OpenCinemaParseLead,
                       "OpenCinemaStoryBrief": OpenCinemaStoryBrief, "OpenCinemaParseStory": OpenCinemaParseStory,
                       "OpenCinemaShotsBrief": OpenCinemaShotsBrief, "OpenCinemaParseShots": OpenCinemaParseShots,
                       "OpenCinemaTitleOverlay": OpenCinemaTitleOverlay, "OpenCinemaShotStamp": OpenCinemaShotStamp,
                       "OpenCinemaCards": OpenCinemaCards, "OpenCinemaTitlePreview": OpenCinemaTitlePreview,
                       "OpenCinemaTypeSheet": OpenCinemaTypeSheet}
NODE_DISPLAY_NAME_MAPPINGS = {"OpenCinemaShot": "Open Cinema Shot (camera direction)",
                              "OpenCinemaShotLength": "Open Cinema Shot Length",
                              "OpenCinemaLeadBrief": "Open Cinema Lead Brief (for an LLM)",
                              "OpenCinemaParseLead": "Open Cinema Parse Lead",
                              "OpenCinemaStoryBrief": "Open Cinema Story Brief (for an LLM)",
                              "OpenCinemaParseStory": "Open Cinema Parse Story",
                              "OpenCinemaShotsBrief": "Open Cinema Shots Brief (for an LLM)",
                              "OpenCinemaParseShots": "Open Cinema Parse Shots",
                              "OpenCinemaTitleOverlay": "Open Cinema Title Overlay",
                              "OpenCinemaShotStamp": "Open Cinema Shot Stamp",
                              "OpenCinemaCards": "Open Cinema Cards (kinetic type)",
                              "OpenCinemaTitlePreview": "Open Cinema Title Preview",
                              "OpenCinemaTypeSheet": "Open Cinema Type Sheet (title reference)"}

try:
    from .studio_bridge import install as _install_studio_bridge
    _install_studio_bridge()
except Exception as _bridge_error:
    import logging
    logging.warning('Open Cinema companion unavailable: %s', _bridge_error)
