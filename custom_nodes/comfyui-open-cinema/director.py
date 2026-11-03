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
    "illustration": "Still frame from an illustrated or 2D animated feature, following the specified visual style",
    "cg": "Still frame from a computer-animated feature, following the specified visual style",
    "stopmotion": "Still frame from a stop-motion feature, following the specified materials and visual style",
    "papercut": "Flat layered cut-paper animation, crisp paper silhouettes, matte paper fibres, shallow layered depth; flat paper faces and limbs, not rounded dolls or CGI",
    "shadow_puppet": "Shadow-puppet animation: flat articulated silhouette figures and scenery against a backlit screen, crisp cut-out contours and deliberate shadow shapes",
}
MEDIUM_PORTRAIT = {
    "photo": "Natural photograph with sharp, detailed skin and hair, true-to-life colours",
    "bw": "Black-and-white photograph with sharp, detailed skin and hair",
    "anime": "Clean 2D anime character design drawing, line art and flat cel shading",
    "clay": "A handmade plasticine stop-motion puppet, photographed on set",
    "illustration": "A character design in the specified illustrated or 2D animation style",
    "cg": "A character design in the specified computer animation style",
    "stopmotion": "A stop-motion character in the specified materials and visual style",
    "papercut": "A flat articulated cut-paper character design, paper face and limbs, crisp cut edges and matte paper fibres; not a rounded puppet",
    "shadow_puppet": "A single flat articulated shadow-puppet character, with a distinctive cut-out silhouette and recognizable profile, shown against a backlit screen",
}
MEDIUM_FINISHED = {  # what a storyboard drawing turns into
    "photo": "a real photographic film frame in full colour",
    "bw": "a real black-and-white photographic film frame",
    "anime": "a finished 2D anime frame",
    "clay": "a finished stop-motion claymation frame",
    "illustration": "a finished illustrated or 2D animated film frame",
    "cg": "a finished computer-animated film frame",
    "stopmotion": "a finished stop-motion film frame",
    "papercut": "a finished flat layered cut-paper animation frame",
    "shadow_puppet": "a finished shadow-puppet animation frame with flat articulated silhouettes against a backlit screen",
}
_MEDIUM_NEGATIVE = {
    "photo": "illustration, painting, cartoon, anime, 3d render, CGI, video game, plastic skin",
    "bw": "colour, illustration, painting, cartoon, anime, 3d render, CGI, plastic skin",
    "anime": "photograph, photorealistic, live action, 3d render, CGI",
    "clay": "live action, real people, illustration, anime, CGI",
    "illustration": "photograph, photorealistic, live action, 3d character render, CGI characters, volumetric characters",
    "cg": "live action, photograph, flat 2D line art",
    "stopmotion": "live action, real people, flat illustration",
    "papercut": "photograph, real people, 3d render, rounded doll, plastic, clay, volumetric face",
    "shadow_puppet": "photorealistic human face, realistic skin texture, three-dimensional character, separate duplicate actor",
}


def medium(look: str) -> str:
    if look in LOOK_MEDIUM:
        return LOOK_MEDIUM[look]
    import re
    text = re.sub(r"\b(?:not|no|without|avoid|never)\s+(?:a\s+)?(?:3d|3-d|cgi|computer[- ]animated)\b|\b(?:3d|cgi)[- ]free\b", "", (look or "").lower())
    # A live-action scene may contain a stop-motion set or puppet. Treating
    # that as an all-puppet film would explicitly exclude its human actors.
    live = re.sub(r"\b(?:not|no|without|avoid|never)\s+(?:a\s+)?live[- ]action\b", "", text)
    if re.search(r"\blive[- ]action\b", live) and re.search(r"\bstop[- ]motion\b", live):
        return "photo"
    shadow = re.sub(r"\b(?:not|no|without|avoid|never)\s+(?:a\s+)?shadow[- ]puppet(?:ry|s)?\b", "", text)
    if re.search(r"\bshadow[- ]puppet(?:ry|s)?\b", shadow) and not re.search(r"\b(?:live[- ]action|photorealistic|photographic|3[ -]?d|cgi)\b", shadow):
        return "shadow_puppet"
    if any(x in text for x in ("paper-cut", "paper cut", "papercut", "cut-paper")):
        return "papercut"
    if any(x in text for x in ("claymation", "plasticine")):
        return "clay"
    if "stop-motion" in text or "stop motion" in text:
        return "stopmotion"
    if "anime" in text:
        return "anime"
    if not re.search(r"\b(?:2[ -]?d|hand[- ]drawn)\b", text) and (any(x in text for x in ("3d animation", "3d animated", "3d cartoon", "3-d cartoon", "three-dimensional cartoon", "3d render", "cgi", "computer animation", "computer-animated", "computer-generated")) or
            "cartoon" in text and re.search(r"\b(?:3[ -]?d|three[- ]dimensional)\b", text)):
        return "cg"
    if any(x in text for x in ("cartoon", "animation", "animated", "illustrat", "watercolor", "watercolour", "painting", "painted", "hand-drawn", "gouache", "pixel art")):
        return "illustration"
    if any(x in text for x in ("black and white", "black-and-white", "monochrome")):
        return "bw"
    return "photo"


def cartoon_2d_default(idea: str) -> bool:
    """A generic cartoon means 2D unless the director specifies a different medium."""
    import re
    text = (idea or "").lower()
    if not re.search(r"\bcartoons?\b", text):
        return False
    text = re.sub(r"\b(?:not|no|without|avoid|never)\s+(?:a\s+)?(?:3d|3-d|cgi|computer[- ]animated)\b|\b(?:3d|cgi)[- ]free\b", "", text)
    if re.search(r"\b(?:stop[- ]motion|claymation|plasticine|paper[- ]cut|cut[- ]paper|papercut)\b", text):
        return False
    # A 3D camera or object can occur in an expressly hand-drawn cartoon; it does not
    # change the requested animation medium. Keep genuinely mixed-medium requests.
    if re.search(r"\b(?:2[ -]?d|hand[- ]drawn)\b", text):
        text = re.sub(r"\b3[ -]?d\s+(?:camera|background|prop|object)s?\b", "", text)
    return not re.search(r"\b(?:2\.5[ -]?d|3[ -]?d|three[- ]dimensional|cgi|computer[- ]animat\w*|computer[- ]generated|pixar|stop[- ]motion|claymation|plasticine|paper[- ]cut|cut[- ]paper|papercut)\b", text)


