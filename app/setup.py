"""Local readiness checks and explicit, resumable model installation.

The browser can select manifest IDs, never arbitrary URLs or filesystem paths.
Credentials stay in the server's HF_TOKEN environment variable.
"""
from __future__ import annotations

import hashlib
import concurrent.futures
import json
import os
import shutil
import threading
import tempfile
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
WRITING_NODES = {
    'write_story': ('TextGenerate', 'OpenCinemaWriter', 'OpenCinemaStoryBrief', 'OpenCinemaParseStory',
                    'OpenCinemaTitleBrief', 'OpenCinemaSelectTitle', 'PreviewAny'),
    'write_shots': ('TextGenerate', 'OpenCinemaWriter', 'OpenCinemaShotsBrief', 'OpenCinemaParseShots',
                    'OpenCinemaReviewShotsBrief', 'PreviewAny'),
    'write_lead': ('TextGenerate', 'OpenCinemaWriter', 'OpenCinemaLeadBrief', 'OpenCinemaParseLead', 'PreviewAny'),
    'plan_continuity': ('TextGenerate', 'OpenCinemaWriter', 'OpenCinemaContinuityBrief',
                        'OpenCinemaContinuityRepairBrief', 'OpenCinemaParseContinuity', 'OpenCinemaStateLedger', 'PreviewAny'),
}

# One catalog for Studio tasks and ComfyUI's current-workflow inspector.
CAPABILITIES = {
    'writing': ('Story and visual review · Standard', 'Gemma 4 12B writes and checks your film.', ('writer',)),
    'writing_fast': ('Story and visual review · Fast', 'Gemma 4 E4B writes and checks your film.', ('writer_fast',)),
    'hidream': ('HiDream images', 'Portraits, world plates and original storyboard drawings.', ('hidream',)),
    'images_fast': ('FLUX.2 Klein images', 'Portraits, world plates and optional opening-frame editing.', ('klein', 'klein_te', 'klein_vae')),
    'qwen': ('Qwen reference editing', 'Reference-matched frames, repairs, ending frames and storyboard tracing.', ('qwen_edit', 'qwen_te', 'qwen_vae', 'qwen_lightning')),
    'video': ('Video and sound', 'LTX generates motion with synchronized speech and sound.', ('ltx', 'ltx_te', 'ltx_vae', 'ltx_audio_vae')),
    'video_refine': ('Standard video refinement', 'The second video pass used in Standard performance.', ('ltx_upscaler',)),
    'master': ('1080p mastering', 'Optional SeedVR2 finishing for an existing cut.', ('master_11', 'master_12')),
}


def task_capabilities(kind, mode='normal', image_backend='hidream', frame_backend='qwen'):
    if mode not in ('normal', 'fast') or image_backend not in ('hidream', 'klein') or frame_backend not in ('qwen', 'klein'):
        raise ValueError('Choose supported performance and image settings')
    writer = 'writing_fast' if mode == 'fast' else 'writing'
    image = 'images_fast' if image_backend == 'klein' else 'hidream'
    frame = 'images_fast' if frame_backend == 'klein' else 'qwen'
    video = {'video'} | ({'video_refine'} if mode == 'normal' else set())
    if kind in ('stitch', 'review_reel', 'motion_preview'):
        return set()
    if kind == 'master':
        return {'master'}
    if kind in ('film', 'resume_film'):
        return {writer, image, frame, 'qwen'} | video
    if kind == 'video':
        return {writer, image, frame, 'qwen'} | video
    if kind == 'title_video':
        return video
    if kind == 'trailer':
        # score_graph uses the two-pass LTX graph in both film performance modes.
        return {'video', 'video_refine'}
    if kind in ('cast', 'character_reference', 'world'):
        return {writer, image}
    if kind in ('sketch', 'resume_board', 'prop'):
        return {writer, image, 'qwen'}
    if kind == 'keyframe':
        return {writer, image, frame, 'qwen'}
    if kind in ('repair_frame', 'title_frame'):
        return {writer, 'qwen'}
    return {writer}


