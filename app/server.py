"""Open Cinema Studio web server.

    python app/server.py --comfy http://127.0.0.1:8188 --port 8420
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import socket
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from studio import PROJECTS, Studio, default_credits, default_trailer, director, film_inputs, graphs  # noqa: E402
from setup import Setup  # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
MAX_UPLOAD = 40 * 1024 * 1024


class StudioHTTPServer(ThreadingHTTPServer):
    """Reserve the Studio port exclusively, including across Windows processes."""

    def __init__(self, *args, **kwargs):
        # On Windows SO_REUSEADDR permits another process to bind the same TCP
        # address, so the launcher and Comfy companion could both appear healthy
        # while serving separate job queues. Unix reuse is useful for restarts.
        self.allow_reuse_address = os.name != "nt"
        super().__init__(*args, **kwargs)

    def server_bind(self):
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Handler(BaseHTTPRequestHandler):
    studio: Studio

    def log_message(self, format, *args):  # keep the console for pipeline output
        pass

    def _send(self, status: int, body: bytes, content_type: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload, status: int = 200) -> None:
        self._send(status, json.dumps(payload).encode("utf-8"), "application/json")

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_UPLOAD:
            raise ValueError("upload too large")
        return self.rfile.read(length)

    def _file(self, path: Path) -> None:
        if not path.is_file():
            return self._json({"error": "not found"}, 404)
        size = path.stat().st_size
        start, end = 0, size - 1
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if match and (match.group(1) or match.group(2)):  # video scrubbing
            if match.group(1):
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else size - 1
            else:
                start = max(0, size - int(match.group(2)))
            end = min(end, size - 1)
            if start > end or start >= size:
                return self._send(416, b"", content_type, {"Content-Range": f"bytes */{size}"})
        partial = bool(match and (match.group(1) or match.group(2)))
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(max(0, end - start + 1)))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        try:
            with path.open("rb") as source:
                source.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    block = source.read(min(256 * 1024, remaining))
                    if not block:
                        break
                    self.wfile.write(block)
                    remaining -= len(block)
        except (BrokenPipeError, ConnectionResetError):
            pass  # seeking or navigating away cancels the previous stream

    def do_GET(self):
        try:
            route = urlparse(self.path).path
            if route == "/api/health":
                return self._json({"service": "open-cinema", "comfy_url": self.studio.comfy.server,
                                   "events": self.studio.comfy.event_status(),
                                   "model_dir": str(self.studio.setup.model_dir) if self.studio.setup.model_dir else None})
            if route == "/comfy":
                self.send_response(302)
                self.send_header("Location", self.studio.comfy.server + "/")
                self.end_headers()
                return
            if route == "/api/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()
                revision = -1  # every connection reconciles a fresh snapshot
                try:
                    while True:
                        current = self.studio.events.wait(revision)
                        payload = f"id: {current}\ndata: {{}}\n\n" if current != revision else ": heartbeat\n\n"
                        self.wfile.write(payload.encode())
                        self.wfile.flush()
                        revision = current
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
                    return
            if route == "/" or route == "/index.html":
                return self._file(STATIC / "index.html")
            if route.startswith("/static/"):
                target = (STATIC / unquote(route[len("/static/"):])).resolve()
                if STATIC.resolve() not in target.parents:
                    return self._json({"error": "forbidden"}, 403)
                return self._file(target)
            if route.startswith("/fonts/"):  # the node pack's open-licensed fonts, shared with the UI
                fonts = Path(__file__).resolve().parents[1] / "custom_nodes" / "comfyui-open-cinema" / "fonts"
                target = (fonts / unquote(route[len("/fonts/"):])).resolve()
                if target.parent != fonts.resolve() or target.suffix != ".ttf":
                    return self._json({"error": "forbidden"}, 403)
                return self._file(target)
            if route.startswith("/media/"):
                project_id, _, name = unquote(route[len("/media/"):]).partition("/")
                target = (PROJECTS / project_id / name).resolve()
                if (PROJECTS / project_id).resolve() != target.parent:
                    return self._json({"error": "forbidden"}, 403)
                return self._file(target)
            if route == "/api/presets":
                return self._json({"camera_moves": list(director.CAMERA_MOVES), "shot_sizes": list(director.SHOT_SIZES),
                                   "looks": list(director.LOOKS), "look_descriptions": director.LOOKS, "aspects": list(graphs.ASPECTS),
                                   "palettes": director.LOOK_PALETTES,
                                   "score_styles": director.SCORE_STYLES, "materials": director.TITLE_MATERIALS,
                                   "comfy": self.studio.comfy.alive()})
            if route == "/api/projects":
                return self._json(self.studio.list_projects())
            if m := re.fullmatch(r"/api/projects/(\w+)", route):
                project = self.studio.load(m.group(1))
                project["film_now"] = film_inputs(project)
                project["motion_defaults"] = {"credits": default_credits(project), "trailer": default_trailer(project),
                                              "material": director.TITLE_MATERIALS.get(project["look"], "")}
                return self._json(project)
            if route == "/api/jobs":
                return self._json(self.studio.list_jobs())
            if route == "/api/setup":
                return self._json(self.studio.setup.status(refresh="refresh=1" in self.path))
            return self._json({"error": "not found"}, 404)
        except FileNotFoundError:
            self._json({"error": "not found"}, 404)
        except Exception as error:
            self._json({"error": str(error)}, 500)

    def do_POST(self):
        try:
            route = urlparse(self.path).path
            studio = self.studio
            if route == "/api/setup/workflow":
                return self._json(studio.setup.workflow_plan(json.loads(self._body() or b"{}").get('graph')))
            if route == "/api/setup/download":
                return self._json(studio.setup.start(json.loads(self._body()).get("ids")))
            if route == "/api/setup/model-root":
                return self._json(studio.setup.select_model_root(json.loads(self._body() or b"{}").get("id")))
            if route == "/api/projects":
                return self._json(studio.create(json.loads(self._body() or b"{}")))
            if m := re.fullmatch(r"/api/projects/(\w+)", route):
                return self._json(studio.update(m.group(1), json.loads(self._body() or b"{}")))
            if m := re.fullmatch(r"/api/projects/(\w+)/reference", route):
                name = unquote(self.headers.get("X-Filename", "reference.png"))
                return self._json(studio.set_reference(m.group(1), name, self._body()))
            if m := re.fullmatch(r"/api/projects/(\w+)/characters/reference", route):
                data = json.loads(self._body() or b"{}")
                return self._json(studio.queue_character_reference(m.group(1), str(data.get('name', ''))))
            if m := re.fullmatch(r"/api/projects/(\w+)/characters/reference-upload", route):
                character = unquote(self.headers.get('X-Character', ''))
                filename = unquote(self.headers.get('X-Filename', 'reference.png'))
                return self._json(studio.set_character_reference(m.group(1), character, filename, self._body()))
            if m := re.fullmatch(r"/api/jobs/(\w+)/retry", route):
                return self._json(studio.retry_job(m.group(1)))
            if m := re.fullmatch(r"/api/jobs/(\w+)/auto-fix", route):
                data = json.loads(self._body() or b"{}")
                if not isinstance(data.get("continuity_rev"), int):
                    return self._json({"error": "Reload the continuity plan before fixing it"}, 400)
                return self._json(studio.auto_fix_continuity(m.group(1), data["continuity_rev"]))
            if m := re.fullmatch(r"/api/projects/(\w+)/memory/approve", route):
                data = json.loads(self._body() or b"{}")
                return self._json(studio.approve_memory_plate(m.group(1), data.get('name', '')))
            if m := re.fullmatch(r"/api/projects/(\w+)/plan-continuity", route):
                return self._json(studio.enqueue("plan_continuity", m.group(1), label="Planning continuity"))
            if m := re.fullmatch(r"/api/projects/(\w+)/props/(\w+)/generate", route):
                data = json.loads(self._body() or b"{}")
                return self._json(studio.enqueue("prop", m.group(1), label="Drawing prop reference", prop=m.group(2), value=data.get("value", "")))
            if m := re.fullmatch(r"/api/projects/(\w+)/shots/(\w+)/review", route):
                return self._json(studio.enqueue("review", m.group(1), m.group(2), "Reviewing video continuity"))
            if m := re.fullmatch(r"/api/projects/(\w+)/shots/(\w+)/repair-frame", route):
                data = json.loads(self._body() or b"{}")
                return self._json(studio.enqueue("repair_frame", m.group(1), m.group(2), "Repairing frame", candidate_kind=data.get("kind", "keyframe")))
            if m := re.fullmatch(r"/api/projects/(\w+)/shots/(\w+)/accept-review", route):
                data = json.loads(self._body() or b"{}")
                return self._json(studio.accept_review(m.group(1), m.group(2), data.get("kind", ""),
                                                     data.get("name", ""), data.get("reason", "")))
            if m := re.fullmatch(r"/api/projects/(\w+)/shots/(\w+)/keyframe-upload", route):
                name = unquote(self.headers.get("X-Filename", "keyframe.png"))
                return self._json(studio.set_keyframe(m.group(1), m.group(2), name, self._body()))
            if m := re.fullmatch(r"/api/projects/(\w+)/shots/(\w+)/endframe-upload", route):
                name = unquote(self.headers.get("X-Filename", "ending.png"))
                return self._json(studio.set_endframe(m.group(1), m.group(2), name, self._body()))
            if m := re.fullmatch(r"/api/projects/(\w+)/shots/(\w+)/take", route):
                choice = json.loads(self._body() or b"{}")
                return self._json(studio.choose_take(m.group(1), m.group(2), choice["kind"], choice["name"]))
            if m := re.fullmatch(r"/api/projects/(\w+)/shots/(\w+)/(keyframe|video)", route):
                project = studio.load(m.group(1))
                index = next(i for i, s in enumerate(project["shots"]) if s["id"] == m.group(2))
                label = ("Keyframe " if m.group(3) == "keyframe" else "Shot ") + str(index + 1)
                return self._json(studio.enqueue(m.group(3), m.group(1), m.group(2), label))
            if m := re.fullmatch(r"/api/projects/(\w+)/render", route):
                options = json.loads(self._body() or b"{}")
                return self._json(studio.queue_film(m.group(1), bool(options.get("redo"))))
            if m := re.fullmatch(r"/api/projects/(\w+)/review-reel", route):
                return self._json(studio.enqueue('review_reel', m.group(1), label='Building review reel'))
            if m := re.fullmatch(r"/api/projects/(\w+)/cast", route):
                return self._json(studio.enqueue("cast", m.group(1), None, "Casting"))
            if m := re.fullmatch(r"/api/projects/(\w+)/write-lead", route):
                mode = json.loads(self._body() or b"{}").get("mode", "write")
                if mode not in director.LEAD_MODES:
                    return self._json({"error": f"unknown mode {mode}"}, 400)
                label = {"write": "Writing the lead", "refine": "Refining the lead", "from photo": "Describing the cast photo",
                         "continuity": "Writing continuity notes"}[mode]
                return self._json(studio.enqueue("write_lead", m.group(1), None, label, mode=mode))
            if m := re.fullmatch(r"/api/projects/(\w+)/undo-(?:lead|story)", route):
                return self._json(studio.undo_story(m.group(1)))
            if m := re.fullmatch(r"/api/projects/(\w+)/world", route):
                return self._json(studio.enqueue("world", m.group(1), None, "Painting the world"))
            if m := re.fullmatch(r"/api/projects/(\w+)/world/take", route):
                name = json.loads(self._body() or b"{}").get("name", "")
                return self._json(studio.choose_world(m.group(1), name))
            if m := re.fullmatch(r"/api/projects/(\w+)/describe-lead", route):
                return self._json(studio.enqueue("describe_lead", m.group(1), None, "Describing the lead's face"))
            if m := re.fullmatch(r"/api/projects/(\w+)/waveform", route):
                return self._json(studio.waveform(m.group(1)))
            if m := re.fullmatch(r"/api/projects/(\w+)/delete", route):
                try:
                    return self._json(studio.delete(m.group(1)))
                except RuntimeError as error:
                    return self._json({"error": str(error)}, 409)
            if m := re.fullmatch(r"/api/projects/(\w+)/write-shots", route):
                options = json.loads(self._body() or b"{}")
                mode = options.get("mode", "board")
                if mode not in director.SHOT_MODES:
                    return self._json({"error": f"unknown mode {mode}"}, 400)
                project = studio.load(m.group(1))
                shot = options.get("shot")
                number = next((i + 1 for i, s in enumerate(project["shots"]) if s["id"] == shot), 0)
                label = {"board": "Writing the shots", "next": "Writing the next shot",
                         "rewrite": f"Rewriting shot {number}", "beat": f"Adding shot {number} to the story"}[mode]
                return self._json(studio.enqueue("write_shots", m.group(1), shot if mode in ("rewrite", "beat") else None, label,
                                                 mode=mode, count=max(2, min(8, int(options.get("count", 5))))))
            if m := re.fullmatch(r"/api/projects/(\w+)/shots/(\w+)/(pause|resume)", route):
                return self._json(studio.pause_shot(m.group(1), m.group(2), m.group(3) == "pause"))
            if m := re.fullmatch(r"/api/projects/(\w+)/shots/(\w+)/sketch", route):
                return self._json(studio.queue_sketches(m.group(1), [m.group(2)], redraw=True))
            if m := re.fullmatch(r"/api/projects/(\w+)/storyboard", route):
                return self._json(studio.queue_sketches(m.group(1)))
            if m := re.fullmatch(r"/api/projects/(\w+)/undo-shots", route):
                return self._json(studio.undo_shots(m.group(1)))
            if m := re.fullmatch(r"/api/projects/(\w+)/write-story", route):
                options = json.loads(self._body() or b"{}")
                target, count = options.get("target", "everything"), max(1, min(8, int(options.get("count", 3))))
                if target not in director.STORY_TARGETS:
                    return self._json({"error": f"unknown target {target}"}, 400)
                label = {"everything": "Writing the whole story", "title": "Writing a title",
                         "logline": "Writing a logline", "world": "Writing the world",
                         "look": "Choosing look & colours", "trailer": "Writing trailer cards",
                         "beats": "Writing the story beats",
                         "more beats": f"Adding {count} beat{'s' if count > 1 else ''} to the story",
                         "characters": "Writing the other characters"}[target]
                return self._json(studio.enqueue("write_story", m.group(1), None, label, target=target, count=count))
            if m := re.fullmatch(r"/api/projects/(\w+)/title-shot", route):
                options = json.loads(self._body() or b"{}")
                return self._json(studio.queue_title_shot(m.group(1), frame=options.get("frame", True)))
            if m := re.fullmatch(r"/api/projects/(\w+)/title-shot/take", route):
                choice = json.loads(self._body() or b"{}")
                return self._json(studio.choose_title_take(m.group(1), choice["kind"], choice["name"]))
            if m := re.fullmatch(r"/api/projects/(\w+)/trailer", route):
                options = json.loads(self._body() or b"{}")
                job = studio.enqueue("trailer", m.group(1), None, "Trailer · new score" if options.get("reroll")
                                     else "Trailer", reroll=bool(options.get("reroll")))
                return self._json(job)
            if m := re.fullmatch(r"/api/projects/(\w+)/motion-preview", route):
                return self._json(studio.enqueue("motion_preview", m.group(1), None, "Title preview"))
            if m := re.fullmatch(r"/api/projects/(\w+)/master", route):
                return self._json(studio.enqueue("master", m.group(1), None, "1080p master"))
            if m := re.fullmatch(r"/api/projects/(\w+)/stitch", route):
                waiting = next((j for j in studio.list_jobs(m.group(1)) if j["kind"] == "stitch"
                                and j["state"] == "queued"), None)  # one cut in the queue is enough
                return self._json(waiting or studio.enqueue("stitch", m.group(1), None, "Final cut"))
            if route == "/api/cancel":
                data = json.loads(self._body() or b"{}")
                studio.load(data["project"])
                studio.cancel(data["project"])
                return self._json({"ok": True})
            return self._json({"error": "not found"}, 404)
        except Exception as error:
            self._json({"error": str(error)}, 400)


def main() -> None:
    parser = argparse.ArgumentParser(description="Open Cinema Studio")
    parser.add_argument("--comfy", default="http://127.0.0.1:8188", help="ComfyUI server URL")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8420)
    parser.add_argument("--open", action="store_true", help="open the studio in a browser")
    parser.add_argument("--models-dir", default=os.environ.get("OPEN_CINEMA_MODELS_DIR"),
                        help="Local ComfyUI models folder; enables explicit downloads from Setup")
    args = parser.parse_args()
    # Reserve the port before creating workers or touching job history.
    server = StudioHTTPServer((args.host, args.port), Handler)
    Handler.studio = Studio(args.comfy)
    Handler.studio.setup = Setup(Handler.studio.comfy, args.models_dir)
    url = f"http://{args.host}:{args.port}"
    print(f"Open Cinema Studio on {url}  (ComfyUI: {args.comfy}, reachable={Handler.studio.comfy.alive()})", flush=True)
    if args.open:
        webbrowser.open(url)
    server.serve_forever()


if __name__ == "__main__":
    main()