def cartoon_look(look: str, idea: str) -> str:
    """Preserve the generated art direction while resolving an unspecified cartoon to 2D."""
    import re
    if not look or not cartoon_2d_default(idea):
        return look
    # Preserve explicitly requested 3D camera/prop/background details in a 2D film.
    protected = []
    def keep_detail(match):
        phrase = match.group(0)
        if re.search(re.escape(phrase), idea, flags=re.I):
            protected.append(phrase)
            return f"CARTOONDETAILTOKEN{len(protected)-1}"
        return phrase
    look = re.sub(r"\b3[ -]?d\s+(?:camera|background|prop|object)s?\b", keep_detail, look, flags=re.I)
    look = re.sub(r"\b(?:not|no|without|avoid|never)\s+(?:a\s+)?(?:3d|3-d|cgi|computer[- ]animated)(?:\s+(?:animation|rendering|characters))?\b|\b(?:3d|cgi)[- ]free\b", "", look, flags=re.I)
    cleaned = re.sub(r"\b(?:3[ -]?d|three[- ]dimensional|cgi|computer[- ]animated)\s*(?:animation|animated|render(?:ing)?|film)?", "2D animation", look, flags=re.I)
    cleaned = re.sub(r"\b(?:photorealistic|live[- ]action|photograph(?:ic)?)\b", "illustrated", cleaned, flags=re.I)
    cleaned = re.sub(r"\bPixar(?:[- ]style)?\b", "illustrated", cleaned, flags=re.I)
    cleaned = re.sub(r"\bvolumetric\b", "painted", cleaned, flags=re.I)
    for index, phrase in enumerate(protected):
        cleaned = cleaned.replace(f"CARTOONDETAILTOKEN{index}", phrase)
    return "Hand-drawn 2D cartoon animation, flat illustrated characters and backgrounds. " + cleaned


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
    music = SCORE_STYLES.get(look) or (f"an original instrumental score suited to the film's visual direction: {look}"
                                       if look else SCORE_STYLES["None"])
    return _join(f"A movie title card for \"{title}\" glows on a dark background; the camera slowly pushes in",
                 f"Audio: {music}. A movie trailer soundtrack: it opens with a single deep boom, then a steady "
                 "rhythm of percussion hits about once per second, building in intensity with instrumentation "
                 "suited to the score, punctuated by cinematic impacts, ending on one final hit followed by "
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
    """Instruction for an open LLM (Gemma 4 12B (8-bit) via ComfyUI TextGenerate) to write the film's lead."""
    film = (f"THE WORLD OF THE FILM (the character must belong to this exact setting, era and culture): "
            f"{world or 'not specified'}\nFilm title: {title or 'Untitled'}\n"
            f"Visual look: {look} ({LOOKS.get(look, '')})")
    if mode == "continuity":
        return ("You are the script supervisor on a feature film. From the lead character description below, list "
                "the 4 to 6 visual details that must never change from shot to shot (key wardrobe colours, "
                "hairstyle, distinctive features, signature prop).\n\n"
                f"Lead: {draft}\n\nReply with exactly one line and nothing else:\nCONTINUITY: comma-separated details")
    if mode == "identity":
        return ("You are a casting director. The attached image is the reference portrait of a film character. "
                "It may be a photograph, drawing, puppet, animation or another stylized image. Describe the character "
                "as depicted, regardless of medium. Describe only what makes this character recognisable, so an "
                "image model can reproduce the same character in every shot: species or kind, face shape, eyes, "
                "distinctive markings, colour, surface and build. Describe fur, feathers, scales, skin or hair only "
                "when actually visible; an animal is not a human. Be specific and plain. "
                "No clothing, props, background, emotion, analysis or "
                "comments about the request.\n\n"
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
    "LOOK": "LOOK: an original, specific visual direction in one sentence: the medium (live action, 2D animation, "
            "3D animation, stop-motion, or another film medium), lighting, colour and camera or texture. "
            "Invent a look that suits this film; do not choose from a fixed list",
    "PALETTE": "PALETTE: four hex colours for the film's titles and graphics, in this order: background (very dark), "
               "ink (light, for text), accent (the film's signature colour), glow (a lighter tint of the accent)",
    "LEAD": "LEAD: one paragraph of 40 to 70 words describing only what a camera sees of the lead character: age, "
            "build, face, hair, the exact wardrobe with colours and materials, and a signature prop if they would carry one. No name, "
            "no backstory",
    "CONTINUITY": "CONTINUITY: 4 to 6 short comma-separated details of the lead that must never change between shots",
    "CHARACTERS": "CHARACTERS: the other characters the story needs, separated by ' / ', each as 'Name: 15 to 30 "
                  "words of what a camera sees (age, build, face, hair, clothing)', each clearly different from the "
                  "lead; a crowd or group can be one entry; write none if the story needs only the lead",
    "BEATS": "BEATS: 5 to 7 story beats separated by ' / ', in order, each a concrete visible action and its "
             "consequence. Establish the lead's goal and an obstacle; make a choice or discovery change the situation; "
             "escalate to a decisive action and show its aftermath. Each beat follows from the last, names its place "
             "and any characters needed, and can be filmed in a few seconds. Each beat is one sentence of at most "
             "25 words; show the story through actions, not explanations of story structure or isolated mood descriptions",
    "TRAILER": "TRAILER: 4 to 6 trailer title cards separated by ' / ', each at most 6 words, building tension from "
               "the world to the stakes, in the voice of a great movie trailer; the last card is the film's title",
}
_STORY_WANTS = {"everything": STORY_LABELS, "title": ("TITLE",), "logline": ("LOGLINE",), "world": ("WORLD",),
                "look": ("LOOK",), "trailer": ("TRAILER",), "beats": ("BEATS",), "more beats": ("BEATS",),
                "characters": ("CHARACTERS",)}


def story_brief(target: str, idea: str = "", title: str = "", logline: str = "", world: str = "", look: str = "",
                lead: str = "", beats: str = "", count: int = 3, characters: str = "", creative_seed: int = 0,
                avoid_title_words: str = "") -> str:
    """Instruction for an open LLM (Gemma 4 12B (8-bit)) to write the whole story page or one field of it,
    consistent with whatever the director has already written. "more beats" continues the story in `beats`
    (one numbered beat per line) with `count` new beats."""
    wants = _STORY_WANTS.get(target, STORY_LABELS)
    known = [("The director's idea", idea), ("Title", "" if title.strip().lower() == "untitled film" else title), ("Logline", logline), ("World", world),
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
                "Everything must fit together. Give the lead a specific objective, an obstacle with visible stakes, "
                "a consequential choice and an ending that resolves or deliberately transforms the objective. "
                "Introduce supporting characters or groups only where they affect the action. CHARACTERS contains "
                "descriptions, never plot events; BEATS contains the events, never omit its label.")
        if not any((idea.strip(), logline.strip(), world.strip(), lead.strip(),
                    title.strip() if title.strip().lower() != "untitled film" else "")):
            # A seed chooses a combination of broad starting points, not a closed catalogue of stories or styles.
            # An explicit director's idea always takes precedence and receives no imposed creative direction.
            import random
            rng = random.Random(creative_seed)
            domains = ("an intimate family relationship", "an unexpected friendship", "a community ritual",
                       "an animal's perspective", "a creative craft", "a sporting challenge", "a historical journey",
                       "a comic misunderstanding", "an ecological mystery", "a scientific discovery",
                       "a workplace dilemma", "an impossible encounter", "a celebration", "a rescue")
            settings = ("a coastal village", "an ordinary apartment building", "a mountain landscape",
                        "a busy marketplace", "a remote island", "a small travelling theatre", "a farm",
                        "a river crossing", "an unfamiliar planet", "a public garden", "a desert settlement",
                        "a forest", "a school", "a train journey")
            tones = ("playful", "tender", "suspenseful", "hopeful", "bittersweet", "wondrous", "restless",
                     "joyful", "contemplative", "surreal", "energetic", "mysterious")
            visuals = ("observational live-action photography", "hand-painted 2D animation", "tactile stop-motion",
                       "black-and-white photography", "expressive 3D animation", "sunlit naturalistic live action",
                       "graphic illustration", "pastel-coloured live action", "shadow puppetry",
                       "vibrant cel animation", "soft-grained documentary photography", "miniature stop-motion")
            task += ("\n\nFor this blank spark, explore these loose starting points: " + rng.choice(domains) +
                     "; " + rng.choice(settings) + "; " + rng.choice(tones) +
                     "; visual inspiration: " + rng.choice(visuals) +
                     ". Transform or depart from them when a better coherent idea emerges; any visual direction or "
                     "medium is allowed. Avoid stock genre "
                     "phrases and repeated naming formulas; give the lead a specific life and wardrobe suited to "
                     "the actual setting. Do not default to a dystopian city or an archivist.")
    else:
        task = (f"Write a fresh {' and '.join(w.lower() for w in wants)} for this film. It must fit everything "
                "else already established about the film.")
    if target in ("everything", "title") and avoid_title_words.strip():
        task += " Avoid these repeated title words unless explicitly present in the director's idea: " + avoid_title_words.strip() + "."
    if target in ("everything", "look") and cartoon_2d_default(idea):
        task += " The director asked for a cartoon without specifying computer-animated characters: use hand-drawn or illustrated 2D cartoon animation. Preserve their requested camera, tone and colours."
    return ("You are the writer and production designer of a short cinematic film made with AI.\n" + task +
            ("\n\nWhat is established so far:\n" + context if context else "") +
            f"\n\nReply with exactly these {len(wants)} labelled lines and nothing else:\n" + lines)


def title_words(text: str) -> set[str]:
    import re
    return {w[:-2] if w.endswith("oes") else w[:-1] if w.endswith("s") and not w.endswith("ss") else w
            for w in re.findall(r"[a-z]{3,}", text.lower())}


def prop_prompt(description: str, state: str, look: str) -> str:
    return ("Production prop reference. Exactly one isolated object, fully visible with clear silhouette, "
            "on a plain neutral background; no people, hands, labels or scenery. OBJECT DESIGN: " + description +
            ". CURRENT PHYSICAL STATE: " + state + ". Render the specified state literally. " +
            MEDIUM_FRAME[medium(look)] + ". Film medium: " + look +
            ". The current physical state takes precedence over mood lighting: an unlit object emits no light.")


def prop_reference_direction(picture: int, name: str, description: str, state: str) -> str:
    return (f"Picture {picture} is the authoritative {name} prop design in its required current state. "
            "Replace the storyboard's approximate prop with this exact object: preserve its silhouette, "
            "proportions, material, handle, surface pattern and current light state. Place it naturally at "
            "the storyboard's prop position; do not copy the reference background. "
            f"Design: {description}. Required visible state: {state}. "
            "This prop reference overrides conflicting details in the drawing and general film lighting.")


def previous_frame_direction() -> str:
    return ("Picture 1 is the previous shot's final frame. Carry forward the exact people, object design, "
            "object condition, set geometry and paper or other rendering material into the new setup. "
            "Use the new shot size and written staging for a purposeful new camera composition. "
            "Only include the people named for this new shot. Do not reset the object's condition or replay the prior action.")


def following_frame_prompt(staging: str, shot_size: str, people: str, state: dict, look: str = "",
                           camera_move: str = "", expected_count: int | None = None) -> str:
    """A local edit of an accepted performance, without competing portrait/world aesthetics."""
    facts = "; ".join(f"{key}: {value}" for key, value in state.items() if not key.startswith("Design of "))
    framing = SHOT_SIZES.get(shot_size, shot_size)
    viewpoint = MOVE_VIEWPOINT.get(camera_move, "")
    count_direction = ("No characters are visible in this frame. " if type(expected_count) is int and expected_count == 0 else
                       f"Exactly {expected_count} visible characters in this frame; show each individual only once, with no extra or duplicate figures. "
                       if isinstance(expected_count, int) and not isinstance(expected_count, bool) and expected_count > 0 else "")
    return ("Edit Picture 1 into the next shot. " + framing + ": " + staging + ". "
            + ("Initial camera viewpoint: " + viewpoint + ". " if viewpoint else "") +
            "Preserve the exact existing face, hair, wardrobe, object shape, folds, handle, colours and paper or other rendering material from Picture 1. "
            "Keep the same set, lighting, physical conditions and continuity of the action. "
            "Use the specified camera viewpoint and framing for the new shot; when a different viewpoint is specified, "
            "show the scene from that viewpoint rather than merely cropping Picture 1. "
            "Keep people and objects in their consistent positions in the scene, allowing their appearance and screen positions to change with perspective. "
            + count_direction +
            "Visible cast in this shot: " + people + ". Physical condition at this instant: " + facts + ". "
            + ("Film visual direction: " + look + ". " + MEDIUM_FRAME[medium(look)] + ". " if look else "") +
            "This is the starting pose, before the next action happens. One image, no text.")


def look_for_state(look: str, state: dict) -> str:
    """Object illumination belongs to the state ledger, not a global aesthetic clause."""
    import re
    dark_objects = []
    for key, value in state.items():
        if str(value).strip().lower() in ("unlit", "off", "extinguished"):
            label = re.sub(r"\b(state|light|lighting|illumination|status)\b", "", key, flags=re.I)
            words = re.findall(r"[a-z]+", label.lower())
            if words:
                dark_objects.append(words)
    clauses = re.split(r"[,;]", look)
    return ", ".join(clause.strip() for clause in clauses if clause.strip() and not (
        re.search(r"\b(light|lit|glow|glowing|illumination)\b", clause, re.I) and
        any(all(re.search(r"\b" + re.escape(word) + r"\b", clause, re.I) for word in obj) for obj in dark_objects)))


def ending_frame_prompt(action: str, end_state: str, look: str, state: dict, design: str) -> str:
    import json
    facts = "; ".join(f"{key}: {value}" for key,value in state.items() if not key.startswith("Design of "))
    return ("Edit Picture 1. Change the actors' poses and object positions to this precise visible result: " + end_state + ". "
            "Physical facts at this moment: " + facts + ". "
            "Keep every object's original colour, proportions, material and handle. Keep the same faces, "
            "hair, clothing, set, camera viewpoint, palette and rendering style. Change only what the visible "
            "result requires. An unlit coloured object retains its original colour. One image, no captions.")


def title_brief(idea: str, story: str, avoid_words: str) -> str:
    return ("You are naming a film for its theatrical poster. Return ONLY a JSON array of eight memorable "
            "cinematic titles, best first. Prefer compact 2–4 word names that carry emotional subtext. "
            "A title is NOT a plot summary, newspaper headline, description of an action, or subject-verb-object "
            "sentence. Do not enumerate what the protagonist does. Find a story-specific metaphor, a charged "
            "object, an ironic institutional phrase, or a fragment of dialogue that gains meaning after viewing. "
            "Vary those approaches across candidates. Avoid generic atmospheric nouns, repeated formulas and "
            "vague 'X of Y' titles. Do not reuse words from the repeated-title list, including "
            "singular/plural variants, unless the director explicitly used them in the idea. "
            "The story's provisional title is not a requirement.\nDirector's idea: " + idea +
            "\nRepeated title words: " + avoid_words + "\nStory: " + story)


def frame_repair_prompt(staging: str, requirements_json: str, findings_json: str) -> str:
    import json
    required = json.loads(requirements_json)
    states = required.get("state", {})
    findings = json.loads(findings_json)
    failures = {k:v for k,v in states.items() if any(str(f).startswith(k + ":") for f in findings)}
    if failures:
        required["state"] = states = failures
    if required.get("count") == 1:
        required.pop("people", None)
    requirements_json = json.dumps(required, ensure_ascii=False)
    darkness = any(str(v).lower() in ("unlit", "off", "extinguished") for v in states.values())
    return ("Edit Picture 1 into this exact frozen moment. Preserve its camera, location, "
            "rendering material, character faces and wardrobe. "
            "REQUIRED STAGING: " + staging + ". REQUIRED VISIBLE FACTS: " + requirements_json +
            ". These facts replace the current physical condition and pose. "
            + ("Extinguish the light source completely. Replace its flame with a short black wick. "
               "Its interior is dark and its opaque surfaces receive only ambient light. " if darkness else "") +
            f"The finished frame contains exactly {required.get('count', 'the specified')} people: " +
            ", ".join(required.get("visible_names") or []) + ". Keep only these people.")


def select_title(text: str, avoid_words: str, idea: str) -> str:
    import json, re
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    candidates = json.loads(raw)
    if not isinstance(candidates, list) or not candidates or any(not isinstance(s, str) for s in candidates):
        raise ValueError("The title writer must return a list of title candidates")
    banned = title_words(avoid_words) - title_words(idea)
    for title in candidates:
        title = title.strip().strip('"')
        if 1 <= len(title.split()) <= 8 and len(title) <= 100 and not (title_words(title) & banned):
            return title
    raise ValueError("All title candidates repeat recent titles. Generate another set.")


def continuity_repair_brief(text: str, context_json: str, shot_count: int) -> str:
    checked = None
    try:
        checked = parse_continuity(text, shot_count, recover_missing=False)
        error = ("; ".join(checked["issues"]) if checked["issues"] else
                 "The draft is structurally valid. Verify its facts against the script.")
    except (ValueError, TypeError, KeyError) as exc:
        error = str(exc)
    try:
        conflicts = cast_roster_conflicts(json_object(context_json), checked)
    except (ValueError, TypeError, KeyError):
        conflicts = []
    roster_note = ("Opening direction mentions omitted named cast: " +
                   "; ".join(f"shot {x['index']}: {x['name']}" for x in conflicts) +
                   ". Recheck whether each person is actually visible at the start; "
                   "do not count offscreen people, future entrances, memories or depictions. "
                   "If visibility is unclear, use null for start_cast. ") if conflicts else ""
    return (continuity_brief(context_json) + "\nCorrect this draft, returning the complete JSON object. " + roster_note +
            "Use a small set of stable exact initial keys. Copy those keys VERBATIM into changes and check arrays; "
            "never append the value or a state name to a key. Only track visible object states; character "
            "locations can change at a cut, and offscreen locations do not need state facts. Fix starting "
            "states that already depict an action's result. Do not erase a contradiction; put it in issues. "
            "Validation: " + error + "\nDraft:\n" + text)


def _clean_line(line: str) -> str:
    """Strip list bullets and markdown headings, but not the '#' of a hex colour."""
    import re
    return re.sub(r"^(?:[-*>]+\s*|#+\s+)+", "", line.strip()).strip()


def parse_story(text: str, target: str = "everything", idea: str = "") -> dict[str, str]:
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
    if "look" in out:  # retain free-form directions; canonicalize exact legacy preset names
        out["look"] = cartoon_look(out["look"], idea)
        out["look"] = next((l for l in LOOKS if l.lower() == out["look"].lower()), out["look"])
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
        # Plot lines accidentally emitted under CHARACTERS are not usable character descriptions.
        out["characters"] = "\n".join(c for c in people if re.match(r"^[^:]{1,60}:\s*\S", c))
    if "beats" in out:  # one beat per line, without the model's own numbering
        beats = [re.sub(r"^\s*(?:beat\s*)?\d+\s*[.):-]\s*", "", b, flags=re.I).strip().strip('"').strip()
                 for b in out["beats"].split("/")]
        out["beats"] = "\n".join(b for b in beats if b)
    return out


# ---------------------------------------------------------------- AI shot writer
SHOT_MODES = ("board", "next", "rewrite", "beat")
DIALOGUE_MODES = ("auto", "minimal", "dialogue", "silent")
_DIALOGUE_DIRECTION = {
    "auto": "Let the story, genre, and character relationships decide how much dialogue is needed. "
            "Use natural, purposeful lines for conversations and character-driven scenes, and silence when visuals tell the story better.",
    "minimal": "Use dialogue sparingly, only at important moments; let action and images carry most of the story.",
    "dialogue": "Write dialogue for conversations and character-driven moments wherever it advances the scene. "
                "Use concise, distinct voices and alternate speakers across shots when appropriate; do not force speech into every shot.",
    "silent": "This film has no spoken dialogue. Always write - for the line field; tell the story through action and sound instead.",
}
_NEW_BEAT = ("BEAT: one sentence of at most 18 words saying what the lead does and where, something a camera can "
             "see, that continues the story")
SHOT_FIELDS = ("beat", "action", "shot_size", "camera_move", "seconds", "sound", "lead", "others", "line",
               "transition", "frame_source", "start_frame", "end_state")
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
                       ("continue" if shot.get("transition") == "continue" else
                        "reframe" if shot.get("frame_source") == "previous_end" else "cut"),
                       str(shot.get("start_frame") or "-").replace("|", "/"),
                       str(shot.get("end_state") or "-").replace("|", "/")])