def dependency_plan(status, kind='film', mode='normal', image_backend='hidream', frame_backend='qwen'):
    capabilities = task_capabilities(kind, mode, image_backend, frame_backend)
    ids = {i for key in capabilities for i in CAPABILITIES[key][2]}
    missing = [m['id'] for m in status['models'] if m['id'] in ids and not m['installed']]
    nodes = set(WRITING_NODES.get(kind, ('TextGenerate', 'OpenCinemaWriter') if capabilities & {'writing', 'writing_fast'} else ()))
    if kind in ('film', 'resume_film', 'video', 'keyframe'):
        nodes.update(name for name in REQUIRED_NODES if name not in
                     ('HiDreamO1PatchSeamSmoothing', 'EmptyHiDreamO1LatentImage', 'LTXVImgToVideoInplace'))
    if 'hidream' in capabilities:
        nodes.update(('HiDreamO1PatchSeamSmoothing', 'EmptyHiDreamO1LatentImage'))
    if 'video' in capabilities:
        nodes.add('LTXVImgToVideoInplace')
    missing_nodes = sorted(nodes - set(status.get('available_nodes', nodes)))
    if 'images_fast' in capabilities:
        missing_nodes += status.get('missing_fast_image_nodes', [])
        if frame_backend == 'klein' and kind in ('film', 'resume_film', 'video', 'keyframe'):
            missing_nodes += status.get('missing_klein_frame_nodes', [])
    ffmpeg = kind in ('film', 'resume_film', 'video', 'title_video', 'trailer', 'master', 'stitch', 'review_reel')
    return {'capabilities': [c for c in CAPABILITIES if c in capabilities], 'model_ids': sorted(ids),
            'missing_ids': missing, 'missing_nodes': sorted(set(missing_nodes)),
            'missing_bytes': sum(m['bytes'] for m in status['models'] if m['id'] in missing),
            'needs_ffmpeg': ffmpeg and not status['ffmpeg'],
            'ready': status['connected'] and not missing and not missing_nodes and (not ffmpeg or status['ffmpeg'])}


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


def reserve_download_space(items: list[dict], root: Path) -> None:
    """Check the combined remaining bytes on each destination filesystem.

    Separate workers share free space, so individually sufficient checks do not
    ensure that a concurrent batch fits. Existing complete files need no extra
    allocation; interrupted partials only need their remaining bytes.
    """
    root = root.resolve()
    volumes = {}
    for item in items:
        target = (root / item['folder'] / item['name']).resolve()
        if root not in target.parents:
            raise ValueError('Model destination is outside the configured folder')
        if target.is_file():
            continue  # install_model validates its checksum before accepting it
        partial = target.with_suffix(target.suffix + '.part')
        offset = partial.stat().st_size if partial.exists() else 0
        if offset > item['bytes']:
            raise ValueError('Partial download exceeds the expected size; inspect the .part file before retrying')
        parent = target.parent
        while not parent.exists():
            if parent.parent == parent:
                raise ValueError('Model download folder has no existing parent')
            parent = parent.parent
        if not parent.is_dir():
            raise ValueError('Model download folder is not a directory')
        device = parent.stat().st_dev
        if device not in volumes:
            volumes[device] = [parent, 0]
        volumes[device][1] += item['bytes'] - offset
    for parent, remaining in volumes.values():
        if shutil.disk_usage(parent).free < remaining + 512 * 1024 * 1024:
            raise ValueError('Insufficient free disk space for the selected model downloads')


def promote_verified_model(partial: Path, target: Path, *, windows: bool | None = None) -> None:
    """Atomically publish verified bytes without replacing a competing file.

    Windows rename refuses to replace an existing destination. On Unix, a
    same-directory hard link creates the target atomically without replacement.
    If the filesystem cannot provide this, preserve the verified partial.
    """
    use_windows = os.name == 'nt' if windows is None else windows
    try:
        if use_windows:
            os.rename(partial, target)
        else:
            os.link(partial, target)
    except FileExistsError:
        raise ValueError('A model appeared during download; it was not overwritten. The verified partial was kept.') from None
    except OSError as error:
        raise RuntimeError('Could not safely publish the verified model without overwriting another file; the partial was kept.') from error
    if not use_windows:
        try:
            partial.unlink()
        except OSError as error:
            raise RuntimeError('The verified model was installed, but its partial file could not be removed.') from error


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
    promote_verified_model(partial, target)
    progress("installed", offset)


