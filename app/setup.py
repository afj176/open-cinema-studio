"""Local readiness checks and explicit, resumable model installation.

The browser can select manifest IDs, never arbitrary URLs or filesystem paths.
Credentials stay in the server's HF_TOKEN environment variable.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

MANIFEST = json.loads(Path(__file__).with_name("model_manifest.json").read_text())
LOADERS = {"checkpoints": ("CheckpointLoaderSimple", "ckpt_name"),
           "diffusion_models": ("UNETLoader", "unet_name"), "text_encoders": ("CLIPLoader", "clip_name"),
           "vae": ("VAELoader", "vae_name"), "loras": ("LoraLoaderModelOnly", "lora_name"),
           "latent_upscale_models": ("LatentUpscaleModelLoader", "model_name")}
REQUIRED_NODES = ("TextGenerate", "OpenCinemaShot", "OpenCinemaContinuityRepairBrief", "OpenCinemaSelectTitle",
                  "OpenCinemaWriter", "OpenCinemaCastReview",
                  "OpenCinemaFactBrief", "OpenCinemaAppendObservation", "OpenCinemaReviewRequirements", "OpenCinemaFrameRepairBrief",
                  "OpenCinemaStateEvidenceBrief", "OpenCinemaReviewSamples", "HiDreamO1PatchSeamSmoothing",
                  "EmptyHiDreamO1LatentImage", "LTXVImgToVideoInplace")


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


class PublisherRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected and urllib.parse.urlparse(req.full_url).netloc != urllib.parse.urlparse(newurl).netloc:
            redirected.remove_header("Authorization")
        return redirected


def publisher_open(request, **kwargs):
    return urllib.request.build_opener(PublisherRedirect()).open(request, **kwargs)


def install_model(item: dict, root: Path, progress, token: str = "", opener=publisher_open):
    root = root.resolve()
    target = (root / item["folder"] / item["name"]).resolve()
    if root not in target.parents:
        raise ValueError("Model destination is outside the configured folder")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        progress("verifying", target.stat().st_size)
        if target.stat().st_size == item["bytes"] and digest(target) == item["sha256"]:
            return
        raise ValueError("Existing model differs from the verified release. Move it aside before installing; it was not overwritten.")
    partial = target.with_suffix(target.suffix + ".part")
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > item["bytes"]:
        raise ValueError("Partial download exceeds the expected size; inspect the .part file before retrying")
    if shutil.disk_usage(target.parent).free < item["bytes"] - offset + 512 * 1024 * 1024:
        raise ValueError("Insufficient free disk space for this model")
    if offset < item["bytes"]:
        url = item.get("url") or f"https://huggingface.co/{item['repo']}/resolve/main/{item['path']}"
        headers = {"User-Agent": "OpenCinemaStudio/1.0"}
        if token:
            headers["Authorization"] = "Bearer " + token
        if offset:
            headers["Range"] = f"bytes={offset}-"
        try:
            response = opener(urllib.request.Request(url, headers=headers), timeout=60)
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                raise RuntimeError("Access required: visit the model publisher, accept its conditions yourself, then start the studio with HF_TOKEN set and retry.") from None
            raise RuntimeError(f"Model download returned HTTP {error.code}; retry to resume.") from None
        with response:
            if offset and response.status == 206:
                if not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
                    raise ValueError("Download server returned an unexpected byte range")
            elif response.status == 200:
                offset = 0  # server ignored Range: safely restart the partial file
            else:
                raise ValueError("Unexpected download response")
            with partial.open("ab" if offset else "wb") as stream:
                while block := response.read(4 * 1024 * 1024):
                    if offset + len(block) > item["bytes"]:
                        raise ValueError("Download exceeds the verified model size")
                    stream.write(block)
                    offset += len(block)
                    progress("downloading", offset)
    progress("verifying", offset)
    if offset != item["bytes"] or digest(partial) != item["sha256"]:
        raise ValueError("Model size or SHA-256 check failed. The partial file was kept for inspection; no model was installed.")
    partial.replace(target)
    progress("installed", offset)


class Setup:
    def __init__(self, comfy, model_dir=None):
        self.comfy = comfy
        self.model_dir = Path(model_dir).expanduser().resolve() if model_dir else None
        self.lock = threading.RLock()
        self.jobs = {}
        self.cached = None
        self.checked = 0

    def require(self, kind, target=None, mode="normal"):
        if mode not in ("normal", "fast"):
            raise ValueError("Choose Normal or Fast AI mode")
        groups = ("writing", "images", "video") if kind in ("film", "video") or kind == "write_story" and target == "everything" else \
                 ("writing", "images") if kind in ("cast", "world", "sketch", "keyframe", "prop", "repair_frame") else \
                 ("master",) if kind == "master" else ("writing",)
        groups = tuple("writing_fast" if group == "writing" and mode == "fast" else group for group in groups)
        status = self.status()
        if not status["connected"]:
            raise RuntimeError("ComfyUI is offline. Open Setup to connect it before generating.")
        if status["missing_nodes"]:
            raise RuntimeError("Required ComfyUI nodes are missing. Open Setup for installation instructions.")
        missing = [m["name"] for m in status["models"] if m["group"] in groups and not m["installed"]]
        if missing:
            raise RuntimeError("Models are missing: " + ", ".join(missing[:3]) + ". Open Setup to install them.")
        if kind in ("film", "video", "stitch", "master", "trailer") and not status["ffmpeg"]:
            raise RuntimeError("FFmpeg and FFprobe are required. Open Setup before rendering.")

    def status(self, refresh=False):
        with self.lock:
            if not refresh and self.cached and time.monotonic() - self.checked < 15:
                return {**self.cached, "downloads": list(self.jobs.values())}
        try:
            with urllib.request.urlopen(self.comfy.server + "/object_info", timeout=5) as response:
                info = json.load(response)
            connected, error = True, None
        except Exception:
            info, connected, error = {}, False, "Start ComfyUI at the configured address, then check again."
        models = []
        for item in MANIFEST:
            loader, field = LOADERS[item["folder"]]
            spec = info.get(loader, {}).get("input", {}).get("required", {}).get(field, [[]])
            choices = spec[0] if isinstance(spec[0], list) else spec[1].get("options", []) if len(spec) > 1 else []
            models.append({**item, "installed": item["name"] in choices,
                           "source": f"https://huggingface.co/{item['repo']}/blob/main/{item['path']}"})
        missing_nodes = [name for name in REQUIRED_NODES if name not in info] if connected else []
        ffmpeg = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
        groups = {g: connected and not missing_nodes and all(m["installed"] for m in models if m["group"] == g)
                  for g in ("writing", "writing_fast", "images", "video", "master")}
        result = {"connected": connected, "comfy_url": self.comfy.server, "error": error, "models": models,
                  "missing_nodes": missing_nodes, "ffmpeg": ffmpeg, "groups": groups,
                  "ready": all(groups[g] for g in ("writing", "images", "video")) and ffmpeg,
                  "modes": {mode: {"ready": groups[group],
                             "film_ready": groups[group] and groups["images"] and groups["video"] and ffmpeg}
                            for mode, group in (("normal", "writing"), ("fast", "writing_fast"))},
                  "model_dir": str(self.model_dir) if self.model_dir else None,
                  "free_bytes": shutil.disk_usage(self.model_dir if self.model_dir and self.model_dir.exists() else Path.cwd()).free,
                  "downloads": list(self.jobs.values())}
        with self.lock:
            self.cached, self.checked = result, time.monotonic()
        return result

    def start(self, ids):
        if not self.model_dir:
            raise ValueError("Start the studio with --models-dir pointing at your ComfyUI models folder to enable downloads.")
        if not isinstance(ids, list) or not ids or any(i not in {m["id"] for m in MANIFEST} for i in ids):
            raise ValueError("Choose models from the setup checklist")
        with self.lock:
            if any(j["state"] in ("queued", "downloading", "verifying") for j in self.jobs.values()):
                raise ValueError("A model installation is already running")
            chosen = [m for m in MANIFEST if m["id"] in ids]
            for item in chosen:
                self.jobs[item["id"]] = {"id": item["id"], "name": item["name"], "state": "queued", "done": 0, "total": item["bytes"]}
            threading.Thread(target=self._install, args=(chosen,), daemon=True).start()
        return self.status()

    def _install(self, items):
        for item in items:
            job = self.jobs[item["id"]]
            def progress(state, done):
                with self.lock:
                    job.update(state=state, done=done)
            try:
                install_model(item, self.model_dir, progress, os.environ.get("HF_TOKEN", ""))
                progress("installed", item["bytes"])
            except Exception as error:
                with self.lock:
                    job.update(state="failed", error=str(error))
            with self.lock:
                self.checked = 0