def shot_list_text(shots: list) -> str:
    return "\n".join(f"{n + 1}. {shot_line(s)}" for n, s in enumerate(shots))


def beat_list_text(beats: list) -> str:
    return "\n".join(f"{n + 1}. {b}" for n, b in enumerate(beats))


def shot_brief(mode: str, title: str = "", logline: str = "", world: str = "", look: str = "", lead: str = "",
               continuity: str = "", shots: str = "", index: int = 1, count: int = 5, beats: str = "",
               write_beats: str = "", characters: str = "", dialogue_mode: str = "auto", idea: str = "") -> str:
    """Instruction for an open LLM (Gemma 4 12B (8-bit)) to write the storyboard. `beats` is the story as numbered beats
    (optional); `shots` the board so far as numbered shot lines, which stay as they are; `index` is 1-based.
    board: the shots for the beats in `write_beats` (or `count` shots that start, or continue and end, the film);
    next: the one shot after the board, telling beat `write_beats`; rewrite: shot `index` again; beat: the story
    beat shot `index` tells. `write_beats` "new" means the story has run out: every shot also writes a new beat
    (a BEAT line before it), so the story grows with the film."""
    film = "\n".join(f"{k}: {v}" for k, v in (("Title", title), ("Logline", logline), ("World", world),
                                                 ("Look", look), ("The lead", lead), ("Design and continuity notes", continuity),
                                                 ("Other characters", characters and "\n" + characters))
                     if v and v.strip())
    fmt = ("SHOT: beat | action | size | camera move | seconds | sound | who | line | transition | start frame | end state\n\n"
           "beat: the number of the story beat this shot tells" + ("" if beats.strip() else " (write -)") + "\n"
           "action: one or two sentences, present tense, concrete and physical. Start with the exact place in this "
           "film's world where the camera is, then one specific visible action, interaction or change. Show how "
           "people and important props are positioned relative to each other. Call the lead "
           "the lead and other characters by their names. No thoughts, no cameras or camera words. If the lead is "
           "not in the shot, do not mention them at all\n"
           f"size: exactly one of: {', '.join(SHOT_SIZES)}\n"
           f"camera move: exactly one of: {', '.join(CAMERA_MOVES)}\n"
           "seconds: a whole number from 3 to 8\n"
           "sound: what we hear besides speech, 4 to 12 words (ambience, effects, music)\n"
           "who: everyone in the shot, comma-separated: lead, the names from Other characters, or a group "
           "described in a few words; none for a shot of only the place or an object. A POV shot excludes the "
           "lead unless their body is actually visible\n"
           "line: what is said aloud in this shot, as Speaker: \"words\" (Lead or a character's name, at most 14 "
           "words), or - for no speech. The speaker must be visible in who and in the start frame. "
           "Write only one speaker per shot, with a line short enough to say naturally in the available seconds.\n"
           "transition: choose cut, reframe, or continue. Use cut for a new scene, time jump, or independent view. "
           "Use reframe when the very next moment needs a different angle on the same ongoing action: the new view "
           "is made from the preceding shot's ending, retaining people, props and their positions. For a reframe, "
           "specify the actual new camera viewpoint in the start frame (for example over a named person's shoulder, "
           "or from a named side); a shot size alone is a crop, not a viewpoint. Describe whose face is visible, "
           "whose back or shoulder is in the foreground, and which named people are outside the frame when relevant. "
           "A foreground shoulder belongs to that same person and must not appear as another figure. "
           "Include only people actually visible in who; do not invent an angle, person, or exclusion contrary to the story. "
           "Use continue when the camera keeps rolling without a cut from the preceding shot's ending. "
           "Choose only when the story supports it; the first shot of the film, with no preceding shot, must be cut.\n"
           "start frame: one frozen moment BEFORE the action completes. Specify viewpoint, foreground subject, "
           "left/right placement, hands and prop ownership. For an entrance, the arriving person is initially offscreen; "
           "for a visible handoff, show the participants and object needed for the action; a reaction shot may leave "
           "other people offscreen. Never ask an already visible actor to appear again. "
           "This becomes the storyboard and first video frame, not the action's aftermath\n"
           "end state: the visible result at the end of the action, including who now holds the important object. "
           "The next shot must begin from this result, not reset it")
    head = ("You are the director and storyboard artist of a short cinematic film made with AI. Every shot is one "
            "moving image of a few seconds, generated from a still of the film's world and a photo of the lead, so "
            "every shot happens in that world. The lead's face comes from their photo; other characters are drawn "
            "from their descriptions, so name them exactly as written, and keep a shot to the people it needs.\n\n"
            "HOW THE SHOTS GO TOGETHER\n"
            "- The story is the lead's: most shots show what they do. A shot without the lead is usually another "
            "character, a close detail (an object, the light, the weather on a surface) or the opening view of the "
            "world; avoid repeating a wide view of the world.\n"
            "- Choose coverage to make the action legible: establish geography, show a meaningful action or reaction, "
            "and preserve screen direction and the position of people and props across cuts. For an exchange or "
            "reaction within the same scene, a reframe can follow the preceding performance from another angle; "
            "continue can extend an uninterrupted camera move. Change location only "
            "when the story does; do not invent travel or a new angle merely for variety.\n"
            "- Each shot picks up the consequence of the preceding beat and advances the goal, obstacle or decision. "
            "Keep time, weather and character placement consistent unless the story changes them.\n"
            "- Include every named person, creature, machine or group actually visible in the action in who. "
            "Supporting characters and crowds may share the frame with the lead when the scene needs them.\n"
            "- Every detail fits the world exactly.\n\nTHE FILM\n" + (film or "(nothing yet)"))
    head += ("\nDIRECTABLE COVERAGE\nChoose the subject the audience must see to understand each beat. "
             "Use inserts for decisive object changes, close views for reactions, and two-shots for exchanges. "
             "Do not stage every beat as a full-body figure in the same wide landscape. When showing a handoff, "
             "make the object and the relevant hands legible; a reaction or reply may leave other people offscreen. "
             "Keep a recurring prop's shape, material and owner "
             "consistent; state changes only when an action causes them. Use one achievable action per shot, "
             "not a montage or multiple locations. Use screen-left and screen-right to hold the action axis.")
    head += "\n\nDIALOGUE DIRECTION\n" + _DIALOGUE_DIRECTION.get(dialogue_mode, _DIALOGUE_DIRECTION["auto"])
    if idea.strip():
        head += ("\n\nORIGINAL CREATIVE BRIEF OR SCRIPT\n" + idea.strip() +
                 "\nRespect explicitly requested dialogue and character voices where they fit the story and "
                 "the dialogue direction. Do not mistake instructions about style for spoken lines.")
    story = f"\n\nTHE STORY, BEAT BY BEAT (the film tells these in order)\n{beats}" if beats.strip() else ""
    board = (f"\n\nTHE FILM SO FAR (these shots stay exactly as they are)\n{shots}" if shots.strip() else "")
    vary = "Choose shot size and camera movement for clarity and dramatic purpose; hold still when appropriate."
    one = "Reply with exactly one line and nothing else:\n"
    extend = bool(story) and write_beats.strip() == "new"
    told = len([b for b in beats.splitlines() if b.strip()])
    if extend:  # each shot tells a new beat, written on the line before it
        fmt = (_NEW_BEAT + f"\nSHOT: the same number as that beat (the story continues from beat {told + 1}) | action | "
               "size | camera move | seconds | sound | who | line | transition | start frame | end state\n\n" + fmt.split("\n\n", 1)[1])
    if mode == "beat":
        return (head + story + board + f"\n\nShot {index} is not in the story yet. Write the story beat it tells, in "
                "the same voice as the beats above, so it fits between the beats around it.\n\n" + one +
                "BEAT: one sentence of at most 18 words saying what the lead does and where, something a camera can see")
    if mode == "next":
        task = ("Write the ONE shot that comes right after the film so far: the next moment of the story" +
                (", a new beat that continues the story past its last beat" if extend else
                 f", telling beat {write_beats.strip()}" if story and write_beats.strip() else "") +
                ", choosing framing and movement that serve this next moment.")
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
                    "the visible cause and result of its beat" + (" and fits between the shots that are already made" if board
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


def shot_review_brief(brief: str, draft: str) -> str:
    """A separate script-supervision pass before expensive images. Same schema in app and ComfyUI."""
    return (brief + "\n\nPROPOSED DRAFT TO REVIEW (not approved footage)\n" + draft +
            "\n\nYou are now the script supervisor and editor. Correct this draft against the story and the "
            "director's continuity notes. Return the complete corrected requested rows, in the same format, "
            "with the same beat numbers and row count. No commentary.\n"
            "CHECK BEFORE YOU WRITE:\n"
            "1. Each action must show its assigned beat, and its end state must be the result of that action. "
            "Do not put travel or the next beat's action into this beat's ending.\n"
            "2. The next starting state must preserve the preceding result: prop ownership, light state, "
            "positions and screen direction. No reset or unexplained travel back and forth.\n"
            "3. Important props keep the same shape, material, construction and number. Retain every stated "
            "design detail; choose a simple consistent shape if unspecified and repeat its compact description "
            "in every start frame where it is visible. Never replace the prop with a different kind of object.\n"
            "4. For an on-screen handoff, stage the people and object needed for the action with clear positions "
            "and the object at the correct hands. For a reaction or reply, other people may remain offscreen. "
            "List only visible people in who, including anyone partly visible in the foreground. "
            "For lead dialogue, use the speaker name Lead, not the lead's proper name. Do not combine an entrance "
            "and an exchange in one shot. If the actor is already visible, describe their movement, not their appearance.\n"
            "5. Make the decisive action large enough to read. Use an insert for object manipulation, a "
            "two-shot for an exchange, a reaction close-up when a reaction carries a beat. Avoid a sequence "
            "of full-body poses in a wide landscape. Respect the shot size in the start frame: a close-up "
            "cannot simultaneously show everyone's feet and the entire location.\n"
            "6. Keep start frame and end state concise but concrete. The start is a frozen preparatory moment, "
            "not the completed action. For a reframe, describe the camera viewpoint and who is seen face-on, "
            "from behind or partly in the foreground; say who is offscreen where needed. A foreground person "
            "is the same individual, not another copy. Preserve the director's story rather than inventing "
            "extra events, people or exclusions.")


def lead_name(description: str) -> str:
    import re
    match = re.match(r"^\s*([A-Z][\w'’-]*(?:\s+[A-Z][\w'’-]*){0,2})\s*[,:(—]", description or "")
    return match[1] if match else ""


def normalize_shot_cast(shot: dict, description: str) -> dict:
    """A writer may use the lead's proper name in WHO. It must still select the portrait, not a new actor."""
    name = lead_name(description)
    if not name:
        return shot
    people = [p.strip() for p in (shot.get("others") or "").split(",") if p.strip()]
    if any(p.casefold() == name.casefold() for p in people):
        shot["lead"] = True
        shot["others"] = ", ".join(p for p in people if p.casefold() != name.casefold())
    speaker, colon, words = (shot.get("line") or "").partition(":")
    if colon and speaker.strip().casefold() == name.casefold():
        shot["line"] = "Lead:" + words
    return shot


def parse_shots(text: str, lead_description: str = "") -> list[dict]:
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
        parts += [""] * (10 - len(parts))
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
                      "start_frame": parts[8].strip("-— "), "end_state": parts[9].strip("-— "),
                      "transition": "continue" if transition.lower().startswith("cont") else "cut",
                      "frame_source": "previous_end" if transition.lower().startswith("reframe") else "storyboard"})
        if pending:
            shots[-1]["new_beat"], pending = pending, None
    return [normalize_shot_cast(s, lead_description) for s in shots]


