"""Tiny stdlib client for the ComfyUI HTTP API."""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable


class ComfyError(RuntimeError):
    pass


class Comfy:
    def __init__(self, server: str = "http://127.0.0.1:8188"):
        self.server = server.rstrip("/")
        self.client_id = uuid.uuid4().hex

    def _json(self, path: str, payload: dict[str, Any] | None = None, timeout: float = 60) -> Any:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(self.server + path, data=data,
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read() or b"null")
        except urllib.error.HTTPError as error:
            raise ComfyError(f"{path}: HTTP {error.code}: {error.read().decode('utf-8', 'replace')[:2000]}") from error

    def alive(self) -> bool:
        try:
            self._json("/system_stats", timeout=3)
            return True
        except Exception:
            return False

    def upload(self, path: Path, name: str | None = None) -> str:
        """Upload an image to ComfyUI's input folder and return the name to use in LoadImage."""
        boundary = uuid.uuid4().hex
        name = name or path.name
        body = b"".join([
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n".encode(),
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{name}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n".encode(),
            path.read_bytes(), f"\r\n--{boundary}--\r\n".encode(),
        ])
        request = urllib.request.Request(self.server + "/upload/image", data=body,
                                         headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read())
        return f"{result['subfolder']}/{result['name']}" if result.get("subfolder") else result["name"]

    def submit(self, graph: dict[str, Any]) -> str:
        result = self._json("/prompt", {"prompt": graph, "client_id": self.client_id})
        if result.get("node_errors"):
            raise ComfyError(f"Graph rejected: {json.dumps(result['node_errors'])[:2000]}")
        return result["prompt_id"]

    def wait(self, prompt_id: str, timeout: float = 3600,
             on_tick: Callable[[float], None] | None = None) -> dict[str, Any]:
        started = time.monotonic()
        while True:
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
            time.sleep(1.0)

    def run(self, graph: dict[str, Any], **kwargs: Any) -> list[dict[str, Any]]:
        """Run a graph and return its saved files as ComfyUI output descriptors."""
        record = self.wait(self.submit(graph), **kwargs)
        files: list[dict[str, Any]] = []
        for output in record.get("outputs", {}).values():
            for key in ("images", "videos", "gifs", "video"):
                # loaders (e.g. LoadVideo) report their input file as a preview; only saved outputs count
                files.extend(item for item in output.get(key, [])
                             if isinstance(item, dict) and item.get("type", "output") == "output")
        if not files:
            raise ComfyError("Graph finished without saving any file")
        return files

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
