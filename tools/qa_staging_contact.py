"""Contact sheet and pixel measurements for a scratch film; no media is modified."""
import json
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageChops

root = Path(__file__).resolve().parents[1]
project_id = sys.argv[1]
folder = root / "projects" / project_id
project = json.loads((folder / "project.json").read_text(encoding='utf-8'))
output = root / "runtime" / "staging-qa"
output.mkdir(exist_ok=True)
shots = project["shots"]
sheet = Image.new("RGB", (480 * len(shots), 600), "#181818")
draw = ImageDraw.Draw(sheet)
stats = []
for i, shot in enumerate(shots):
    for row, kind in enumerate(("sketch", "keyframe")):
        name = shot.get(kind)
        draw.text((i * 480 + 8, row * 300 + 8), f'{i + 1} {kind} - {shot["shot_size"]}', fill="white")
        if not name:
            continue
        image = Image.open(folder / name).convert("RGB")
        if kind == "sketch":
            r, g, b = image.split()
            delta = max(ImageChops.difference(r, g).getextrema()[1], ImageChops.difference(g, b).getextrema()[1])
            stats.append({"shot": i + 1, "file": name, "max_channel_difference": delta})
        image.thumbnail((472, 266))
        sheet.paste(image, (i * 480 + 4, row * 300 + 30))
sheet.save(output / "staging-contact.jpg", quality=94)
(output / "monochrome.json").write_text(json.dumps(stats, indent=2))
print(json.dumps(stats))
print(output / "staging-contact.jpg")