def parse_new_beats(text: str) -> list[str]:
    """Every BEAT line in the writer's reply (the "beat" mode answers with just one)."""
    import re
    return [m.group(1).strip().strip('"').strip()
            for m in re.finditer(r"^\s*(?:[-*>]+\s*)?beat\s*\d*\s*:\s*([^|\n]+)$", text.replace("**", ""),
                                 flags=re.I | re.M) if m.group(1).strip()]


# ---------------------------------------------------------------- storyboard sketches
def sketch_prompt(action: str, shot_size: str, camera_move: str = "", has_cast: bool = False, lead: bool = True,
                  world: str = "", previous: bool = False, scene: str = "", others: str = "",
                  cast: str = "", continuity: str = "", start_frame: str = "", expected_cast: int | None = None,
                  cast_uncertain: bool = False) -> str:
    """Plan composition from text, without a location photograph biasing every panel toward the same view.

    Legacy reference arguments remain accepted by saved integrations; no image references are used.
    The film's rendering medium is deliberately absent: this is a working pencil drawing.
    """
    framing = SHOT_SIZES.get(shot_size, shot_size)
    close = shot_size in ("Medium close-up", "Close-up", "Extreme close-up", "Insert")
    import re
    # Descriptions often repeat the film medium. A planning drawing must not inherit that rendering style.
    def design(text):
        return re.sub(r"\b(?:handmade\s+)?(?:paper[- ]cut|cut[- ]paper|2d|3d|stop[- ]motion|claymation|photorealistic|anime)\b", "", text, flags=re.I)
    count = None if cast_uncertain else expected_cast if expected_cast is not None else character_count(lead, others)
    roster = [entry.strip() for entry in others.split(";") if entry.strip()]
    # A scene ledger can select one member of a group described in the character bible.
    # Scope that costume to one performer, without shrinking intentional crowds.
    if expected_cast is not None and len(roster) + int(lead) == expected_cast:
        plural = {"soldiers": "soldier", "guards": "guard", "workers": "worker", "visors": "visor", "faces": "face"}
        roster = [re.sub(r"\b(soldiers|guards|workers|visors|faces)\b", lambda m: plural[m[0].lower()], entry, flags=re.I) for entry in roster]
    cast_limit = (f"Exactly {count} visible characters, each appearing once. Empty background with no other figures or bystanders"
                  if count is not None else "Show the participants specified in the staging")
    staging = start_frame or action
    rear_view = bool(re.search(r"\b(?:walking|walks|moving|moves|running|runs) away\b|\b(?:rear view|from behind|back to camera)\b", staging, re.I))
    appearance = design(cast)
    if rear_view:
        # Face descriptions can pull a rear-view composition back into a portrait.
        appearance = ". ".join(sentence for sentence in re.split(r"(?<=[.!?])\s+", appearance)
                                if not re.search(r"\b(face|jawline|eyes|nose|mouth)\b", sentence, re.I))
    shared_space = ("One continuous shot in one shared setting: the participants occupy the same space, "
                    "with their positions, gestures and sightlines driven by the opening staging. "
                    "No dividing line, separate portraits or character lineup" if count is None or count > 1 else "")
    return _join("One uninterrupted monochrome pencil storyboard image, a single camera view", cast_limit, shared_space,
                 "Stage this exact opening moment: " + staging,
                 "The scene action for context, not its later outcome: " + action,
                 "Rear view: backs toward camera, faces hidden, moving deeper into the scene" if rear_view else
                 "Preserve the specified viewing angle and eyelines. Show the participants engaged in the action, not lined up for a portrait",
                 "Camera framing: " + framing, MOVE_VIEWPOINT.get(camera_move, ""),
                 "Readable acting poses and separated silhouettes; the characters interact with the scene, not the viewer",
                 lead and cast and "Lead wardrobe and appearance within this crop: " + appearance,
                 roster and "Supporting cast in this panel: " + "; ".join(roster),
                 continuity and "Continuity: " + continuity,
                 "Indicate only the location named in the staging with sparse pencil marks; leave all other space white",
                 "Tight crop: the subject fills the frame and extends beyond its edges; no full body or whole building" if close else
                 "Frame only the area needed for this action; the subjects dominate the composition",
                 cast_limit, shared_space,
                 "All named colours are grey values in this drawing. Black, grey and white only. One panel edge to edge, no lettering, borders or drawing equipment")


SKETCH_NEGATIVE = ("colour, colored, coloured, photograph, 3d render, doll, polished illustration, comic page, "
                   "paper craft, diorama, paper border, multiple panels, split screen, divided frame, diptych, "
                   "character lineup, separate portraits, border, text, caption, watermark, drawing equipment, extra limbs, duplicate people")


def sketch_state_prompt(state: dict, visible_keys: list | None = None) -> str:
    facts = [f"{key.replace(' · ', ' ')} is {value}" for key, value in state.items()
             if visible_keys is None or key in visible_keys]
    return ("Depict these starting conditions: " + "; ".join(facts) +
            ". Illustrate them visually without writing any words into the drawing.") if facts else ""


