"""Tiny stdlib client for the ComfyUI HTTP API."""

from __future__ import annotations

import json
import functools
import hashlib
import threading
import time
import urllib.parse
import urllib.request
import uuid
import sys
from pathlib import Path
from typing import Any, Callable

# Optional local dependency; HTTP reconciliation remains available without it.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime" / "python-packages"))
try:
    import websocket
except ImportError:
    websocket = None


class ComfyError(RuntimeError):
    pass


def timed(operation):
    """Accumulate client-side wall time for the current worker job."""
    @functools.wraps(operation)
    def wrapped(self, *args, **kwargs):
        started = time.monotonic()
        try:
            return operation(self, *args, **kwargs)
        finally:
            metrics = getattr(self._timing, "metrics", None)
            if metrics is not None:
                key = operation.__name__ + "_seconds"
                metrics[key] = metrics.get(key, 0.0) + time.monotonic() - started
                count = operation.__name__ + "_calls"
                metrics[count] = metrics.get(count, 0) + 1
    return wrapped


class Comfy:
    def __init__(self, server: str = "http://127.0.0.1:8188"):
        self.server = server.rstrip("/")
        self.client_id = uuid.uuid4().hex
        self._timing = threading.local()
        self._uploads: dict[tuple[str, str], str] = {}
        self._upload_lock = threading.Lock()
        self.on_event = None
        self._event_condition = threading.Condition()
        self._event_revision = 0
        self._ws_started = False
        self._ws_connected = False

    def _listen(self):
        while True:
            try:
                url = self.server.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
                with websocket.create_connection(url + "/ws?clientId=" + self.client_id, timeout=30) as connection:
                    self._ws_connected = True
                    while True:
                        try:
                            raw = connection.recv()
                        except websocket.WebSocketTimeoutException:
                            connection.ping()
                            continue
                        if not raw:
                            break
                        if not isinstance(raw, str):
                            continue  # binary previews are not Studio status events
                        message = json.loads(raw)
                        with self._event_condition:
                            self._event_revision += 1
                            self._event_condition.notify_all()
                        if self.on_event:
                            self.on_event(message)
            except Exception:
                pass  # history is authoritative; retry the event channel independently
            finally:
                self._ws_connected = False
            time.sleep(3)

    def _json(self, path: str, payload: dict[str, Any] | None = None, timeout: float = 60) -> Any:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(self.server + path, data=data,
                                         headers={"Content-Type": "application/json"})
        for attempt in range(3):  # a ComfyUI busy loading weights can miss a connection; try again before failing
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return json.loads(response.read() or b"null")
            except urllib.error.HTTPError as error:
                raise ComfyError(f"{path}: HTTP {error.code}: {error.read().decode('utf-8', 'replace')[:2000]}") from error
            except (urllib.error.URLError, TimeoutError):
                if attempt == 2 or timeout < 10:
                    raise
                time.sleep(3)

    def alive(self) -> bool:
        try:
            self._json("/system_stats", timeout=3)
            return True
        except Exception:
            return False

    @timed
    def upload(self, path: Path, name: str | None = None) -> str:
        """Upload an image to ComfyUI's input folder and return the name to use in LoadImage."""
        boundary = uuid.uuid4().hex
        name = name or path.name
        # Content identity prevents an edited file from reusing an old input.
        # Read once: hashing and multipart construction share the same snapshot.
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        key = (name, digest)
        with self._upload_lock:
            cached = self._uploads.get(key)
        if cached:
            query = urllib.parse.urlencode({"filename": cached.rsplit("/", 1)[-1],
                "subfolder": cached.rsplit("/", 1)[0] if "/" in cached else "", "type": "input"})
            try:
                request = urllib.request.Request(self.server + "/view?" + query, method="HEAD")
                with urllib.request.urlopen(request, timeout=5):
                    metrics = getattr(self._timing, "metrics", None)
                    if metrics is not None:
                        metrics["upload_cache_hits"] = metrics.get("upload_cache_hits", 0) + 1
                    return cached
            except urllib.error.HTTPError as error:
                error.close()
            except (urllib.error.URLError, TimeoutError):
                pass  # deleted inputs, server restarts and unsupported HEAD all re-upload
        name = f"{Path(name).stem}_{digest[:24]}{Path(name).suffix}"
        body = b"".join([
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n".encode(),
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{name}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n".encode(),
            content, f"\r\n--{boundary}--\r\n".encode(),
        ])
        request = urllib.request.Request(self.server + "/upload/image", data=body,
                                         headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read())
        uploaded = f"{result['subfolder']}/{result['name']}" if result.get("subfolder") else result["name"]
        with self._upload_lock:
            if len(self._uploads) >= 512:
                self._uploads.pop(next(iter(self._uploads)))
            self._uploads[key] = uploaded
        return uploaded

    @timed
    def submit(self, graph: dict[str, Any]) -> str:
        if websocket is not None and not self._ws_started:
            self._ws_started = True
            threading.Thread(target=self._listen, daemon=True, name="comfy-events").start()
        result = self._json("/prompt", {"prompt": graph, "client_id": self.client_id})
        if result.get("node_errors"):
            raise ComfyError(f"Graph rejected: {json.dumps(result['node_errors'])[:2000]}")
        if self.on_event:
            self.on_event({"type": "studio_submitted", "data": {"prompt_id": result["prompt_id"]}})
        return result["prompt_id"]

    @timed
    def wait(self, prompt_id: str, timeout: float = 3600,
             on_tick: Callable[[float], None] | None = None) -> dict[str, Any]:
        started = time.monotonic()
        while True:
            with self._event_condition:
                revision = self._event_revision
            history = self._json(f"/history/{prompt_id}")
            record = history.get(prompt_id) if history else None
            if record:
                status = record.get("status", {})
                if status.get("status_str") == "error":
                    detail = [m for m in status.get("messages", []) if m and m[0] == "execution_error"]
                    message = detail[0][1].get("exception_message", "unknown") if detail else "unknown"
                    raise ComfyError(f"ComfyUI execution failed: {message.strip()}")
                if status.get("completed"):
                    return record
            elapsed = time.monotonic() - started
            if elapsed > timeout:
                raise ComfyError(f"Timed out after {timeout:.0f}s waiting for {prompt_id}")
            if on_tick:
                on_tick(elapsed)
            with self._event_condition:
                self._event_condition.wait_for(lambda: self._event_revision != revision,
                                               timeout=5 if self._ws_connected else 1)

    def run(self, graph: dict[str, Any], **kwargs: Any) -> list[dict[str, Any]]:
        """Run a graph and return its saved files as ComfyUI output descriptors."""
        record = self.wait(self.submit(graph), **kwargs)
        files: list[dict[str, Any]] = []
        for output in record.get("outputs", {}).values():
            for key in ("images", "videos", "gifs", "video", "audio"):
                # loaders (e.g. LoadVideo) report their input file as a preview; only saved outputs count
                files.extend(item for item in output.get(key, [])
                             if isinstance(item, dict) and item.get("type", "output") == "output")
        if not files:
            raise ComfyError("Graph finished without saving any file")
        return files

    @timed
    def download(self, descriptor: dict[str, Any], destination: Path) -> Path:
        query = urllib.parse.urlencode({"filename": descriptor["filename"],
                                        "subfolder": descriptor.get("subfolder", ""),
                                        "type": descriptor.get("type", "output")})
        destination.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(f"{self.server}/view?{query}", timeout=300) as response:
            destination.write_bytes(response.read())
        return destination

    def interrupt(self) -> None:
        self._json("/interrupt", {})