class Setup:
    def __init__(self, comfy, model_dir=None, preferences_path=None):
        self.comfy = comfy
        self.model_dir = Path(model_dir).expanduser().resolve() if model_dir else None
        self.explicit_model_dir = bool(model_dir)
        self.preferences_path = Path(preferences_path) if preferences_path else Path(__file__).resolve().parents[1] / 'runtime' / 'setup-preferences.json'
        self.lock = threading.RLock()
        self.jobs = {}
        self.cached = None
        self.checked = 0

    def model_roots(self):
        """Discover roots from the local ComfyUI bridge, never from browser input."""
        parsed = urllib.parse.urlparse(self.comfy.server)
        if parsed.scheme != 'http' or parsed.hostname not in ('localhost', '127.0.0.1', '::1') or parsed.username or parsed.password:
            return []
        try:
            with urllib.request.urlopen(self.comfy.server + '/open-cinema/model-roots', timeout=2) as response:
                values = json.load(response).get('roots', [])
            if not isinstance(values, list):
                return []
            roots = []
            for value in values:
                if not isinstance(value, str):
                    continue
                path = Path(value)
                if not path.is_absolute() or not path.is_dir():
                    continue
                path = path.resolve()
                identifier = hashlib.sha256(os.path.normcase(str(path)).encode('utf-8')).hexdigest()
                if not any(root['id'] == identifier for root in roots):
                    roots.append({'id': identifier, 'path': str(path)})
            return roots
        except (OSError, ValueError, TypeError, AttributeError):
            return []

    def _saved_model_dir(self, roots):
        try:
            data = json.loads(self.preferences_path.read_text(encoding='utf-8'))
            if data.get('comfy_url') != self.comfy.server:
                return None
            return next((Path(root['path']) for root in roots if root['id'] == data.get('root_id')), None)
        except (OSError, ValueError, TypeError, AttributeError):
            return None

    def select_model_root(self, identifier):
        if self.explicit_model_dir:
            raise ValueError('The model folder is controlled by the launcher or environment.')
        with self.lock:
            if any(j['state'] in ('queued', 'downloading', 'verifying') for j in self.jobs.values()):
                raise ValueError('Wait for model installation to finish before changing folders.')
            selected = next((root for root in self.model_roots() if root['id'] == identifier), None)
            if not selected:
                raise ValueError('That folder is no longer available in ComfyUI. Refresh Setup and choose again.')
            self.preferences_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=self.preferences_path.parent, delete=False) as out:
                    temporary = Path(out.name)
                    json.dump({'version': 1, 'comfy_url': self.comfy.server, 'root_id': selected['id']}, out)
                os.replace(temporary, self.preferences_path)
            finally:
                if temporary and temporary.exists():
                    temporary.unlink()
            self.model_dir = Path(selected['path'])
            self.cached = None
        return self.status(refresh=True)

    def require(self, kind, target=None, mode="normal", image_backend="hidream", frame_backend="qwen"):
        status = self.status()
        plan = dependency_plan(status, kind, mode, image_backend, frame_backend)
        if not status['connected']:
            raise RuntimeError('ComfyUI is offline. Open Setup to connect it before generating.')
        if plan['missing_nodes']:
            raise RuntimeError('Required ComfyUI nodes are missing: ' + ', '.join(plan['missing_nodes']) + '. Open Setup.')
        if plan['missing_ids']:
            names = [m['name'] for m in status['models'] if m['id'] in plan['missing_ids']]
            raise RuntimeError('Models are missing: ' + ', '.join(names[:3]) + '. Open Setup to install them.')
        if plan['needs_ffmpeg']:
            raise RuntimeError('FFmpeg and FFprobe are required. Open Setup before rendering.')

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
        missing_writing_nodes = {kind: [name for name in nodes if name not in info] for kind, nodes in WRITING_NODES.items()} if connected else {}
        ffmpeg = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
        fast_image_nodes = ("EmptyFlux2LatentImage", "Flux2Scheduler", "CFGGuider", "SamplerCustomAdvanced", "ConditioningZeroOut")
        missing_fast_image_nodes = [name for name in fast_image_nodes if name not in info] if connected else []
        missing_klein_frame_nodes = [name for name in ('ReferenceLatent', 'VAEEncode', 'ImageScaleToTotalPixels') if name not in info] if connected else []
        roots = self.model_roots() if connected and not self.explicit_model_dir else []
        if not self.explicit_model_dir:
            with self.lock:
                if not any(j['state'] in ('queued', 'downloading', 'verifying') for j in self.jobs.values()):
                    self.model_dir = self._saved_model_dir(roots)
        groups = {g: connected and (not missing_writing_nodes.get('write_story') if g in ('writing','writing_fast') else True)
                  and (g != "images_fast" or not missing_fast_image_nodes)
                  and all(m["installed"] for m in models if m["group"] == g)
                  for g in ("writing", "writing_fast", "images", "images_fast", "video", "master")}
        result = {"connected": connected, "comfy_url": self.comfy.server, "error": error, "models": models,
                  "available_nodes": list(info), "output_nodes": [k for k, v in info.items() if v.get('output_node')], "missing_nodes": missing_nodes, "missing_writing_nodes": missing_writing_nodes, "missing_fast_image_nodes": missing_fast_image_nodes, "missing_klein_frame_nodes": missing_klein_frame_nodes, "ffmpeg": ffmpeg, "groups": groups,
                  "ready": all(groups[g] for g in ("writing", "images", "video")) and ffmpeg,
                  "modes": {mode: {"ready": groups[group],
                             "film_ready": groups[group] and groups["images"] and groups["video"] and ffmpeg}
                            for mode, group in (("normal", "writing"), ("fast", "writing_fast"))},
                  "model_dir": str(self.model_dir) if self.model_dir else None,
                  "model_roots": roots, "model_dir_source": 'explicit' if self.explicit_model_dir else 'selected' if self.model_dir else None,
                  "free_bytes": shutil.disk_usage(self.model_dir if self.model_dir and self.model_dir.exists() else Path.cwd()).free,
                  "downloads": list(self.jobs.values())}
        result['capabilities'] = {key: {'title': value[0], 'description': value[1], 'model_ids': list(value[2])}
                                  for key, value in CAPABILITIES.items()}
        result['plans'] = {f'{mode}:{image}:{frame}': {
            'film': dependency_plan(result, 'film', mode, image, frame),
            'writing': dependency_plan(result, 'write_story', mode, image, frame)}
            for mode in ('normal', 'fast') for image in ('hidream', 'klein') for frame in ('qwen', 'klein')}
        result['ready'] = result['plans']['normal:hidream:qwen']['film']['ready']
        result['modes'] = {mode: {'ready': result['plans'][f'{mode}:hidream:qwen']['writing']['ready'],
                                  'film_ready': result['plans'][f'{mode}:hidream:qwen']['film']['ready']}
                           for mode in ('normal', 'fast')}
        with self.lock:
            self.cached, self.checked = result, time.monotonic()
        return result

    def workflow_plan(self, graph):
        """Inspect loader inputs, including the writer node's implicit model choice."""
        if not isinstance(graph, dict) or len(graph) > 2000:
            raise ValueError('Choose a valid ComfyUI workflow')
        status = self.status()
        if 'output_nodes' in status:
            # Comfy executes only nodes upstream of an output. Spare loaders on
            # the canvas must not become installation requirements.
            reachable, pending = set(), [key for key, node in graph.items()
                if isinstance(node, dict) and node.get('class_type') in status['output_nodes']]
            while pending:
                key = pending.pop()
                if key in reachable or key not in graph:
                    continue
                reachable.add(key)
                inputs = graph[key].get('inputs', {})
                if isinstance(inputs, dict):
                    pending.extend(str(value[0]) for value in inputs.values()
                                   if isinstance(value, list) and len(value) == 2 and isinstance(value[1], int))
            # Unknown nodes may be missing outputs: retain them for diagnosis.
            graph = {key: node for key, node in graph.items() if key in reachable or
                     isinstance(node, dict) and node.get('class_type') not in status['available_nodes']}
        names, nodes = set(), set()
        for node in graph.values():
            if not isinstance(node, dict):
                continue
            kind, inputs = node.get('class_type'), node.get('inputs', {})
            if not isinstance(kind, str) or not isinstance(inputs, dict):
                continue
            nodes.add(kind)
            for field in ('ckpt_name', 'unet_name', 'clip_name', 'vae_name', 'lora_name', 'model_name'):
                if isinstance(inputs.get(field), str) and inputs[field] not in ('', 'None', 'none'):
                    names.add(inputs[field])
            if kind == 'OpenCinemaWriter':
                writer_id = 'writer_fast' if str(inputs.get('mode', '')).lower().startswith('fast') else 'writer'
                names.add(next(m['name'] for m in MANIFEST if m['id'] == writer_id))
        models = [m for m in status['models'] if m['name'] in names]
        missing = [m for m in models if not m['installed']]
        unknown = sorted(names - {m['name'] for m in models})
        absent_nodes = sorted(nodes - set(status.get('available_nodes', [])))
        return {'models': models, 'missing_ids': [m['id'] for m in missing],
                'missing_bytes': sum(m['bytes'] for m in missing), 'missing_nodes': absent_nodes,
                'unmanaged_models': unknown, 'empty': not nodes,
                'ready': bool(nodes) and status['connected'] and not missing and not absent_nodes and not unknown,
                'model_dir': status['model_dir'], 'downloads': status['downloads']}

    def start(self, ids):
        if not isinstance(ids, list) or not ids or any(i not in {m["id"] for m in MANIFEST} for i in ids):
            raise ValueError("Choose models from the setup checklist")
        with self.lock:
            if any(j["state"] in ("queued", "downloading", "verifying") for j in self.jobs.values()):
                raise ValueError("A model installation is already running")
            if not self.explicit_model_dir:
                self.model_dir = self._saved_model_dir(self.model_roots())
            if not self.model_dir:
                raise ValueError("Select a ComfyUI model folder in Setup, or start the studio with --models-dir, to enable downloads.")
            chosen = [m for m in MANIFEST if m["id"] in ids]
            reserve_download_space(chosen, self.model_dir)
            for item in chosen:
                self.jobs[item["id"]] = {"id": item["id"], "name": item["name"], "state": "queued", "done": 0, "total": item["bytes"]}
            threading.Thread(target=self._install, args=(chosen,), daemon=True).start()
        return self.status()

    def _install(self, items):
        def install_one(item):
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
        # Independent files can download concurrently; each maintains its own
        # resumable partial and is verified before promotion.
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(3, len(items))) as pool:
            list(pool.map(install_one, items))