def sketch_from_frame_prompt() -> str:
    return ("Trace Picture 1 as a rough monochrome graphite storyboard drawing on white paper. "
            "Preserve the exact framing, silhouettes, poses, faces, number of people, object shapes, handles, folds "
            "and physical state. Only change the rendering into black pencil lines and sparse grey shading. "
            "Do not redesign anything or advance the action. Coloured surfaces become grey values; "
            "retain the distinction between an unlit object and emitted light. One panel, no text or border.")


def storyboard_guide(picture: int, lead: bool, look: str = "", others: str = "", world_picture: int | None = 1) -> str:
    """The storyboard owns layout; an optional world image only supplies materials and light."""
    follow = (", where the characters are placed and how they pose" if lead or others else
              " (leave out any character drawn in it)")
    return (f"Picture {picture} is the storyboard drawing of this shot: use its composition, camera angle, framing"
            f"{follow}, but render {MEDIUM_FINISHED[medium(look)]}" +
            (f" using the materials and lighting of Picture {world_picture}" if world_picture else
             " using the specified film look and lighting") + "; nothing pencil-drawn or sketched" +
            (". Rebuild every surface as overlapping flat shapes physically cut from matte coloured cardstock. "
             "Visible scissor-cut edges and tiny shadows between paper layers establish the material. "
             "Faces, hands, clothes and scenery are flat paper shapes with simplified features; replace the "
             "drawing's realistic shading and anatomical modelling with planar paper construction"
             if medium(look) == "papercut" else ""))


def _join(*parts: str) -> str:
    return " ".join(part.strip().rstrip(".") + "." for part in parts if part and part.strip())


def cast_prompt(cast: str, scene: str, look: str) -> str:
    """Character reference portrait for HiDream-O1, reused by every later frame. Drawn in the look's medium, so
    an anime film's lead is an anime character from the start."""
    import re
    if medium(look) == "shadow_puppet":
        return _join("A flat silhouette shadow-puppet cutout character design, not a photograph. The entire subject "
                     "is one flat articulated puppet with a recognizable silhouette and carved ornamental details, "
                     "made in the materials and palette requested for the film. Shown against a luminous screen. "
                     "No realistic skin or three-dimensional person",
                     "Translate this description into silhouette shapes only, never realistic skin or clothing: " + cast,
                     LOOKS.get(look, look), "Flat 2D shadow-puppet cutout in the requested palette and materials, "
                     "no separate cast shadow, no realistic person", "No text")
    backdrop = ("A plain backlit screen behind the single flat puppet, with no separate projected person or figure"
                if medium(look) == "shadow_puppet" else
                "The background is one seamless, plain, light grey colour that fills the whole frame, with no "
                "equipment, props or edges visible. Even, soft, frontal lighting")
    mixed_human = (medium(look) == 'photo' and bool(re.search(r'\bstop[- ]motion\b', look, re.I))
                   and bool(re.search(r'\b(?:human|person|woman|man|adult)\b', cast, re.I))
                   and not re.search(r'\b(?:puppet|doll|figurine|toy|miniature)\b', cast, re.I))
    portrait_look = re.sub(r'\b(?:miniature|stop[- ]motion)\b', '', look, flags=re.I) if mixed_human else look
    return _join("Three-quarter body shot, eye-level, front view. A casting reference image of a single character "
                 "standing alone and facing the camera with a neutral expression", cast,
                 "A real full-sized living human with natural skin, not a toy or figurine" if mixed_human else "",
                 backdrop,
                 MEDIUM_PORTRAIT[medium(look)], LOOKS.get(portrait_look, portrait_look),
                 cartoon_render_direction(portrait_look), "No text")


def legacy_mixed_cast_prompt(cast: str, look: str) -> str | None:
    """Prior portrait direction for mixed live-action/stop-motion projects."""
    import re
    if not re.search(r'\blive[- ]action\b', look or '', re.I) or not re.search(r'\bstop[- ]motion\b', look or '', re.I):
        return None
    text = (look or '').lower()
    if any(x in text for x in ('paper-cut', 'paper cut', 'papercut', 'cut-paper')):
        old_medium = 'papercut'
    elif any(x in text for x in ('claymation', 'plasticine')):
        old_medium = 'clay'
    else:
        old_medium = 'stopmotion'
    return _join("Three-quarter body shot, eye-level, front view. A casting reference image of a single character "
                 "standing alone and facing the camera with a neutral expression", cast,
                 "The background is one seamless, plain, light grey colour that fills the whole frame, with no "
                 "equipment, props or edges visible. Even, soft, frontal lighting",
                 MEDIUM_PORTRAIT[old_medium], LOOKS.get(look, look), cartoon_render_direction(look), "No text")


def anchor_review_question(look: str) -> str:
    """Ask for a conservative check of the visible medium, not creative quality or identity."""
    description = MEDIUM_PORTRAIT[medium(look)]
    return ("Look at the character image. Is its visible medium consistent with this direction: " + description +
            "? Answer YES only if the medium visibly matches, NO only if it clearly conflicts, "
            "or UNCERTAIN if the image or the requested style could reasonably be interpreted either way. "
            "Do not judge the character's name, story or artistic quality. Answer with exactly one word.")


def people_note(lead: bool, others: str = "") -> str:
    """Say who is in frame: unasked-for extra people are the biggest artifact source, and anyone besides the lead
    must not borrow the lead's face."""
    if others:
        count = character_count(lead, others)
        return ((f"Exactly {count} characters in this frame. " if count is not None else "") +
                (f"The cast consists of the lead and {others}. " if lead else f"The cast consists of {others}; the lead is not in this shot. ")
                + "Everyone besides the lead has clearly distinct appearance, markings and clothing. No other characters are in the frame")
    return ("The lead is the only character in the frame" if lead else "There are no characters anywhere in this shot")


def cartoon_render_direction(look: str) -> str:
    """Explicit flat artwork only for a 2D cartoon, never for mixed or other media."""
    import re
    if not re.search(r"\bcartoons?\b", look or "", re.I) or not cartoon_2d_default(look):
        return ""
    return ("Render characters as flat hand-drawn 2D cartoon artwork: clear drawn contours, flat colour fills, "
            "simple cel-shaded shadow shapes and painted shapes for the background. Preserve each character's "
            "species and distinctive markings. Faces and bodies are drawn shapes, not sculpted or airbrushed "
            "volumetric 3D character models; avoid plastic surfaces, realistic fur and rounded CGI faces")


def character_count(lead: bool, others: str) -> int | None:
    """Only count an explicit roster of individuals; crowds and unspecified extras remain unrestricted."""
    import re
    if not others.strip():
        return int(bool(lead))
    entries = [x.strip() for x in others.split(";") if x.strip()]
    if any(not re.match(r"^[\w '’-]+\s*\(", x) for x in entries):
        return None
    counts = [roster_entry_count(*((entry.split("(", 1) + [""])[:2])) for entry in entries]
    return None if any(count is None for count in counts) else int(bool(lead)) + sum(counts)


def roster_entry_count(name: str, description: str = "") -> int | None:
    """Count an individual or an explicitly sized group; unknown groups remain uncountable."""
    import re
    name = name.strip()
    # Only accept cardinal words attached to a group, not a person's name such as "Three".
    match = re.match(r"^(?:a\s+|the\s+)?(pair|couple|twins|trio|quartet|quintet)\s+of\s+\S", name, re.I)
    if match:
        return {"pair": 2, "couple": 2, "twins": 2, "trio": 3, "quartet": 4, "quintet": 5}[match.group(1).lower()]
    match = re.match(r"^(?:the\s+)?(\d+|two|three|four|five|six)\s+(?:people|persons|characters|villagers|patrons|workers|soldiers|guards|figures|children|animals)\b", name, re.I)
    if match:
        value = match.group(1).lower()
        count = int(value) if value.isdigit() else {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6}[value]
        return count if 1 <= count <= 50 else None
    group = r"\b(?:crowds?|groups?|clusters?|teams?|famil(?:y|ies)|twins|trios?|quartets?|quintets?|pairs?|villagers|patrons|workers|soldiers|guards|people|passers-by)\b"
    # A name can itself denote a group; in descriptions, a group must be the described subject,
    # rather than a person who happens to stand near other people.
    if re.search(group, name, re.I) or re.match(r"\s*(?:an?\s+|the\s+)?(?:crowd|group|cluster|team|family|trio|quartet|pair|twins)\b", description, re.I):
        return None
    return 1


CAST_COUNT_CHECK = ("Count every separate visible character in this image, including humans, animals, "
                    "anthropomorphic cartoon animals, quadrupeds, robots, creatures, puppets and dolls. "
                    "A puppet or doll is a separate character even when a human holds or operates it. A cat or other animal "
                    "is one character even if no human is present. Include characters in foreground, background "
                    "and doorways. Count each actual figure once; do not count objects, plants, clothes, props, "
                    "shadows, reflections, pictures or decorative statues as characters. "
                    "Answer with only the total number as digits, and nothing else.")




def world_plate_prompt(scene: str, look: str) -> str:
    """The film's world for HiDream-O1: an empty location plate. Nobody is in it, so no shot inherits a stray face
    from it; the lead and the other characters are added shot by shot."""
    return _join("Wide establishing view of this world, from wherever it looks most striking", scene,
                 "The place is completely deserted and uninhabited: nobody is there, no people, no figures, "
                 "no human silhouettes", LOOKS.get(look, look), MEDIUM_FRAME[medium(look)] + ", no text or lettering")


PEOPLE_CHECK = ("Look carefully at this image. Is there any person, human figure, silhouette, face or body part "
                "anywhere in it, even small or far away? Answer with exactly one word: YES or NO.")


