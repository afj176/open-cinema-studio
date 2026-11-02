"""Sample each scratch-film clip at four times for visual continuity review."""
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[1]
folder = root / "projects" / sys.argv[1]
project = json.loads((folder / "project.json").read_text(encoding="utf-8"))
output = root / "runtime" / "staging-qa"
output.mkdir(exist_ok=True)
shots = [s for s in project["shots"] if s.get("video")]
if not shots:
    raise SystemExit("No rendered clips yet")
sheet = Image.new("RGB", (1600, 250 * len(shots)), "#181818")
draw = ImageDraw.Draw(sheet)
metadata = []
for row, shot in enumerate(shots):
    video = folder / shot["video"]
    probe = subprocess.run([shutil.which("ffprobe"), "-v", "error", "-show_entries",
                            "format=duration:stream=codec_type,width,height,r_frame_rate", "-of", "json",
                            str(video)], capture_output=True, text=True, check=True)
    info = json.loads(probe.stdout)
    length = float(info["format"]["duration"])
    metadata.append({"shot": shot["id"], "video": shot["video"], **info})
    for col, fraction in enumerate((0.01, 0.33, 0.66, 0.96)):
        timestamp = length * fraction
        frame = subprocess.run([shutil.which("ffmpeg"), "-loglevel", "error", "-ss", str(timestamp),
                                "-i", str(video), "-frames:v", "1", "-vf", "scale=392:-1",
                                "-f", "image2pipe", "-vcodec", "png", "-"],
                               capture_output=True, check=True)
        image = Image.open(io.BytesIO(frame.stdout)).convert("RGB")
        image.thumbnail((392, 220))
        sheet.paste(image, (col * 400 + 4, row * 250 + 26))
        draw.text((col * 400 + 6, row * 250 + 6), f"Shot {row + 1} / {timestamp:.2f}s", fill="white")
sheet.save(output / "motion-contact.jpg", quality=95)
(output / "motion-metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
print(output / "motion-contact.jpg")
