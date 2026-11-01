"""Cinematography vocabulary shared by the ComfyUI nodes and the web app.

Turns a scene, a shot size, a camera move and a film look into prompts that
Qwen-Image (keyframes), Qwen-Image-Edit (coverage) and LTX 2.5 (motion) follow.
"""

from __future__ import annotations

CAMERA_MOVES: dict[str, str] = {
    "Static": "The camera is locked off on a tripod and does not move.",
    "Dolly in": "The camera dollies slowly forward toward the subject in one smooth continuous move.",
    "Dolly out": "The camera dollies slowly backward away from the subject, revealing more of the surroundings.",
    "Push in (slow)": "A very slow, subtle push-in toward the subject's face, building tension.",
    "Crash zoom": "A sudden fast zoom punches in on the subject.",
    "Truck left": "The camera tracks steadily sideways to the left, parallel to the subject, foreground objects "
                  "sliding past.",
    "Truck right": "The camera tracks steadily sideways to the right, parallel to the subject, foreground objects "
                   "sliding past.",
    "Pan left": "The camera pans smoothly to the left from a fixed position.",
    "Pan right": "The camera pans smoothly to the right from a fixed position.",
    "Tilt up": "The camera tilts upward, revealing what is above.",
    "Tilt down": "The camera tilts downward from above to the subject.",
    "Crane up": "The camera cranes up, rising steadily high above the scene and tilting down as it ascends, "
                "the ground falling away below.",
    "Crane down": "The camera cranes down from high above and settles at eye level with the subject.",
    "Orbit left": "The camera travels around the subject counter-clockwise in a smooth half orbit, keeping them "
                  "centered while the background swings past behind them.",
    "Orbit right": "The camera travels around the subject clockwise in a smooth half orbit, keeping them "
                   "centered while the background swings past behind them.",
    "Handheld follow": "Handheld camera follows the subject closely with natural shake and breathing.",
    "Whip pan": "The camera whips quickly sideways in a fast blurred pan.",
    "Drone flyover": "Aerial drone shot: the camera flies steadily forward high above the scene, the landscape "
                     "sliding past beneath it, strong forward parallax.",
    "FPV dive": "A fast FPV drone dives down and races through the scene at high speed.",
    "Dolly zoom (vertigo)": "Dolly zoom: the camera moves backward while zooming in, the background stretches and warps around the subject.",
    "Bullet time": "Time nearly freezes as the camera sweeps around the subject in slow motion.",
    "Snorricam": "The camera is rigged to the subject's body; they stay fixed in frame while the world sways around them.",
}

# Camera-path guides for forward moves: LTX is shy about inventing big camera travel from a busy
# wide frame, so the shot is pulled toward a zoomed end frame. (zoom, centre x, centre y, strength)
# Only for wide shots with nobody in them: the end frame pins a subject to its first pose.
CAMERA_PATHS: dict[str, tuple[float, float, float, float]] = {
    "Drone flyover": (1.5, 0.5, 0.5, 0.6),
    "Dolly in": (1.3, 0.5, 0.45, 0.6),
    "Push in (slow)": (1.15, 0.5, 0.45, 0.5),
    "Crash zoom": (1.9, 0.5, 0.45, 0.7),
    "FPV dive": (1.6, 0.5, 0.62, 0.6),
}

SHOT_SIZES: dict[str, str] = {
    "Extreme wide": "extreme wide shot, the subject small in a vast environment",
    "Wide": "wide shot showing the full body and the location",
    "Full": "full shot, head to toe",
    "Medium": "medium shot from the waist up",
    "Medium close-up": "medium close-up from the chest up",
    "Close-up": "close-up on the face",
    "Extreme close-up": "extreme close-up on the eyes",
    "Over the shoulder": "over-the-shoulder shot",
    "Low angle": "low angle shot looking up at the subject, heroic",
    "High angle": "high angle shot looking down on the subject",
    "Insert": "insert shot, macro detail of an object",
    "POV": "point of view shot through the character's eyes",
}

WIDE_SIZES = {"Extreme wide", "Wide"}

# Where the camera starts: a keyframe is the first frame of its camera move.
MOVE_VIEWPOINT: dict[str, str] = {
    "Drone flyover": "aerial view from high above, looking down and forward over the scene",
    "FPV dive": "high aerial view looking steeply down into the depth below",
    "Crane down": "high angle from above",
    "Crane up": "low camera close to the ground",
    "Tilt up": "camera looking down toward the ground level of the scene",
    "Tilt down": "camera looking up toward the top of the scene",
    "Bullet time": "eye-level, frozen mid-action",
    "Dolly out": "close to the subject",
}

LOOKS: dict[str, str] = {
    "Anamorphic blockbuster": "shot on 35mm anamorphic lenses, oval bokeh, horizontal lens flares, teal and orange grade, high contrast",
    "70mm epic": "shot on 65mm large format film, epic scale, rich detail, natural light, deep focus",
    "Noir": "black and white film noir, hard key light, deep shadows, venetian blind light patterns, smoke",
    "Neon cyberpunk": "neon-soaked night, magenta and cyan practical lights, wet reflective streets, haze",
    "16mm indie": "shot on 16mm film, visible grain, soft halation, muted pastel colors, handheld intimacy",
    "Wes-style symmetry": "perfectly symmetrical composition, pastel palette, flat frontal staging, whimsical production design",
    "Golden hour": "golden hour backlight, warm sun flare, long shadows, dreamy atmosphere",
    "Horror": "underexposed, cold desaturated green tint, harsh single light source, unsettling negative space",
    "Documentary": "naturalistic documentary look, available light, realistic textures",
    "Anime": "high quality 2D anime film still, cel shading, painted backgrounds, dramatic lighting",
    "Claymation": "stop-motion claymation, handmade plasticine textures, miniature set, soft studio lights",
    "None": "",
}