def shot_prompt(action: str, shot_size: str, look: str, continuity: str = "", has_cast: bool = False,
                camera_move: str = "", lead: bool = True, world: str = "", identity: str = "", cast: str = "",
                storyboard: bool = False, others: str = "", line: str = "", start_frame: str = "",
                world_reference: bool = True, world_picture_index: int | None = None,
                cast_uncertain: bool = False) -> str:
    """Storyboard = Picture 1, lead = Picture 2, optional world = last. Without a board the world is first."""
    framing = ", ".join(x for x in (SHOT_SIZES.get(shot_size, shot_size), MOVE_VIEWPOINT.get(camera_move, "")) if x)
    who = ("The lead is the character from Picture 2 with the same species, face, distinctive markings, colouring, build and wardrobe. "
           "Picture 2 is only an identity reference: take their pose, expression and body language from this shot's "
           "action, not from Picture 2, and play it with the emotion the moment calls for. Ignore the studio "
           "backdrop of Picture 2" if has_cast else lead and cast and "The lead: " + cast)
    speaker = line.split(":", 1)[0].strip() if ":" in line else ""
    world_picture = ((world_picture_index or (3 if has_cast else 2)) if storyboard else 1) if world_reference else None
    return _join(
        ("Transform the storyboard in Picture 1 into a finished film frame. Preserve its crop, subject scale, "
         "viewpoint, poses and the number and placement of characters and props. " if storyboard else "") +
        "Create this shot in the specific location described below: " + framing,
        "Visible first frame: " + (start_frame or action),
        world and ((f"Location context from Picture {world_picture}: " if world_picture else "Location context: ")
                   + world + ". Use the location and atmosphere; do not add offscreen characters or actions from this description"),
        (storyboard_guide(1, lead, look, others, world_picture) +
         (f". Picture {world_picture} is only a materials, palette and lighting reference; its wide camera view is not this shot"
          if world_picture else ". Keep the storyboard's camera view, crop and subject placement. Preserve any sketched scenery; "
          "complete a plain or incomplete background using the location context without adding a wide establishing view")) if storyboard else
        ("Choose the camera position this shot needs; do not copy the layout of Picture 1, but keep its era, weather, light and colour"
         if world_picture else "Choose the camera position this shot needs and use the described location and atmosphere"),
        lead and who, ("Follow the opening staging for who is visible; do not invent additional figures"
                       if cast_uncertain else people_note(lead, others)),
        lead and identity and "The lead: " + identity, continuity,
        speaker and f"{'The lead' if speaker.lower() == 'lead' else speaker} is caught mid-sentence, speaking",
        LOOKS.get(look, look) and "Same color grade: " + LOOKS.get(look, look),
        cartoon_render_direction(look),
        MEDIUM_FRAME[medium(look)] + ", no text, no borders")


def motion_prompt(action: str, camera_move: str, sound: str = "", look: str = "", cast: str = "",
                  shot_size: str = "", continuity: str = "", lead: bool = True, others: str = "",
                  line: str = "", start_frame: str = "", end_state: str = "") -> str:
    """LTX 2.5 prompt: action, then the camera move (LTX follows early camera language best), then who, any spoken
    line, look and sound. LTX samples without guidance, so everything it must avoid is said here, not in a
    negative prompt."""
    move = CAMERA_MOVES.get(camera_move, camera_move)
    style = LOOKS.get(look, look)
    speaker, _, words = line.partition(":")
    spoken = words.strip().strip('"').strip() if words else ""
    lead_speaking = speaker.strip().lower() == "lead"
    speaker = (cast or "The lead") if lead_speaking else speaker.strip()
    return _join(action, move, shot_size and "Framing: " + SHOT_SIZES.get(shot_size, shot_size),
                 start_frame and "At the beginning: " + start_frame,
                 end_state and "By the end of this single shot: " + end_state,
                 lead and cast and "The character: " + cast,
                 continuity and "These details stay exactly the same throughout: " + continuity,
                 people_note(lead, others),
                 spoken and (f'The only speaker is {speaker}, saying "{spoken}" clearly. '
                             + ('Their lips move in sync; the other visible characters listen silently.'
                                if not lead_speaking or lead else 'The voice is offscreen; visible characters listen.')),
                 style and "Cinematic style: " + style,
                 cartoon_render_direction(look),
                 ("Flat shadow-puppet silhouettes articulate with small deliberate jointed movements against the backlit screen; keep each figure's cut-out profile and flat materials throughout" if medium(look) == "shadow_puppet" else
                  "Flat cut-paper pieces articulate with small deliberate jointed movements; preserve paper edges and flat faces" if medium(look) == "papercut" else
                  "Natural, physically plausible motion") + ", consistent faces, no cuts, no captions or on-screen text",
                 sound and "Audio: " + sound + ("" if not spoken else ", under the spoken line"))


# ---------------------------------------------------- continuity contracts and visual acceptance
REVIEW_VERSION = 3
REVIEW_PROMPT_VERSION = 3  # invalidate inference caches without invalidating saved/director-approved takes


def json_object(text: str) -> dict:
    """Accept a JSON object, optionally fenced; never treat malformed model output as approval."""
    import json
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def state_map(value) -> dict[str, str]:
    if not isinstance(value, dict) or len(value) > 32:
        raise ValueError("Scene state must be an object with at most 32 named facts")
    if any(not isinstance(k, str) or not k.strip() or len(k) > 100 or
           not isinstance(v, str) or not v.strip() or len(v) > 600 for k, v in value.items()):
        raise ValueError("Each state fact needs a short name and a non-empty description")
    return {k.strip(): v.strip() for k, v in value.items()}


def continuity_brief(context_json: str) -> str:
    return ("You are a script supervisor. Build an explicit state ledger for the supplied film. Return ONLY JSON. "
            "Do not rewrite the script or invent events to conceal a contradiction.\n"
            "Separate permanent DESIGN (shape, size, material, wardrobe) from changing STATE (owner, position, "
            "lit/unlit, intact/broken, open/closed, location). A general design note about glow must NOT override "
            "a beat that explicitly starts with the object unlit.\n"
            "For environment, copy short, exact phrases from the WORLD text describing the location, "
            "architecture, weather, lighting, time and physical surroundings. Include every such detail "
            "that is present, but omit character names, people, actions and story events. Do not paraphrase, "
            "infer or add details: each phrase must occur verbatim in WORLD. If none is usable, return an empty list.\n"
            "DESIGN must preserve the supplied objects' exact materials, colours, shapes and handles, and "
            "fixed set materials. Do not merely repeat the film's rendering style. Character appearance and "
            "wardrobe are already supplied separately for only the people visible in each shot: do not "
            "repeat character names or wardrobe in this shared design string (that can introduce offscreen actors). "
            "For an object described as paper, preserve paper in design; never substitute glass or metal. "
            "A light's colour when lit is a design property; whether it is currently lit belongs in STATE.\n"
            "Use a small set of concrete, human-readable fact names, e.g. 'Parcel · held by', 'Parcel · seal', "
            "'Location'. Values are short phrases. Names and values are open-ended, not a fixed vocabulary. "
            "Track only facts that matter to this story.\n"
            "Prefer 2–5 plot-critical prop facts. Ordinary seating, table labels, character locations, "
            "wardrobe and visible presence belong in staging/cast, not additional state facts. "
            "A cut to another angle is not a change of location.\n"
            "initial is the state BEFORE shot 1. Each shot's changes are applied AFTER its action. "
            "The next shot automatically inherits that result; never reset it. An action's result must not already "
            "exist in its starting state. No unexplained relocation, ownership change or magically repaired object. "
            "Every changes key must exist in initial. Use ONE fact for an object's holder, whose value changes "
            "between people; never create a separate holder fact for each person. Do not introduce new facts "
            "in later shots. Put every tracked fact in initial, even if its starting value is 'none'. "
            "Use 'none' only for explicit physical absence, never as a placeholder for an unexamined starting "
            "condition. Read shot 1's first-frame staging to establish initial values. If that staging does "
            "not establish a necessary value, use 'Unknown before first change' and report the question in issues. "
            "Use readable spaces in fact names, not underscores. checks lists only facts visibly verifiable in that shot; "
            "do not require inspecting an offscreen object or recognizing an exact geographical name. "
            "If visibility changes, use separate start_checks and end_checks. List all visibly present character "
            "names in start_cast and end_cast, using exactly the supplied names (Lead for an unnamed lead). "
            "An entrance changes the roster; an exchange between already visible people does not. "
            "If a roster is uncountable, use null rather than inventing a number.\n"
            "Report story contradictions in issues as short actionable sentences. Do not report issues just "
            "because a camera cuts to a different view of the same place. Include EVERY shot, once, in order.\n"
            'Schema: {"environment":["exact setting phrase from WORLD"], "design":"immutable design only", "initial":{"fact name":"starting value"}, '
            '"shots":[{"index":1,"changes":{"fact name":"new value"},"start_checks":["fact name"],'
            '"end_checks":["fact name"],"start_cast":["name"],"end_cast":["name"]}],"issues":[]}\n'
            "design must be a STRING, not an object. Before returning, check each changes/checks key against "
            "initial and remove redundant facts. Keep the ledger small: usually 2–5 facts. "
            "Track visible cast in the cast arrays, not redundant presence state facts.\n"
            "FILM\n" + context_json)


def cast_roster_conflicts(context: dict, plan: dict) -> list[dict]:
    """Find named cast mentioned in the opening but absent from its roster.

    Mentions alone do not prove visibility. Only a narrow explicit physical
    staging pattern supports correction; ambiguous cases remain unresolved.
    """
    import re
    if not isinstance(context, dict) or not isinstance(plan, dict):
        return []
    names = []
    lead = lead_name(context.get('cast') or '')
    if lead and roster_entry_count(lead, context.get('cast') or '') == 1:
        names.append(lead)
    for line in (context.get('characters') or '').splitlines():
        name, separator, description = line.partition(':')
        if (separator and name.strip() and description.strip() and roster_entry_count(name.strip(), description) == 1
                and name.strip().casefold() not in {entry.casefold() for entry in names}):
            names.append(name.strip())
    shots, rows = context.get('shots'), plan.get('shots')
    if not isinstance(shots, list) or not isinstance(rows, list) or len(shots) != len(rows):
        return []
    conflicts = []
    for index, (shot, row) in enumerate(zip(shots, rows), 1):
        if not isinstance(shot, dict) or not isinstance(row, dict) or not isinstance(row.get('start_cast'), list):
            continue
        staging = shot.get('start_frame') or ''
        if not isinstance(staging, str) or not staging.strip():
            continue
        roster = {name.strip().casefold() for name in row['start_cast'] if isinstance(name, str)}
        # Negative, hypothetical and depicted mentions do not prove presence.
        ambiguous = bool(re.search(r"\b(?:offscreen|off-screen|no|not|never|neither|absent|outside|enters|entering|arrives|"
                                   r"photograph|photo|picture|portrait|painting|drawing|reflection|memory|dream|"
                                   r"imagines|imagined|imaginary|if|unless|later|without)\b|[\"“”]",
                                   staging, re.I))
        for name in names:
            escaped = re.escape(name)
            present = name.casefold() in roster or (lead and name.casefold() == lead.casefold()
                                                     and bool(roster & {'lead', 'the lead'}))
            if present or not re.search(r'(?<!\w)' + escaped + r'(?!\w)', staging, re.I):
                continue
            if (re.search(r'(?<!\w)' + escaped + r"\s+(?:is\s+)?(?:offscreen|off-screen|not visible|absent|outside the frame)\b",
                          staging, re.I)
                    or re.search(r'\bwithout\s+' + escaped + r'(?!\w)', staging, re.I)):
                continue  # Explicitly offscreen, so omission is not a conflict.
            direct = bool(re.search(r'\bwith\s+' + escaped + r'\s+(?:in front of|beside|next to|opposite|at the table)\b',
                                    staging, re.I))
            pair = bool(re.search(r'(?<!\w)' + escaped + r'\s+and\s+[\w -]+\s+(?:stand|sit|face)\b', staging, re.I)
                        or re.search(r'\b[\w -]+\s+and\s+' + escaped + r'\s+(?:stand|sit|face)\b', staging, re.I))
            conflicts.append({'index': index, 'name': name, 'explicit': not ambiguous and (direct or pair)})
    return conflicts


