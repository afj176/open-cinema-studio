"""Open Cinema: camera-direction nodes for building multi-shot films in ComfyUI."""

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
        }}

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("world_plate_prompt", "shot_prompt", "motion_prompt", "cast_prompt")
    FUNCTION = "build"
    CATEGORY = "Open Cinema"

    def build(self, scene, action, shot_size, camera_move, look, sound, continuity="", lead_in_shot=True, cast=""):
        return (world_plate_prompt(scene, look),
                shot_prompt(action, shot_size, look, continuity, has_cast=bool(cast.strip()) and lead_in_shot,
                            camera_move=camera_move, lead=lead_in_shot, world=scene.split(". ")[0]),
                motion_prompt(action, camera_move, sound, look, cast, shot_size, continuity, lead_in_shot),
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


LOOK_INPUT = (list(LOOKS), {"default": "70mm epic", "tooltip": "Motion graphics take on this film look's palette"})
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
    """Writes the instruction for an LLM (e.g. Gemma 4 E4B in TextGenerate) to create the film's lead:
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
                             "lead": ("STRING", {"multiline": True, "default": ""})}}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("prompt",)
    FUNCTION = "build"
    CATEGORY = "Open Cinema"

    def build(self, target, idea, title="", logline="", world="", look="", lead=""):
        from .director import story_brief
        return (story_brief(target, idea, title, logline, world, look, lead),)


class OpenCinemaParseStory:
    """Splits the LLM's reply into the story fields. Palette is 'bg,ink,accent,glow' hex."""

    @classmethod
    def INPUT_TYPES(cls):
        from .director import STORY_TARGETS
        return {"required": {"text": ("STRING", {"forceInput": True})},
                "optional": {"target": (list(STORY_TARGETS), {"default": "everything"})}}

    RETURN_TYPES = ("STRING",) * 8
    RETURN_NAMES = ("title", "logline", "world", "look", "palette", "lead", "continuity", "trailer")
    FUNCTION = "parse"
    CATEGORY = "Open Cinema"

    def parse(self, text, target="everything"):
        from .director import parse_story
        fields = parse_story(text, target)
        return tuple(fields.get(k, "") for k in self.RETURN_NAMES)


class OpenCinemaShotsBrief:
    """Writes the instruction for an LLM to plan the storyboard: the whole sequence ("board"), the shot that
    comes next ("next"), or one shot again ("rewrite"). `shots` is the board so far, one numbered shot per line."""

    @classmethod
    def INPUT_TYPES(cls):
        from .director import SHOT_MODES
        return {"required": {"mode": (list(SHOT_MODES), {"default": "board"}),
                             "count": ("INT", {"default": 5, "min": 2, "max": 8}),
                             "index": ("INT", {"default": 1, "min": 1, "max": 99})},
                "optional": {"title": ("STRING", {"default": ""}), "logline": ("STRING", {"default": ""}),
                             "world": ("STRING", {"multiline": True, "default": ""}),
                             "look": ("STRING", {"default": ""}),
                             "lead": ("STRING", {"multiline": True, "default": ""}),
                             "continuity": ("STRING", {"default": ""}),
                             "shots": ("STRING", {"multiline": True, "default": ""})}}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("prompt",)
    FUNCTION = "build"
    CATEGORY = "Open Cinema"

    def build(self, mode, count, index, title="", logline="", world="", look="", lead="", continuity="", shots=""):
        from .director import shot_brief
        return (shot_brief(mode, title, logline, world, look, lead, continuity, shots, index, count),)


class OpenCinemaParseShots:
    """Splits the LLM's reply into shots: JSON for the studio, and a readable storyboard."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"text": ("STRING", {"forceInput": True})}}

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("shots_json", "storyboard")
    FUNCTION = "parse"
    CATEGORY = "Open Cinema"

    def parse(self, text):
        import json
        from .director import parse_shots
        shots = parse_shots(text)
        board = "\n\n".join(f"{n + 1}. {s['shot_size']} · {s['camera_move']} · {s['seconds']:g}s"
                             f"{'' if s['lead'] else ' · no lead'}{' · one take' if s['transition'] == 'continue' else ''}"
                             f"\n{s['action']}\nSound: {s['sound']}" for n, s in enumerate(shots))
        return (json.dumps(shots), board)


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


NODE_CLASS_MAPPINGS = {"OpenCinemaShot": OpenCinemaShot, "OpenCinemaShotLength": OpenCinemaShotLength,
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