# What each look is made of. The realism words, the negative prompt and how a storyboard drawing becomes a frame
# all follow it, so a look is never fought by the prompts around it (everything not listed is live action).
LOOK_MEDIUM = {"Noir": "bw", "Anime": "anime", "Claymation": "clay"}
MEDIUM_FRAME = {
    "photo": "Cinematic still frame from a live-action feature film: realistic light, natural colour and texture",
    "bw": "Cinematic still frame from a black-and-white live-action feature film: realistic light and texture, "
          "no colour anywhere, every colour named here (clothing included) seen only as a shade of grey",
    "anime": "Still frame from a high-quality 2D animated feature film: clean line art, cel shading, painted "
             "backgrounds",
    "clay": "Still frame from a stop-motion claymation feature film: handmade plasticine characters and a miniature "
            "set, real studio light",
}
MEDIUM_PORTRAIT = {
    "photo": "Natural photograph with sharp, detailed skin and hair, true-to-life colours",
    "bw": "Black-and-white photograph with sharp, detailed skin and hair",
    "anime": "Clean 2D anime character design drawing, line art and flat cel shading",
    "clay": "A handmade plasticine stop-motion puppet, photographed on set",
}
MEDIUM_FINISHED = {  # what a storyboard drawing turns into
    "photo": "a real photographic film frame in full colour",
    "bw": "a real black-and-white photographic film frame",
    "anime": "a finished 2D anime frame in full colour",
    "clay": "a finished stop-motion claymation frame",
}
_MEDIUM_NEGATIVE = {
    "photo": "illustration, painting, cartoon, anime, 3d render, CGI, video game, plastic skin",
    "bw": "colour, illustration, painting, cartoon, anime, 3d render, CGI, plastic skin",
    "anime": "photograph, photorealistic, live action, 3d render, CGI",
    "clay": "live action, real people, illustration, anime, CGI",
}


def medium(look: str) -> str:
    return LOOK_MEDIUM.get(look, "photo")


def image_negative(look: str) -> str:
    """HiDream-O1's negative prompt (it samples with real guidance, so this one matters), for the look's medium."""
    return (_MEDIUM_NEGATIVE[medium(look)] + ", low quality, blurry, deformed, extra limbs, extra fingers, readable "
            "text, caption, subtitles, watermark, logo, frame border, split screen, collage, film camera, camera rig, "
            "film crew, lighting equipment")


# Motion-graphics palette per look: ink, accent, glow, background, title face (barlow | fraunces | manrope).
LOOK_PALETTES: dict[str, tuple[str, str, str, str, str]] = {
    "Anamorphic blockbuster": ("#F4F1EA", "#FF7A1A", "#FFB25C", "#0B0E12", "barlow"),
    "70mm epic": ("#F3E9D2", "#E2A43A", "#FFD27A", "#120E0A", "fraunces"),
    "Noir": ("#F2F2F2", "#BDBDBD", "#FFFFFF", "#050505", "fraunces"),
    "Neon cyberpunk": ("#F5F7FF", "#FF2BD6", "#34E7FF", "#07060F", "barlow"),
    "16mm indie": ("#F1E6D2", "#D9553B", "#F2A07B", "#15110D", "manrope"),
    "Wes-style symmetry": ("#FFF4E6", "#E8738A", "#F7C873", "#2B1F27", "fraunces"),
    "Golden hour": ("#FFF3DF", "#F39C33", "#FFD08A", "#140C06", "manrope"),
    "Horror": ("#E7E4DA", "#B3121B", "#FF3B30", "#060707", "fraunces"),
    "Documentary": ("#FFFFFF", "#FFD400", "#FFF2A6", "#0D0D0D", "manrope"),
    "Anime": ("#FFFFFF", "#FF3355", "#FF8FA3", "#0E0B16", "barlow"),
    "Claymation": ("#FFF6EC", "#FF8A3D", "#FFC08A", "#1B130F", "manrope"),
    "None": ("#F4F4F2", "#FF4A1C", "#FF7A45", "#0C0C0D", "barlow"),
}


# In-world title materials: the title becomes part of the scene, in a material that suits the look.
TITLE_MATERIALS: dict[str, str] = {
    "Anamorphic blockbuster": "huge brushed-steel letters standing in the landscape, catching a lens flare",
    "70mm epic": "monumental letters deeply carved into the ancient weathered rock face, as if cut by a lost "
                 "civilisation",
    "Noir": "letters painted in white on a rain-streaked frosted glass window, lit from behind",
    "Neon cyberpunk": "a giant glowing neon sign of bent glass tubes, buzzing and reflected in the wet surfaces",
    "16mm indie": "a hand-painted wooden sign with chipped paint, slightly crooked",
    "Wes-style symmetry": "perfectly centred pastel-painted signage in a vintage typeface",
    "Golden hour": "tall letters formed by warm sunlight shining through cut-out shapes, glowing gold",
    "Horror": "letters scratched deep into old wood, dark and dripping",
    "Documentary": "bold stencilled letters spray-painted on a weathered surface",
    "Anime": "giant bold brush-calligraphy letters with dynamic ink strokes",
    "Claymation": "chunky handmade plasticine letters with visible fingerprints",
    "None": "glowing orange neon letters",
}


def spell(title: str) -> str:
    """Letter-by-letter spelling; image models copy it far more reliably than a whole word."""
    return " ".join("-".join(word.upper()) for word in title.split())


def title_frame_prompt(title: str, material: str) -> str:
    """Qwen-Image-Edit: put the film's title into the establishing frame as part of the world."""
    return _join(f'Picture 2 shows the exact title lettering "{title.upper()}". Add exactly this lettering to the '
                 f"film frame in Picture 1 as {material}",
                 "Copy the letters from Picture 2 precisely: the same words, the same spelling "
                 f"({spell(title)}), the same order and line layout, appearing only once",
                 "Place the lettering on a real surface in the scene where it would truly exist, such as a rock "
                 "face, wall, building or sign (only light-based lettering may float in the air), large and clearly "
                 "readable, following that surface's perspective, light and weather",
                 "Keep everything else in the frame unchanged: same composition, framing, subjects and colours",
                 "No other text")