def parse_continuity(text: str, shot_count: int, recover_missing: bool = True) -> dict:
    def normalize_schema(value, fields):
        if not isinstance(value, dict):
            return value
        result = {}
        for key, item in value.items():
            canonical = key.strip().casefold() if isinstance(key, str) else key
            canonical = canonical if canonical in fields else key
            if canonical in result:
                raise ValueError("Continuity plan has duplicate schema keys")
            result[canonical] = item
        return result
    plan = normalize_schema(json_object(text), {'initial', 'design', 'issues', 'shots', 'environment'})
    initial = state_map(plan.get("initial"))
    design = plan.get("design")
    issues = plan.get("issues")
    rows = plan.get("shots")
    if not isinstance(design, str) or not isinstance(issues, list) or any(not isinstance(x, str) for x in issues):
        raise ValueError("Continuity plan is missing design or issues")
    if not isinstance(rows, list) or len(rows) != shot_count:
        raise ValueError("Continuity plan must cover every shot exactly once")
    rows = [normalize_schema(row, {'index', 'changes', 'start_checks', 'end_checks', 'start_cast', 'end_cast'})
            for row in rows]
    # A writer can introduce a new fact in a change even after the repair pass.
    # Preserve the change, but do not invent its preceding value. Surface the
    # missing starting condition as a director decision instead of losing the
    # entire plan to a parser exception.
    issues = list(issues)
    missing = {}
    for index, row in enumerate(rows, 1):
        if isinstance(row, dict):
            for key in state_map(row.get("changes")):
                if key not in initial:
                    missing.setdefault(key, index)
    if missing and not recover_missing:
        raise ValueError("Changes reference facts absent from initial: " + ", ".join(missing))
    if len(initial) + len(missing) > 32:
        raise ValueError("Scene state must contain at most 32 named facts")
    for key, index in missing.items():
        initial[key] = "Unknown before first change"
        issues.append(f"Set the initial value of '{key}' before shot {index}; the writer did not establish it.")
    clean = []
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict) or row.get("index") != index:
            raise ValueError("Continuity shots are out of order")
        changes = state_map(row.get("changes"))
        if changes.keys() - initial.keys():
            raise ValueError("A state change uses a fact absent from the initial state")
        item = {"index": index, "changes": changes}
        for field in ("start_checks", "end_checks"):
            keys = row.get(field)
            # Some writers append a proposed value to a known key. Preserve a usable ledger,
            # but require editorial review instead of silently accepting the inferred mapping.
            if isinstance(keys, list):
                repaired = []
                for key in keys:
                    if not isinstance(key, str):
                        raise ValueError("State checks must be fact names")
                    key = key.strip()  # Match the normalization already applied by state_map.
                    matches = [known for known in initial if isinstance(key, str) and key.startswith(known + " · ")]
                    if key not in initial and len(matches) == 1:
                        issues.append(f"Shot {index}: review {field} for '{matches[0]}'; the writer attached a value instead of a fact name ({key}).")
                        key = matches[0]
                    if key in missing and (index < missing[key] or index == missing[key] and field == "start_checks"):
                        issues.append(f"Shot {index}: '{key}' was removed from {field} because its initial value is unknown; restore the check after setting it if visible.")
                        continue
                    repaired.append(key)
                keys = repaired
            if not isinstance(keys, list) or any(not isinstance(k, str) or k not in initial for k in keys) or len(set(keys)) != len(keys):
                raise ValueError("State checks must name known facts exactly once")
            item[field] = keys
        for field in ("start_cast", "end_cast"):
            names = row.get(field)
            if names is not None:
                if not isinstance(names, list) or any(not isinstance(n, str) or not n.strip() for n in names):
                    raise ValueError("Visible cast must be unique names or null for an uncountable group")
                names = [name.strip() for name in names]
                if len(set(n.casefold() for n in names)) != len(names):
                    raise ValueError("Visible cast must be unique names or null for an uncountable group")
            item[field] = names
        clean.append(item)
    # A visible actor cannot simultaneously have an absent location. Flag the
    # contradiction without guessing where that actor should actually be.
    first = clean[0] if clean else {}
    visible = {name.casefold() for name in (first.get("start_cast") or [])}
    for key in first.get("start_checks", []):
        subject, separator, field = key.partition(" · ")
        if (separator and subject.casefold() in visible and field.casefold() in ("location", "position")
                and initial[key].casefold() in ("none", "unknown", "n/a", "unknown before first change")):
            message = f"Set the initial value of '{key}': this actor is visible in shot 1 but their starting position is unspecified."
            if message not in issues:
                issues.append(message)
    # Optional in model output and historical plans. An invalid environmental
    # extraction should never break continuity planning; Studio verifies each
    # phrase against the actual scene before using it for a world plate.
    environment = plan.get("environment")
    if not isinstance(environment, list) or len(environment) > 20 or any(
            not isinstance(fragment, str) or not fragment.strip() or len(fragment) > 300 for fragment in environment):
        environment = []
    else:
        environment = [fragment.strip() for fragment in environment]
    return {"design": design.strip(), "environment": environment, "initial": initial, "shots": clean, "issues": issues}


def scope_shared_design(design: str, people) -> str:
    """Keep prop/set design separate from clauses describing named cast.

    Only explicit leading cast labels/appearance clauses are removed. Ambiguous
    prose is retained rather than deleting a set or prop that happens to share a
    name. Callers still supply the relevant cast through their dedicated inputs.
    """
    import re
    names = [str(name).strip() for name in people if str(name).strip()]
    if not names:
        return design.strip()
    cast_prefix = re.compile(r"^(?:" + "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True)) +
                             r")(?:\s*:|\s+(?:wears|has|is|looks like)\b)", re.I)
    clauses = re.split(r"(?<=[.!?])\s+|;\s*|\n+", design.strip())
    return " ".join(clause.strip() for clause in clauses if clause.strip() and not cast_prefix.match(clause.strip()))


def state_direction(state: dict, changes: dict | None = None, visible_keys: list | None = None) -> str:
    import json
    if visible_keys is not None:
        state = {k: v for k, v in state.items() if k in visible_keys}
        if changes is not None:
            changes = {k: v for k, v in changes.items() if k in visible_keys}
    return ("AUTHORITATIVE SCENE STATE. These current facts override general mood, glow and continuity "
            "adjectives. Do not depict a later result early. Current state: " + json.dumps(state, ensure_ascii=False) +
            (". Changes performed by this shot, reached only at its end: " + json.dumps(changes, ensure_ascii=False)
             if changes is not None else ". This is a frozen starting moment; no state changes have happened yet."))


def cast_transition_direction(start_cast, end_cast) -> str:
    return (f"Visible people at start: {start_cast}; at end: {end_cast}. "
            "An already visible actor performs the action; do not create a second copy of them. "
            "Every visible figure keeps the same flatness, material, face and wardrobe throughout.")


def visual_review_brief(expected_json: str, look: str, phase: str = "start") -> str:
    return ("Inspect the actual image as a strict visual continuity reviewer. Observe first, then compare. "
            "Do not infer success from the instructions. Do not invent hidden objects or treat the intended "
            "story as visible evidence. Return ONLY JSON, no markdown.\n"
            "Count separate visible characters, including humans, animals, anthropomorphic cartoon animals, "
            "quadrupeds, robots, creatures, puppets and dolls, including small background figures. "
            "A puppet being operated by a human counts separately from that human. Exclude objects, props, "
            "plants, shadows, reflections, pictures and decorative statues. "
            "Use null if the number cannot be determined. For each requested state fact, describe what is "
            "actually visible and assign verdict pass, fail, or uncertain. Missing, hidden or ambiguous evidence "
            "is uncertain, not pass. Include EVERY requested fact exactly once. "
            "Owner means who physically holds the object, not who it belongs to in the story. "
            "An object emitting visible light fails an unlit requirement. "
            "Judge rendering style against the FILM LOOK. In a mixed-media scene, preserve each character's "
            "explicit material: a photographed human and a cloth puppet must not both become puppets. " +
            ("Flat layered paper should have cut edges and flat shapes; smooth rounded CGI or ordinary painted "
             "illustration does not prove paper-cut style. " if medium(look) == "papercut" else "") +
            "Match named characters using the provided appearance descriptions; report clear identity substitutions.\n"
            'Schema: {"count":0,"style":{"verdict":"pass|fail|uncertain","observed":"visible evidence"},'
            '"cast":{"verdict":"pass|fail|uncertain","observed":"visible characters and clothing"},'
            '"state":[{"key":"exact requested fact name","verdict":"pass|fail|uncertain",'
            '"observed":"visible evidence"}]}\n'
            f"Phase: {phase}. Film look: {look}\nRequirements: {expected_json}\n"
            "Copy each state object's KEY exactly into key. Do NOT append ': value' to the key. "
            "For example a requirement {\"Door · position\":\"closed\"} uses key \"Door · position\", "
            "never \"Door · position: closed\". Describe the observed value only in observed.")


def state_evidence_brief(text: str, expected_json: str) -> str:
    import json
    try:
        observed = json_object(text).get("state")
        if isinstance(observed, list):
            observed = {row["key"]: row.get("observed") for row in observed}
        elif isinstance(observed, dict):
            observed = {key: row.get("observed") for key, row in observed.items()}
    except (ValueError, TypeError, KeyError, AttributeError):
        observed = None
    return ("Compare required scene facts with an image observer's descriptions. You do not see the image. "
            "Use ONLY the observations as evidence; never assume the requirement is true. "
            "An observation that contradicts the required value is fail, even if other facts match. "
            "Bind each observation to the object or person it explicitly describes. "
            "Camera orientation and actor-to-actor orientation are different relations: facing away from "
            "the viewer can be correct when facing a person farther into the scene. Do not infer a "
            "contradiction from a camera-relative observation alone. Likewise, standing on a surface "
            "does not contradict being at a location containing that surface. If the relevant relation "
            "was not observed, return uncertain rather than fail. "
            "Names identify subjects by their supplied appearance; names and furniture labels do not need "
            "to be printed in the image. Compare visible relations such as seated beside a window with "
            "the corresponding staging label. Do not fail a match merely because the observation uses "
            "different ordinary words. Missing evidence is uncertain, not a confirmed contradiction. "
            "A required unlit object fails when the observer describes emission from THAT SAME OBJECT. "
            "Emission from a separate nearby object does not contradict an unlit requirement. "
            "An explicit observation that the required object has no flame or internal glow supports unlit, "
            "even if the observer also describes a separate light source. "
            "Empty hands fail if the observer says the person is holding an object. "
            "Missing or ambiguous evidence is uncertain. Return ONLY JSON with every exact requirement key once: "
            '{"state":[{"key":"exact fact name","verdict":"pass|fail|uncertain","reason":"comparison"}]}. '
            'For no required facts return {"state":[]}.\nRequired facts: ' +
            json.dumps(json_object(expected_json).get("state", {}), ensure_ascii=False) +
            "\nVisible character identities (match observed clothes and appearance to these names): " +
            json.dumps(json_object(expected_json).get("people", {}), ensure_ascii=False) +
            "\nObserved facts (no verdicts): " + json.dumps(observed, ensure_ascii=False))


