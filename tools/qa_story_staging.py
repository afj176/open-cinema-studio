"""Scratch-only live acceptance helpers; never rewrites a source film."""
import json
import os
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def api(path, data=None):
    request = urllib.request.Request(os.environ.get('OPEN_CINEMA_URL', 'http://127.0.0.1:8420').rstrip('/') + "/api/" + path,
                                    data=json.dumps(data).encode() if data is not None else None,
                                    headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def create(source_id):
    source = api("projects/" + source_id)
    film = api("projects", {"title": "Scratch - Paper-cut staging acceptance v2",
                           **{k: source[k] for k in ("scene", "look", "cast", "continuity", "aspect")}})
    folder = ROOT / "projects" / film["id"]
    # Reuse the same reference material so the comparison isolates staging, not a recast.
    for filename in (source["reference"], source["world"]["plate"]):
        shutil.copy2(ROOT / "projects" / source_id / filename, folder / filename)
    film.update({k: source[k] for k in ("reference", "world", "lead_identity", "lead_identity_of")})
    film.update(auto_render=False, beats=source["beats"], characters=source["characters"], logline=source["logline"])
    # Generated media is server-owned; seed the new scratch fixture before any browser has opened it.
    (folder / "project.json").write_text(json.dumps(film, indent=2), encoding="utf-8")
    (ROOT / "runtime" / "staging-project.txt").write_text(film["id"])
    print(film["id"])
    print(api(f"projects/{film['id']}/write-shots", {"mode": "board", "count": len(film["beats"])}))


if __name__ == "__main__":
    create(sys.argv[1])