def title_motion_prompt(title: str, material: str, sound: str = "") -> str:
    """LTX: the title holds perfectly still while the world moves around it."""
    return _join(f'The title "{title}", made of {material}, stays perfectly still, sharp and legible for the whole '
                 "shot", "The camera pushes in very slowly toward the title",
                 "Around the letters the scene comes alive: weather, light, particles and atmosphere move gently",
                 "Cinematic, awe-inspiring title shot, no cuts", sound and "Audio: " + sound)


# Trailer score character per look; LTX composes it as the soundtrack of one continuous render.
SCORE_STYLES: dict[str, str] = {
    "Anamorphic blockbuster": "huge modern blockbuster trailer music with booming brass braams, hybrid synth pulses and "
                              "pounding drums",
    "70mm epic": "an epic orchestral trailer score with deep brass braams, thundering taiko drums, a choir and soaring "
                 "strings",
    "Noir": "a brooding jazz-noir trailer score with low double bass, muted trumpet, brushed drums and tension stabs",
    "Neon cyberpunk": "a dark synthwave trailer score with pulsing bass, glitchy percussion and huge synth impacts",
    "16mm indie": "an intimate indie trailer score with warm acoustic guitar, soft piano and a gentle build",
    "Wes-style symmetry": "a whimsical trailer score with plucked strings, glockenspiel and a jaunty rhythm",
    "Golden hour": "a hopeful, swelling trailer score with warm strings, piano and a rising choir",
    "Horror": "a terrifying horror trailer score with dissonant strings, deep sub drops, heartbeat drums and sudden "
              "screeching stingers",
    "Documentary": "a restrained documentary trailer score with ambient piano and a steady pulse",
    "Anime": "an energetic anime trailer score with driving drums, electric guitar and soaring strings",
    "Claymation": "a playful trailer score with bouncy tuba, pizzicato strings and woodblock hits",
    "None": "a hard-hitting modern trailer score with deep braams, risers and heavy impacts",
}


def score_prompt(look: str, title: str) -> str:
    """LTX prompt for the trailer soundtrack. The picture (a title card) is throwaway; the audio is the point."""
    music = SCORE_STYLES.get(look, SCORE_STYLES["None"])
    return _join(f"A movie title card for \"{title}\" glows on a dark background; the camera slowly pushes in",
                 f"Audio: {music}. A movie trailer soundtrack: it opens with a single deep boom, then a steady "
                 "rhythm of heavy percussion hits about once per second, building in intensity with rising strings "
                 "and brass, punctuated by huge cinematic impacts, ending on one massive final hit followed by "
                 "silence. Studio-recorded instrumental music only: no ambience, no weather, no voices")


LEAD_MODES = ("write", "refine", "from photo", "continuity", "identity")

_LEAD_FORMAT = (
    "Reply with exactly two lines and nothing else:\n"
    "LEAD: one paragraph of 40 to 70 words describing only what a camera sees: approximate age, build, face and "
    "skin, distinctive features, hair, the exact wardrobe with colours and materials, and a signature prop if they would carry one. "
    "Present tense, concrete visual details only. No name, no backstory, no personality or emotion words.\n"
    "CONTINUITY: 4 to 6 short comma-separated details that must never change from shot to shot, such as key "
    "wardrobe colours, the hairstyle and the signature prop."
)


def lead_brief(mode: str, title: str, world: str, look: str, draft: str = "") -> str:
    """Instruction for an open LLM (Gemma 4 E4B via ComfyUI TextGenerate) to write the film's lead."""
    film = (f"THE WORLD OF THE FILM (the character must belong to this exact setting, era and culture): "
            f"{world or 'not specified'}\nFilm title: {title or 'Untitled'}\n"
            f"Visual look: {look} ({LOOKS.get(look, '')})")
    if mode == "continuity":
        return ("You are the script supervisor on a feature film. From the lead character description below, list "
                "the 4 to 6 visual details that must never change from shot to shot (key wardrobe colours, "
                "hairstyle, distinctive features, signature prop).\n\n"
                f"Lead: {draft}\n\nReply with exactly one line and nothing else:\nCONTINUITY: comma-separated details")
    if mode == "identity":
        return ("You are a casting director. The attached image is the casting photo of a film's lead. Describe only "
                "what makes this exact person recognisable, so an image model paints the same face in every shot: "
                "skin tone, face shape, eyes and eye colour, eyebrows, nose, lips, facial hair, hair colour, "
                "texture and style, approximate age and build. Be specific and plain (for example 'light olive "
                "skin', 'narrow face with high cheekbones'). No clothing, no props, no background, no emotion.\n\n"
                "Reply with exactly one line and nothing else:\nLEAD: 20 to 40 comma-separated words")
    if mode == "from photo":
        return ("You are the costume and continuity supervisor on a feature film. The attached image is the "
                "casting photo of the film's lead. Describe this exact person as they appear, so an image model "
                "can recreate them in every shot.\n\n" + film + "\n\n" + _LEAD_FORMAT)
    if mode == "refine" and draft.strip():
        return ("You are the casting director and costume designer on a feature film. Improve the director's "
                "draft description of the lead for an image model: keep every detail the director wrote exactly "
                "(the same garments, colours and objects; a torch stays a torch), make vague details specific, and "
                "add what is missing (age, build, face, hair, exact wardrobe colours "
                "and materials, a signature prop if it suits them) so it fits the world and look.\n\n" + film +
                f"\nDirector's draft: {draft}\n\n" + _LEAD_FORMAT)
    return ("You are the casting director and costume designer on a feature film. Read the world below "
            "carefully, then invent a striking, memorable lead character who could only exist in it: their "
            "clothing, materials, props and technology must match its era and setting exactly.\n\n" + film + "\n\n" + _LEAD_FORMAT)


def parse_lead(text: str) -> tuple[str, str]:
    """Split the model's reply into (lead, continuity); tolerant of extra words around the two lines."""
    lead, continuity = "", ""
    for line in text.replace("**", "").splitlines():
        clean = line.strip().lstrip("-* ").strip()
        upper = clean.upper()
        if upper.startswith("LEAD:"):
            lead = clean[5:].strip()
        elif upper.startswith("CONTINUITY:"):
            continuity = clean[11:].strip()
        elif lead and not continuity and clean and not upper.startswith(("CONTINUITY", "LEAD")):
            lead += " " + clean  # the paragraph wrapped onto more lines
    if not lead and not continuity:  # small models often drop the labels: a short comma list last is continuity
        lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
        if len(lines) >= 2 and lines[-1].count(",") >= 2 and len(lines[-1]) < 240:
            lead, continuity = " ".join(lines[:-1]), lines[-1]
        else:
            lead = text.strip()
    return lead.strip().strip('"'), continuity.strip().strip('"').rstrip(".")