def fact_observation_brief(key: str, expected_json: str | dict | None = None, phase: str = "start") -> str:
    import json
    import re
    expected = json_object(expected_json) if isinstance(expected_json, str) else expected_json or {}
    phase = expected.get('phase', phase)
    people = expected.get("people") or {}
    objects = expected.get("objects") or {}
    subject = key.split(" · ", 1)[0].strip()
    person = next((name for name in people if name.casefold() == subject.casefold()), None)
    if not person:
        # The planner can emit both "Mira · position" and "Mira's position".
        # Match only a direct person-position fact: "Mira's jacket position"
        # is an object fact and must not be treated as the actor's position.
        person = next((name for name in people if re.fullmatch(
            rf"{re.escape(name)}['’]s\s+(?:position|location|place)(?:\s+.*)?", subject, re.IGNORECASE)
            or re.fullmatch(rf"(?:position|location|place)\s+of\s+{re.escape(name)}", subject, re.IGNORECASE)), None)
    holder = any(word in key.lower() for word in ("holder", "held by", "owner"))
    design = key.lower().startswith("design of ")
    position = any(word in key.lower() for word in ("position", "location", "place"))
    illumination = any(word in key.lower() for word in ("light", "lit", "lantern", "lamp", "candle"))
    orientation = key.endswith(' · camera orientation')
    material = key.endswith(' · rendering material')
    if material:
        # Identity cues may themselves name the requested medium. Hide those
        # labels from this observer so a failed puppet/human rendering is not
        # "verified" by repeating the cast description.
        people = {name: re.sub(r'\b(?:(?:real|living|photographed)\s+)?human\b|'
                              r'\b(?:cloth|felt|fabric)\s+puppet\b|\breal person\b',
                              '', description, flags=re.I).strip()
                  for name, description in people.items()}
    # Observers receive identity cues, never the required state value. The
    # independent comparison pass is the only place the target value appears.
    identities = json.dumps({"people": people, "objects": objects}, ensure_ascii=False)
    return ("Inspect the actual image, using these descriptions only to identify subjects: " + identities +
            ". Names are reference labels, not lettering that must appear in the image. "
            "For example, a named character is recognized by their appearance, never by a printed name. "
            f"Frame phase: {phase}. Describe ONLY what is visibly true about this scene fact: " + key +
            ". One or two short factual sentences, no JSON and no pass/fail verdict. "
            + ("Identify this character by their clothes and hair. Is the face visible, in profile, or is the "
               "back of the head visible? Is this character in the near foreground or farther away? "
               "Report each matching figure separately if the character appears more than once. " if orientation else
               "Describe this character's visible surface and construction: skin and hair, cloth and stitching, "
               "clay, painted illustration, or another material. Describe the head, hands and clothing separately; "
               "include visible textile texture. A smooth face alone does not establish the material of the body. "
               "Report what the image shows, not the "
               "material suggested by the identity description. " if material else
               "Identify the person from their appearance. Describe their visible posture and whether they face "
               "another person, and their position relative to visible people, furniture or landmarks. "
               "A table's story label or a geographical name need not be readable. " if person and position else
               "Describe the object's colour, body shape, surface folds or pattern, handle and material. " if design else
               "This asks WHICH PERSON has their hand physically connected to the object's handle, not a stand or fixture. "
               "Describe the holder's clothes and their position in frame. If the object rests on a surface and nobody holds it, say nobody holds it. " if holder else
               "Describe the object's position: is its base resting on a surface, or suspended above it? Name the visible support. " if position else
               "Inspect the specific object named in this fact. Trace any visible emission to its source: "
               "does this object itself contain a visible flame or glow from within? "
               "Describe nearby light sources separately. A separate flame or reflected light does not establish "
               "that this object is lit. Name the object explicitly instead of using an ambiguous 'it'. "
               "Distinguish red or yellow material from emitted light: colour alone is not evidence of illumination. " if illumination else
               "Describe the object's visible physical condition. ") +
            "Do not infer an intended story. "
            "If the relevant subject is hidden or the fact cannot be established, say it is not visible. "
            "Do not interpret a person's name as a month, word, sign or object.")


def parse_visual_review(text: str, expected_json: str, observed_count: str | None = None,
                        state_audit: str | None = None) -> dict:
    """Separate actual visual defects from uncertainty and broken reviewer output."""
    import json
    issues, report = [], None

    def add(category, code, message, severity="warning"):
        issues.append({"category": category, "code": code, "message": message, "severity": severity})

    def verdict(value, code, message, severity="blocking"):
        if value == "fail":
            add("content_issue", code, message, severity)
        elif value == "uncertain":
            add("uncertain", code, message)
        elif value != "pass":
            raise ValueError("Invalid verdict for " + code)

    try:
        expected = json_object(expected_json)
        report = json_object(text)
        count = report.get("count")
        if observed_count is not None:
            import re
            neutral = observed_count.strip().rstrip(".")
            count = int(neutral) if re.fullmatch(r"\d+", neutral) else None
            report["reported_count"], report["count"] = report.get("count"), count
        wanted = expected.get("count")
        allowed = expected.get("allowed_counts", [wanted] if wanted is not None else None)
        if allowed is not None:
            if count is None:
                add("uncertain", "cast_count_unverifiable", f"Visible cast count: expected {allowed}, observed {count}")
            elif type(count) is not int or count < 0:
                raise ValueError("Invalid visible cast count")
            elif count not in allowed:
                add("content_issue", "cast_count_mismatch", f"Visible cast count: expected {allowed}, observed {count}", "blocking")
        for field in ("style", "cast"):
            evidence = report.get(field)
            if not isinstance(evidence, dict) or not isinstance(evidence.get("observed"), str) or not evidence["observed"].strip():
                raise ValueError("Missing " + field + " evidence")
            verdict(evidence.get("verdict"), field + "_mismatch", field + ": " + evidence["observed"],
                    "warning" if field == "style" else "blocking")
        state = report.get("state")
        keys = set(expected.get("state", {}))
        # Accept the equivalent keyed-object representation without inventing evidence.
        if isinstance(state, dict) and all(isinstance(v, dict) for v in state.values()):
            state = [{**value, "key": key} for key, value in state.items()]
            report["state"] = state
        if not isinstance(state, list) or any(not isinstance(row, dict) for row in state):
            raise ValueError("Missing state evidence")
        names = [row.get("key") for row in state]
        if len(names) != len(keys) or set(names) != keys:
            raise ValueError("State evidence does not cover the requested facts exactly once")
        for row in state:
            if not isinstance(row.get("observed"), str) or not row["observed"].strip():
                raise ValueError("Missing observation for " + row["key"])
            if row.get("verdict") == "observed":
                if state_audit is None:
                    add("uncertain", "state_comparison_missing", row["key"] + ": observation has not been compared")
            else:
                verdict(row.get("verdict"), "state_mismatch", row["key"] + ": " + row["observed"])
        if state_audit is not None:
            audit = json_object(state_audit).get("state")
            if not isinstance(audit, list) or any(not isinstance(row, dict) or not isinstance(row.get('key'), str) for row in audit):
                raise ValueError("State comparison does not cover the required facts")
            # Accept only outer whitespace differences; never guess between
            # different fact names or merge colliding audit entries.
            audit = [{**row, 'key': row['key'].strip()} for row in audit]
            audit_names = [row['key'] for row in audit]
            if len(audit_names) != len(keys) or len(set(audit_names)) != len(audit_names) or set(audit_names) != keys:
                raise ValueError("State comparison does not cover the required facts")
            report["state_comparison"] = audit
            for row in audit:
                if not isinstance(row.get("reason"), str) or not row["reason"].strip():
                    raise ValueError("Missing state comparison reason")
                contradiction = any(term in row["reason"].lower() for term in ("contradicts", "a contradiction", "does not match", "fails the"))
                if contradiction and row.get("verdict") == "pass":
                    raise ValueError("State comparison verdict contradicts its reason")
                uncertain_reason = any(term in row['reason'].lower() for term in (
                    'cannot determine', 'cannot be determined', 'cannot confirm', 'insufficient evidence',
                    'not enough evidence', 'does not explicitly confirm or deny'))
                result = row.get('verdict')
                if uncertain_reason and not contradiction and result in ('pass', 'fail'):
                    # Retain the original evidence, but never call explicitly
                    # inconclusive reasoning a verified success or defect.
                    row['interpreted_verdict'] = result = 'uncertain'
                if row['key'] in expected.get('advisory_facts', []) and result == 'fail':
                    # Calibration still confuses felt, painted wood and skin.
                    # A material-only allegation must not spend a repair budget
                    # or replace a useful take; preserve it as an advisory check.
                    row['interpreted_verdict'] = result = 'uncertain'
                verdict(result, "state_mismatch", row["key"] + ": " + row["reason"])
        return review_result(issues, evidence=report)
    except (ValueError, TypeError, KeyError) as error:
        add("reviewer_error", "invalid_review_schema", str(error))
        return review_result(issues, evidence=report, raw=text[:8000],
                             state_audit_raw=state_audit[:8000] if isinstance(state_audit, str) else state_audit)


def review_result(issues: list[dict], **extra) -> dict:
    """Keep the legacy status while exposing a machine-actionable outcome."""
    categories = {issue["category"] for issue in issues}
    outcome = next((value for value in ("reviewer_error", "content_issue", "uncertain") if value in categories), "passed")
    return {"version": REVIEW_VERSION, "status": "passed" if outcome == "passed" else "needs_review",
            "outcome": outcome, "issues": issues, "findings": [issue["message"] for issue in issues], **extra}


def combine_visual_reviews(reports: list[dict]) -> dict:
    issues = []
    if len(reports) != 4:
        issues.append({"category": "reviewer_error", "code": "incomplete_video_review",
                       "message": "All four video samples must be reviewed", "severity": "warning"})
    for index, report in enumerate(reports, 1):
        if not isinstance(report, dict):
            issues.append({"category": "reviewer_error", "code": "invalid_video_sample", "severity": "warning",
                           "message": f"Sample {index}: reviewer returned no structured report", "sample": index})
            continue
        current = report.get("issues") or []
        if not current and (report.get("status") != "passed" or report.get("version") != REVIEW_VERSION):
            current = [{"category": "uncertain", "code": "legacy_or_incomplete_review", "severity": "warning", "message": message}
                       for message in report.get("findings") or ["Sample requires current review"]]
        issues.extend({**issue, "message": f"Sample {index}: {issue['message']}", "sample": index} for issue in current)
    return review_result(issues, samples=reports)


