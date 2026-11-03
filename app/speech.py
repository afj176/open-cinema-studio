"""Optional offline speech comparison for generated shots.

This is a rough transcript comparison, not voice identification or a lip-sync check.
The model is loaded only when an explicit local directory is configured.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import os
import re
import shutil
import subprocess
import threading
from difflib import SequenceMatcher
from pathlib import Path

_lock = threading.Lock()
_models = {}


class AudioDecodeUnavailable(RuntimeError):
    pass


def _ffmpeg_audio(path: Path):
    """Decode a short clip to faster-whisper's 16 kHz mono float format."""
    import numpy as np  # installed with faster-whisper, not a Studio dependency
    binary = shutil.which('ffmpeg')
    if not binary:
        raise AudioDecodeUnavailable('FFmpeg is unavailable')
    # Limit output defensively without silently evaluating a truncated line.
    max_seconds = 600
    try:
        result = subprocess.run([binary, '-nostdin', '-v', 'error', '-i', str(path),
                                 '-t', str(max_seconds + 1), '-vn', '-ac', '1', '-ar', '16000',
                                 '-f', 's16le', 'pipe:1'], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=120, check=True)
    except (OSError, subprocess.SubprocessError) as error:
        raise AudioDecodeUnavailable('FFmpeg could not decode the shot') from error
    if not result.stdout or len(result.stdout) % 2 or len(result.stdout) > max_seconds * 16000 * 2:
        raise AudioDecodeUnavailable('The shot audio is empty or too long')
    return np.frombuffer(result.stdout, dtype='<i2').astype(np.float32) / 32768.0


def _recognized_words(model, path: Path) -> list[str]:
    def transcribe(source):
        segments, _ = model.transcribe(source, beam_size=5, vad_filter=False,
                                       condition_on_previous_text=False)
        return _words(' '.join(segment.text for segment in segments))
    try:
        return transcribe(str(path))
    except TypeError as error:
        # PyAV 19 removed a keyword still used by some faster-whisper versions.
        # Do not downgrade PyAV in a ComfyUI environment that may require it.
        if 'metadata_errors' not in str(error) or 'unexpected keyword' not in str(error):
            raise
        return transcribe(_ffmpeg_audio(path))


def _words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+(?:['’][^\W_]+)*", text.casefold(), re.UNICODE)


def line_fingerprint(line: str) -> str:
    return hashlib.sha256(line.encode('utf-8')).hexdigest()


def _model_key(path: Path) -> tuple:
    files = []
    for name in ('model.bin', 'tokenizer.json', 'vocabulary.json', 'vocabulary.txt', 'config.json', 'preprocessor_config.json'):
        file = path / name
        if file.is_file():
            stat = file.stat()
            files.append((name, stat.st_size, stat.st_mtime_ns))
    versions = []
    for name in ('faster-whisper', 'av', 'ctranslate2'):
        try:
            versions.append((name, importlib.metadata.version(name)))
        except importlib.metadata.PackageNotFoundError:
            versions.append((name, 'not installed'))
    return str(path.resolve()), tuple(versions), tuple(files)


def _model(path: Path, key: tuple):
    with _lock:
        if key not in _models:
            from faster_whisper import WhisperModel
            # A local path and local_files_only prohibit implicit downloads.
            model = WhisperModel(str(path), device='cpu', compute_type='int8', local_files_only=True)
            _models.clear()
            _models[key] = model
        return _models[key]


def check(path: Path, line: str, previous: dict | None = None) -> dict:
    """Compare recognized words to the scripted line. Results never approve a take."""
    name = path.name
    fingerprint = line_fingerprint(line)
    result = {'name': name, 'line_hash': fingerprint, 'script_line': line}
    spoken = line.partition(':')[2].strip().strip('"“” ')
    expected = _words(spoken)
    if not expected:
        return {**result, 'status': 'inconclusive', 'message': 'No spoken words could be identified in the scripted line.'}
    setting = os.environ.get('OPEN_CINEMA_WHISPER_MODEL', '').strip()
    if not setting:
        return {**result, 'status': 'unavailable', 'message': 'Automatic speech checking is not configured. Listen to the shot to check its dialogue.'}
    model_path = Path(setting).expanduser()
    # faster-whisper falls back to a network tokenizer if this file is absent.
    if not model_path.is_dir() or not all((model_path / filename).is_file() for filename in ('model.bin', 'tokenizer.json')):
        return {**result, 'status': 'unavailable', 'message': 'The configured local speech model is unavailable. Listen to the shot to check its dialogue.'}
    try:
        key = _model_key(model_path)
        model_hash = hashlib.sha256(repr(key).encode()).hexdigest()
        digest = hashlib.sha256()
        with path.open('rb') as file:
            for block in iter(lambda: file.read(1024 * 1024), b''):
                digest.update(block)
        media_hash = digest.hexdigest()
        if (previous and previous.get('name') == name and previous.get('line_hash') == fingerprint
                and previous.get('media_hash') == media_hash and previous.get('model_hash') == model_hash
                and previous.get('status') in ('possible_match', 'needs_attention')):
            return dict(previous)
        heard = _recognized_words(_model(model_path, key), path)
    except ModuleNotFoundError:
        return {**result, 'status': 'unavailable', 'message': 'The speech checker or a dependency is missing from the Python environment running Studio. See Optional local dialogue check in the README, then listen to the shot.'}
    except AudioDecodeUnavailable:
        return {**result, 'status': 'unavailable', 'message': 'Speech audio could not be decoded. Check that FFmpeg is installed and available to Studio, then listen to the shot.'}
    except TypeError as error:
        if 'metadata_errors' in str(error) and 'unexpected keyword' in str(error):
            return {**result, 'status': 'unavailable', 'message': 'The installed speech checker and audio decoder are incompatible. Install the versions in Optional local dialogue check in the README, restart Studio, and listen to the shot.'}
        return {**result, 'status': 'unavailable', 'message': 'The local speech check could not run. Listen to the shot to check its dialogue.'}
    except Exception:
        # Avoid leaking local paths or transcription content into logs or the UI.
        return {**result, 'status': 'unavailable', 'message': 'The local speech check could not run. Listen to the shot to check its dialogue.'}
    matches = sum(block.size for block in SequenceMatcher(None, expected, heard, autojunk=False).get_matching_blocks())
    coverage = matches / len(expected)
    if coverage >= 0.8:
        status = 'possible_match'
        message = 'The transcript appears to include the scripted words. Listen to check delivery, speaker, and lip sync.'
    else:
        status = 'needs_attention'
        message = 'The transcript did not reliably match the scripted words. Listen to the shot; speech recognition can be wrong.'
    return {**result, 'status': status, 'message': message, 'media_hash': media_hash, 'model_hash': model_hash}