# ---------------------------------------------------------------- AI story writer
STORY_TARGETS = ("everything", "title", "logline", "world", "look", "trailer", "beats", "more beats", "characters")
STORY_LABELS = ("TITLE", "LOGLINE", "WORLD", "LOOK", "PALETTE", "LEAD", "CONTINUITY", "CHARACTERS",
                "BEATS")  # "everything", in order
_ALL_LABELS = STORY_LABELS + ("TRAILER",)

_STORY_LINES = {
    "TITLE": "TITLE: an evocative film title of 1 to 5 words, no quotes",
    "LOGLINE": "LOGLINE: one sentence of at most 28 words: who wants what, and what stands in the way",
    "WORLD": "WORLD: one paragraph of 70 to 110 words describing the setting as a camera sees it: the place and "
             "era, landscape or architecture, weather, time of day, light, and two or three unforgettable "
             "landmarks or objects. No dialogue and no plot summary",
    "LOOK": "LOOK: exactly one of these film looks: {looks}",
    "PALETTE": "PALETTE: four hex colours for the film's titles and graphics, in this order: background (very dark), "
               "ink (light, for text), accent (the film's signature colour), glow (a lighter tint of the accent)",
    "LEAD": "LEAD: one paragraph of 40 to 70 words describing only what a camera sees of the lead character: age, "
            "build, face, hair, the exact wardrobe with colours and materials, and a signature prop if they would carry one. No name, "
            "no backstory",
    "CONTINUITY": "CONTINUITY: 4 to 6 short comma-separated details of the lead that must never change between shots",
    "CHARACTERS": "CHARACTERS: the other characters the story needs, separated by ' / ', each as 'Name: 15 to 30 "
                  "words of what a camera sees (age, build, face, hair, clothing)', each clearly different from the "
                  "lead; a crowd or group can be one entry; write none if the story needs only the lead",
    "BEATS": "BEATS: 5 to 7 story beats separated by ' / ', in order, each one sentence of at most 18 words saying "
             "what happens and where, something a camera can see. Shape the story the way this idea wants to be "
             "told (a quest, a chase, a quiet portrait, a reveal, a loop, a confrontation) rather than a formula. "
             "It is the lead's story; other characters appear by name when the story needs them. Each beat leads "
             "to the next, and every detail fits the world",
    "TRAILER": "TRAILER: 4 to 6 trailer title cards separated by ' / ', each at most 6 words, building tension from "
               "the world to the stakes, in the voice of a great movie trailer; the last card is the film's title",
}
_STORY_WANTS = {"everything": STORY_LABELS, "title": ("TITLE",), "logline": ("LOGLINE",), "world": ("WORLD",),
                "look": ("LOOK", "PALETTE"), "trailer": ("TRAILER",), "beats": ("BEATS",), "more beats": ("BEATS",),
                "characters": ("CHARACTERS",)}


def story_brief(target: str, idea: str = "", title: str = "", logline: str = "", world: str = "", look: str = "",
                lead: str = "", beats: str = "", count: int = 3, characters: str = "") -> str:
    """Instruction for an open LLM (Gemma 4 E4B) to write the whole story page or one field of it,
    consistent with whatever the director has already written. "more beats" continues the story in `beats`
    (one numbered beat per line) with `count` new beats."""
    wants = _STORY_WANTS.get(target, STORY_LABELS)
    known = [("The director's idea", idea), ("Title", title), ("Logline", logline), ("World", world),
             ("Look", look), ("Lead character", lead), ("Other characters", characters and "\n" + characters)]
    if target != "everything":  # keep the field being rewritten out of the context so it is truly new
        skip = {"title": "Title", "logline": "Logline", "world": "World", "look": "Look",
                "characters": "Other characters"}.get(target)
        known = [(k, v) for k, v in known if k != skip]
    if target == "trailer" and beats.strip():  # trailer cards tease the actual story
        known.append(("The story, beat by beat", "\n" + beats))
    context = "\n".join(f"{k}: {v}" for k, v in known if v and v.strip())
    lines = "\n".join(_STORY_LINES[label].format(looks=", ".join(LOOKS)) for label in wants)
    if target == "more beats":
        told = len([b for b in beats.splitlines() if b.strip()])
        lines = (f"BEATS: exactly {count} new beats separated by ' / ', numbered on from beat {told + 1}, each one "
                 "sentence of at most 18 words saying what the lead does and where, something a camera can see")
        task = (f"Continue this story with the next {count} beat{'s' if count > 1 else ''}. Pick up exactly where the "
                "last beat leaves off, in the same voice; each new beat causes the next, nothing repeats, and every "
                "detail fits the world. Build toward a memorable ending.\n\nThe story so far, beat by beat:\n" + beats)
    elif target == "everything":
        task = ("Develop a short film from the director's idea (or invent a striking original one if there is no "
                "idea): a title, a logline, a vivid visual world, the film look and colour palette that suit it, "
                "a memorable lead character who belongs to that world and era, any other characters the story "
                "needs, and the story told as visual beats. "
                "Everything must fit together.")
    else:
        task = (f"Write a fresh {' and '.join(w.lower() for w in wants)} for this film. It must fit everything "
                "else already established about the film.")
    return ("You are the writer and production designer of a short cinematic film made with AI.\n" + task +
            ("\n\nWhat is established so far:\n" + context if context else "") +
            f"\n\nReply with exactly these {len(wants)} labelled lines and nothing else:\n" + lines)


def _clean_line(line: str) -> str:
    """Strip list bullets and markdown headings, but not the '#' of a hex colour."""
    import re
    return re.sub(r"^(?:[-*>]+\s*|#+\s+)+", "", line.strip()).strip()


