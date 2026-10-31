"""Open Cinema Studio web server.

    python app/server.py --comfy http://127.0.0.1:8188 --port 8420
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import re
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from studio import PROJECTS, Studio, default_credits, default_trailer, director, graphs  # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
MAX_UPLOAD = 40 * 1024 * 1024


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
        data = path.read_bytes()
        size, start, end = len(data), 0, len(data) - 1
        match = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if match and (match.group(1) or match.group(2)):  # video scrubbing
            if match.group(1):
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else size - 1
            else:
                start = size - int(match.group(2))
            return self._send(206, data[start:end + 1], content_type,
                              {"Content-Range": f"bytes {start}-{end}/{size}", "Accept-Ranges": "bytes"})
        self._send(200, data, content_type, {"Accept-Ranges": "bytes"})

    def do_GET(self):
        try:
            route = urlparse(self.path).path
            if route == "/" or route == "/index.html":
                return self._file(STATIC / "index.html")
            if route.startswith("/static/"):
                target = (STATIC / unquote(route[len("/static/"):])).resolve()
                if STATIC.resolve() not in target.parents:
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
                                   "looks": list(director.LOOKS), "aspects": list(graphs.ASPECTS),
                                   "palettes": director.LOOK_PALETTES,
                                   "comfy": self.studio.comfy.alive()})
            if route == "/api/projects":
                return self._json(self.studio.list_projects())
            if m := re.fullmatch(r"/api/projects/(\w+)", route):
                project = self.studio.load(m.group(1))
                project["motion_defaults"] = {"credits": default_credits(project), "trailer": default_trailer(project),
                                              "material": director.TITLE_MATERIALS.get(project["look"], "")}
                return self._json(project)
            if route == "/api/jobs":
                return self._json(self.studio.list_jobs())
            return self._json({"error": "not found"}, 404)
        except FileNotFoundError:
            self._json({"error": "not found"}, 404)
        except Exception as error:
            self._json({"error": str(error)}, 500)

    def do_POST(self):
        try:
            route = urlparse(self.path).path
            studio = self.studio
            if route == "/api/projects":
                return self._json(studio.create(json.loads(self._body() or b"{}")))
            if m := re.fullmatch(r"/api/projects/(\w+)", route):
                return self._json(studio.update(m.group(1), json.loads(self._body() or b"{}")))
            if m := re.fullmatch(r"/api/projects/(\w+)/reference", route):
                name = unquote(self.headers.get("X-Filename", "reference.png"))
                return self._json(studio.set_reference(m.group(1), name, self._body()))
            if m := re.fullmatch(r"/api/projects/(\w+)/shots/(\w+)/keyframe-upload", route):
                name = unquote(self.headers.get("X-Filename", "keyframe.png"))
                return self._json(studio.set_keyframe(m.group(1), m.group(2), name, self._body()))
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
            if m := re.fullmatch(r"/api/projects/(\w+)/cast", route):
                return self._json(studio.enqueue("cast", m.group(1), None, "Casting"))
            if m := re.fullmatch(r"/api/projects/(\w+)/title-shot", route):
                options = json.loads(self._body() or b"{}")
                return self._json(studio.queue_title_shot(m.group(1), frame=options.get("frame", True)))
            if m := re.fullmatch(r"/api/projects/(\w+)/title-shot/take", route):
                choice = json.loads(self._body() or b"{}")
                return self._json(studio.choose_title_take(m.group(1), choice["kind"], choice["name"]))
            if m := re.fullmatch(r"/api/projects/(\w+)/trailer", route):
                return self._json(studio.enqueue("trailer", m.group(1), None, "Trailer"))
            if m := re.fullmatch(r"/api/projects/(\w+)/motion-preview", route):
                return self._json(studio.enqueue("motion_preview", m.group(1), None, "Title preview"))
            if m := re.fullmatch(r"/api/projects/(\w+)/master", route):
                return self._json(studio.enqueue("master", m.group(1), None, "1080p master"))
            if m := re.fullmatch(r"/api/projects/(\w+)/stitch", route):
                return self._json(studio.enqueue("stitch", m.group(1), None, "Final cut"))
            if route == "/api/cancel":
                studio.cancel()
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
    args = parser.parse_args()
    Handler.studio = Studio(args.comfy)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}"
    print(f"Open Cinema Studio on {url}  (ComfyUI: {args.comfy}, reachable={Handler.studio.comfy.alive()})", flush=True)
    if args.open:
        webbrowser.open(url)
    server.serve_forever()


if __name__ == "__main__":
    main()