def parse_story(text: str, target: str = "everything") -> dict[str, str]:
    import re
    """Labelled lines → fields. Small models often drop the labels but keep the order, so unlabelled
    replies are read positionally (everything) or as the single field that was asked for."""
    fields: dict[str, str] = {}
    current, labelled = None, False
    for raw in text.replace("**", "").replace("__", "").splitlines():
        line = _clean_line(raw)
        if not line:
            continue
        label, _, rest = line.partition(":")
        key = label.strip().upper()
        if key in _ALL_LABELS and _:
            current, labelled = key, True
            fields[key] = rest.strip()
        elif labelled and current in ("WORLD", "LEAD", "LOGLINE"):
            fields[current] += " " + line  # paragraph wrapped onto more lines
        elif labelled and current in ("TRAILER", "BEATS", "CHARACTERS"):
            fields[current] += " / " + line  # one card or beat per line instead of ' / '
        elif target == "everything":  # a line whose label was dropped: the next field still missing, in order
            after = STORY_LABELS.index(current) + 1 if current in STORY_LABELS else 0
            nxt = next((k for k in STORY_LABELS[after:] if k not in fields), None)
            if nxt:
                current, labelled, fields[nxt] = nxt, False, line
    if fields.get("BEATS", "").strip().strip(".").lower() in ("none", "n/a", "-"):
        fields.pop("BEATS")  # "BEATS: None" is no beats
    if not fields:
        lines = [_clean_line(l).strip('"') for l in text.replace("**", "").splitlines() if l.strip()]
        wants = _STORY_WANTS.get(target, STORY_LABELS)
        if target == "everything" and len(lines) >= len(STORY_LABELS):
            fields = dict(zip(STORY_LABELS, lines[:len(STORY_LABELS)]))
        elif target == "look" and lines:
            fields = {"LOOK": lines[0], "PALETTE": " ".join(lines[1:])}
        elif len(wants) == 1 and lines:
            fields = {wants[0]: lines[0] if wants[0] == "TITLE" else
                      (" / " if wants[0] in ("TRAILER", "BEATS", "CHARACTERS") else " ").join(lines)}
    out = {k.lower(): v.strip().strip('"').strip() for k, v in fields.items()}
    if "look" in out:  # snap to a known look
        match = next((l for l in LOOKS if l.lower() == out["look"].lower()), None) or \
            next((l for l in LOOKS if l.lower() in out["look"].lower() or out["look"].lower() in l.lower()), "")
        out["look"] = match
    if "palette" in out or "look" in out:
        hexes = re.findall(r"#[0-9a-fA-F]{6}", out.get("palette", "") or text)
        out["palette"] = ",".join(h.upper() for h in hexes[:4]) if len(hexes) >= 4 else ""
    if "continuity" in out:
        out["continuity"] = out["continuity"].rstrip(".")
    if "trailer" in out:  # one card per line, as the trailer cards expect
        cards = [c.strip().strip('"').strip() for c in out["trailer"].split("/")]
        out["trailer"] = "\n".join(c for c in cards if c)
    if "characters" in out:  # one 'Name: description' per line; "none" means the lead is alone
        people = [c.strip().strip('"').strip() for c in out["characters"].split("/")]
        out["characters"] = "\n".join(c for c in people if c and c.lower().rstrip(".") not in ("none", "n/a", "-"))
    if "beats" in out:  # one beat per line, without the model's own numbering
        beats = [re.sub(r"^\s*(?:beat\s*)?\d+\s*[.):-]\s*", "", b, flags=re.I).strip().strip('"').strip()
                 for b in out["beats"].split("/")]
        out["beats"] = "\n".join(b for b in beats if b)
    return out


# ---------------------------------------------------------------- AI shot writer
SHOT_MODES = ("board", "next", "rewrite", "beat")
_NEW_BEAT = ("BEAT: one sentence of at most 18 words saying what the lead does and where, something a camera can "
             "see, that continues the story")
SHOT_FIELDS = ("beat", "action", "shot_size", "camera_move", "seconds", "sound", "lead", "others", "line",
               "transition")
_LEAD_WORDS = r"\b(he|she|his|her|hers|him|himself|herself|the lead|the figure|the artisan|the hero|the heroine)\b"


def shot_who(shot: dict) -> str:
    who = (["lead"] if shot.get("lead", True) is not False else []) + ([shot["others"]] if shot.get("others") else [])
    return ", ".join(who) or "none"


def shot_line(shot: dict) -> str:
    """One shot as the writer reads and writes it:
    beat | action | size | move | seconds | sound | who | line | transition."""
    return " | ".join([str(shot.get("beat") or "-"),
                       str(shot.get("action", "")).replace("|", "/").strip() or "(empty)",
                       shot.get("shot_size", "Wide"), shot.get("camera_move", "Static"),
                       str(int(round(float(shot.get("seconds", 4) or 4)))), str(shot.get("sound", "")).replace("|", "/"),
                       shot_who(shot), str(shot.get("line") or "-").replace("|", "/"),
                       "continue" if shot.get("transition") == "continue" else "cut"])


def shot_list_text(shots: list) -> str:
    return "\n".join(f"{n + 1}. {shot_line(s)}" for n, s in enumerate(shots))


def beat_list_text(beats: list) -> str:
    return "\n".join(f"{n + 1}. {b}" for n, b in enumerate(beats))


def shot_brief(mode: str, title: str = "", logline: str = "", world: str = "", look: str = "", lead: str = "",
               continuity: str = "", shots: str = "", index: int = 1, count: int = 5, beats: str = "",
               write_beats: str = "", characters: str = "") -> str:
    """Instruction for an open LLM (Gemma 4 E4B) to write the storyboard. `beats` is the story as numbered beats
    (optional); `shots` the board so far as numbered shot lines, which stay as they are; `index` is 1-based.
    board: the shots for the beats in `write_beats` (or `count` shots that start, or continue and end, the film);
    next: the one shot after the board, telling beat `write_beats`; rewrite: shot `index` again; beat: the story
    beat shot `index` tells. `write_beats` "new" means the story has run out: every shot also writes a new beat
    (a BEAT line before it), so the story grows with the film."""
    film = "\n".join(f"{k}: {v}" for k, v in (("Title", title), ("Logline", logline), ("World", world),
                                                 ("Look", look), ("The lead", lead), ("Never changes", continuity),
                                                 ("Other characters", characters and "\n" + characters))
                     if v and v.strip())
    fmt = ("SHOT: beat | action | size | camera move | seconds | sound | who | line | transition\n\n"
           "beat: the number of the story beat this shot tells" + ("" if beats.strip() else " (write -)") + "\n"
           "action: one or two sentences, present tense, concrete and physical. Start with the exact place in this "
           "film's world where the camera is, then what the people do, what moves, what the light does. Call the lead "
           "the lead and other characters by their names. No thoughts, no cameras or camera words. If the lead is "
           "not in the shot, do not mention them at all\n"
           f"size: exactly one of: {', '.join(SHOT_SIZES)}\n"
           f"camera move: exactly one of: {', '.join(CAMERA_MOVES)}\n"
           "seconds: a whole number from 3 to 8\n"
           "sound: what we hear besides speech, 4 to 12 words (ambience, effects, music)\n"
           "who: everyone in the shot, comma-separated: lead, the names from Other characters, or a group "
           "described in a few words; none for a shot of only the place or an object\n"
           "line: what is said aloud in this shot, as Speaker: \"words\" (Lead or a character's name, at most 14 "
           "words), or - for no speech. Most shots have none; speak only when it matters\n"
           "transition: cut, or continue only when the camera keeps rolling in one unbroken take from the shot before")
    head = ("You are the director and storyboard artist of a short cinematic film made with AI. Every shot is one "
            "moving image of a few seconds, generated from a still of the film's world and a photo of the lead, so "
            "every shot happens in that world. The lead's face comes from their photo; other characters are drawn "
            "from their descriptions, so name them exactly as written, and keep a shot to the people it needs.\n\n"
            "HOW THE SHOTS GO TOGETHER\n"
            "- The story is the lead's: most shots show what they do. A shot without the lead is usually another "
            "character, a close detail (an object, the light, the weather on a surface) or the opening view of the "
            "world; avoid repeating a wide view of the world.\n"
            "- The camera moves through different places in the world, so the film never repeats a view.\n"
            "- Each shot continues from the one before: same time of day and weather, the action picking up where the "
            "last shot left off, building as the story builds.\n"
            "- Every detail fits the world exactly.\n\nTHE FILM\n" + (film or "(nothing yet)"))
    story = f"\n\nTHE STORY, BEAT BY BEAT (the film tells these in order)\n{beats}" if beats.strip() else ""
    board = (f"\n\nTHE FILM SO FAR (these shots stay exactly as they are)\n{shots}" if shots.strip() else "")
    vary = "Vary the shot sizes and camera moves like a great film editor; never the same size twice in a row."
    one = "Reply with exactly one line and nothing else:\n"
    extend = bool(story) and write_beats.strip() == "new"
    told = len([b for b in beats.splitlines() if b.strip()])
    if extend:  # each shot tells a new beat, written on the line before it
        fmt = (_NEW_BEAT + f"\nSHOT: the same number as that beat (the story continues from beat {told + 1}) | action | "
               "size | camera move | seconds | sound | lead | transition\n\n" + fmt.split("\n\n", 1)[1])
    if mode == "beat":
        return (head + story + board + f"\n\nShot {index} is not in the story yet. Write the story beat it tells, in "
                "the same voice as the beats above, so it fits between the beats around it.\n\n" + one +
                "BEAT: one sentence of at most 18 words saying what the lead does and where, something a camera can see")
    if mode == "next":
        task = ("Write the ONE shot that comes right after the film so far: the next moment of the story" +
                (", a new beat that continues the story past its last beat" if extend else
                 f", telling beat {write_beats.strip()}" if story and write_beats.strip() else "") +
                ", with a different size or camera move from the shot before so the cut feels deliberate.")
        reply = ("Reply with exactly two lines, the BEAT line then the SHOT line, and nothing else:\n" if extend
                 else one)
    elif mode == "rewrite":
        task = (f"Rewrite shot {index} so it tells its moment of the story better and flows from the shot before it "
                "into the shot after it. Keep its place in the story" + (" and its beat." if story else "."))
        reply = one
    else:
        count = max(1, min(8, int(count or 5)))
        if extend:
            task = (f"Continue the film so far with the next {count} moments of the story and bring it to a memorable "
                    "ending: each one is a new beat with its shot. Do not restart the story or introduce the world "
                    "again. " + vary)
        elif story and write_beats.strip():
            todo = [b.strip() for b in write_beats.split(",") if b.strip()]
            task = (f"Write one shot for each of these beats, in order: beat {', beat '.join(todo)}. Each shot shows "
                    "its beat as one striking image" + (" and fits between the shots that are already made" if board
                                                          else "") + ". " + vary)
            count = len(todo)
        elif board:
            task = (f"Continue the film so far with the next {count} shots and bring it to a memorable ending. Do "
                    "not restart the story or introduce the world again. " + vary)
        else:
            task = (f"Plan the film as a sequence of exactly {count} shots that tells the logline visually, shaped the "
                    "way this story wants to be told, building to a memorable final image. " + vary)
        reply = (f"Reply with exactly {count} pairs of lines (a BEAT line, then its SHOT line), in order, and "
                 "nothing else:\n" if extend else
                 f"Reply with exactly {count} lines, one per shot in order, and nothing else:\n")
    return head + story + board + "\n\n" + task + "\n\n" + reply + fmt


def _snap(value: str, options, fallback: str) -> str:
    """The model's word for a size or move → the nearest preset."""
    norm = lambda x: " ".join(x.lower().replace("-", " ").replace("shot", "").strip(" .").split())  # noqa: E731
    v, keys = norm(value), list(options)
    for k in keys:
        if norm(k) == v:
            return k
    for k in sorted(keys, key=len, reverse=True):  # "medium close-up" before "medium"
        if norm(k) in v:
            return k
    words = set(v.split())
    best = max(keys, key=lambda k: len(words & set(norm(k).split())))
    return best if words & set(norm(best).split()) else fallback


def parse_shots(text: str) -> list[dict]:
    """The writer's reply → shot dicts with known sizes and moves and a 2-10 s length. Tolerates missing
    'SHOT:' labels, numbering, bullets, a missing beat field and missing trailing fields."""
    import re
    shots, pending = [], None
    for raw in text.replace("**", "").splitlines():
        if re.match(r"^\s*(?:[-*>]+\s*)?beat\s*\d*\s*:", raw, flags=re.I) and "|" not in raw:
            pending = raw.split(":", 1)[1].strip().strip('"').strip() or None  # the new beat the next shot tells
            continue
        line = re.sub(r"^\s*(?:[-*>]+\s*|#+\s+)?(?:shot\s*\d*\s*[:.)-]?|\d+\s*[.)]\s+)\s*", "", raw, flags=re.I).strip()
        parts = [x.strip().strip('"') for x in line.split("|")]
        beat = None
        if parts and re.fullmatch(r"(?:beat\s*)?(\d+|-|—|none|n/a)", parts[0], flags=re.I):
            found = re.findall(r"\d+", parts[0])
            beat, parts = (int(found[0]) if found else None), parts[1:]
        if len(parts) < 3 or len(parts[0]) < 8 or parts[0].lower().startswith("action"):
            continue  # prose, headings or the format line echoed back
        old = len(parts) == 7 and parts[6].lower().startswith(("cut", "cont"))  # who | transition, no line
        parts += [""] * (8 - len(parts))
        transition = parts[6] if old else parts[7]
        line = "" if old else parts[6].strip()
        line = "" if line.strip("-—. ").lower() in ("", "none", "n/a", "no") else line
        if ":" in line:  # Speaker: "words", however the quotes came back
            who_says, _, words = line.partition(":")
            line = f'{who_says.strip()}: "{words.strip().strip(chr(34) + chr(8220) + chr(8221)).strip()}"'
        try:
            seconds = float(re.findall(r"\d+(?:\.\d+)?", parts[3])[0])
        except IndexError:
            seconds = 4.0
        action = parts[0].rstrip()
        tokens = [t.strip() for t in re.split(r",|;|\band\b", parts[5]) if t.strip()]
        lead_tokens = {"lead", "the lead", "yes"}
        others = ", ".join(t for t in tokens if t.lower() not in lead_tokens | {"no", "none", "-"})
        lead = any(t.lower() in lead_tokens for t in tokens) or (
            not tokens and bool(re.search(_LEAD_WORDS, action, flags=re.I)))  # no answer: read the action
        if line and ":" not in line:  # no speaker given: whoever is in the shot, the lead first
            first = "Lead" if lead else (others.split(",")[0].strip() if others else "")
            line = f'{first}: "{line.strip(chr(34) + chr(8220) + chr(8221))}"' if first else ""
        shots.append({"beat": beat, "action": action, "shot_size": _snap(parts[1], SHOT_SIZES, "Medium"),
                      "camera_move": _snap(parts[2], CAMERA_MOVES, "Static"),
                      "seconds": float(min(10, max(2, round(seconds)))), "sound": parts[4], "lead": lead,
                      "others": others, "line": line,
                      "transition": "continue" if transition.lower().startswith("cont") else "cut"})
        if pending:
            shots[-1]["new_beat"], pending = pending, None
    return shots


def parse_new_beats(text: str) -> list[str]:
    """Every BEAT line in the writer's reply (the "beat" mode answers with just one)."""
    import re
    return [m.group(1).strip().strip('"').strip()
            for m in re.finditer(r"^\s*(?:[-*>]+\s*)?beat\s*\d*\s*:\s*([^|\n]+)$", text.replace("**", ""),
                                 flags=re.I | re.M) if m.group(1).strip()]


# ---------------------------------------------------------------- storyboard sketches
def sketch_prompt(action: str, shot_size: str, camera_move: str = "", has_cast: bool = False, lead: bool = True,
                  world: str = "", previous: bool = False, scene: str = "", others: str = "") -> str:
    """A storyboard panel for Qwen-Image-Edit-2511 from the world plate (Picture 1), the lead (Picture 2) and,
    when there is one, the panel of the shot before (Picture 3), so the storyboard reads as one sequence.
    With `scene` (a panel without the lead), the world comes from that text and Picture 1 is the panel before,
    as a style reference only: with nobody in it, a panel drawn from the world plate redraws the plate's view.
    `others` describes everyone else in the frame."""
    framing = ", ".join(x for x in (SHOT_SIZES.get(shot_size, shot_size), MOVE_VIEWPOINT.get(camera_move, "")) if x)
    close = shot_size in ("Medium close-up", "Close-up", "Extreme close-up", "Insert")
    style = ("Drawn as a rough black pencil and grey marker storyboard sketch, loose confident lines, simple shading, "
             "black and white only")
    page = "Not a page: no paper, sketchbook, pencils, desk, photographs, multiple panels, cameras, text or borders"
    if scene:
        return _join("One single storyboard frame that fills the entire image edge to edge: " + framing,
                     "In this frame: " + action if action else "", "The world of the film: " + scene, style,
                     "Picture 1 is only a style reference: the storyboard frame of the shot just before this one. Draw "
                     "in exactly the same style, as the next moment of the same scene, from a new camera position; do "
                     "not repeat its composition" + ("" if others else " and leave out anyone in it"),
                     people_note(False, others), page)
    return _join("One single storyboard frame that fills the entire image edge to edge: " + framing,
                 "In this frame: " + action if action else "", style,
                 ("The location of Picture 1 is only glimpsed behind" if close else
                  "The place is the location of Picture 1" + (" (" + world + ")" if world else "")) +
                 "; choose the camera position this framing needs, do not copy the layout of Picture 1",
                 (lead and has_cast and "The lead is the person from Picture 2 (same hair, build and clothing), posed "
                  "by this frame's action; do not copy the layout of Picture 2"), people_note(lead, others),
                 previous and ("Picture " + ("3" if has_cast and lead else "2") + " is the storyboard frame of the "
                               "shot just before this one: draw in exactly the same style, with the same time of day "
                               "and weather, as the next moment of the same scene. This frame cuts to a new camera "
                               "angle, so do not repeat its composition"), page)


def storyboard_guide(picture: int, lead: bool, look: str = "", others: str = "") -> str:
    """How a frame follows its storyboard drawing (Picture 3, or Picture 2 in a shot without the lead's portrait)."""
    follow = (", where the people are placed and how they pose" if lead or others else
              " (leave out any person drawn in it)")
    return (f"Picture {picture} is the storyboard drawing of this shot: use its composition, camera angle, framing"
            f"{follow}, but render {MEDIUM_FINISHED[medium(look)]} with the place and light of Picture 1; nothing "
            "pencil-drawn or sketched")


def _join(*parts: str) -> str:
    return " ".join(part.strip().rstrip(".") + "." for part in parts if part and part.strip())


def cast_prompt(cast: str, scene: str, look: str) -> str:
    """Character reference portrait for HiDream-O1, reused by every later frame. Drawn in the look's medium, so
    an anime film's lead is an anime character from the start."""
    return _join("Three-quarter body shot, eye-level, front view. A casting reference image of a single person "
                 "standing alone and facing the camera with a neutral expression", cast,
                 "The background is one seamless, plain, light grey colour that fills the whole frame, with no "
                 "equipment, props or edges visible. Even, soft, frontal lighting",
                 MEDIUM_PORTRAIT[medium(look)], "No text")


def people_note(lead: bool, others: str = "") -> str:
    """Say who is in frame: unasked-for extra people are the biggest artifact source, and anyone besides the lead
    must not borrow the lead's face."""
    if others:
        return ((f"Also in the frame: {others}. " if lead else f"In the frame: {others}; the lead is not in this shot. ")
                + "Everyone besides the lead looks clearly different from the lead: a different face, age, hair and "
                "clothing. No one else is in the frame")
    return ("The lead is the only person in the frame" if lead else "There are no people anywhere in this shot")




def world_plate_prompt(scene: str, look: str) -> str:
    """The film's world for HiDream-O1: an empty location plate. Nobody is in it, so no shot inherits a stray face
    from it; the lead and the other characters are added shot by shot."""
    return _join("Wide establishing view of this world, from wherever it looks most striking", scene,
                 "The place is completely deserted and uninhabited: nobody is there, no people, no figures, "
                 "no silhouettes", LOOKS.get(look, look), MEDIUM_FRAME[medium(look)] + ", no text or lettering")


PEOPLE_CHECK = ("Look carefully at this image. Is there any person, human figure, silhouette, face or body part "
                "anywhere in it, even small or far away? Answer with exactly one word: YES or NO.")


def shot_prompt(action: str, shot_size: str, look: str, continuity: str = "", has_cast: bool = False,
                camera_move: str = "", lead: bool = True, world: str = "", identity: str = "", cast: str = "",
                storyboard: bool = False, others: str = "", line: str = "") -> str:
    """A shot for Qwen-Image-Edit-2511: Picture 1 is the film's empty world plate (place, light, grade),
    Picture 2, when there is one, the lead's portrait (face, hair, wardrobe), and Picture 3, when there is one,
    the shot's storyboard drawing (composition). `others` describes everyone else in the frame and `line` is what
    is said in the shot."""
    framing = ", ".join(x for x in (SHOT_SIZES.get(shot_size, shot_size), MOVE_VIEWPOINT.get(camera_move, "")) if x)
    who = ("The lead is the person from Picture 2 with exactly the same face, skin tone, hair, build and wardrobe. "
           "Picture 2 is only an identity reference: take their pose, expression and body language from this shot's "
           "action, not from Picture 2, and play it with the emotion the moment calls for. Ignore the studio "
           "backdrop of Picture 2" if has_cast else lead and cast and "The lead: " + cast)
    speaker = line.split(":", 1)[0].strip() if ":" in line else ""
    return _join(
        "Picture 1 is an empty location from a film. Create a shot from that film in this exact place: " + framing,
        "In this shot: " + action if action else "",
        world and "The setting is the world of Picture 1: " + world,
        storyboard_guide(3 if has_cast else 2, lead, look, others) if storyboard else
        "Choose the camera position this shot needs; do not copy the layout of Picture 1, but keep its place, era, "
        "weather, light and colour",
        lead and who, people_note(lead, others), lead and identity and "The lead: " + identity, lead and continuity,
        speaker and f"{'The lead' if speaker.lower() == 'lead' else speaker} is caught mid-sentence, speaking",
        LOOKS.get(look, look) and "Same color grade: " + LOOKS.get(look, look),
        MEDIUM_FRAME[medium(look)] + ", no text, no borders")


def motion_prompt(action: str, camera_move: str, sound: str = "", look: str = "", cast: str = "",
                  shot_size: str = "", continuity: str = "", lead: bool = True, others: str = "",
                  line: str = "") -> str:
    """LTX 2.5 prompt: action, then the camera move (LTX follows early camera language best), then who, any spoken
    line, look and sound. LTX samples without guidance, so everything it must avoid is said here, not in a
    negative prompt."""
    move = CAMERA_MOVES.get(camera_move, camera_move)
    style = LOOKS.get(look, look)
    speaker, _, words = line.partition(":")
    spoken = words.strip().strip('"').strip() if words else ""
    speaker = "The lead" if speaker.strip().lower() == "lead" else speaker.strip()
    return _join(action, move, shot_size and "Framing: " + SHOT_SIZES.get(shot_size, shot_size),
                 lead and cast and "The character: " + cast,
                 lead and continuity and "These details stay exactly the same throughout: " + continuity,
                 people_note(lead, others),
                 spoken and f'{speaker} says "{spoken}" clearly, lips moving in sync',
                 style and "Cinematic style: " + style,
                 "Natural, physically plausible motion, consistent faces, no cuts, no captions or on-screen text",
                 sound and "Audio: " + sound + ("" if not spoken else ", under the spoken line"))


