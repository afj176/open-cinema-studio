"""Prepare evidence for a human review of a completed scratch-film benchmark.

This CPU-only tool reads a pipeline report and its selected project media. It
writes a contact sheet and an unscored review template to a separate, empty
directory; it does not change projects or submit work to ComfyUI. Audio levels
and optional speech recognition are observations, not proof of spoken dialogue.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import re
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))

CHECKS = ('identity', 'style', 'continuity', 'action', 'viewpoint', 'dialogue', 'audio_quality')
FRACTIONS = (0.02, 0.33, 0.66, 0.96)


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def media_file(folder: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        raise ValueError('A project media filename is invalid')
    folder = folder.resolve()
    path = (folder / name).resolve()
    if not path.is_relative_to(folder) or not path.is_file():
        raise ValueError('A selected media file is missing or outside its scratch project')
    return path


def load_evaluation(report_path: Path) -> tuple[dict, dict, Path]:
    report_path = report_path.resolve()
    report = json.loads(report_path.read_text(encoding='utf-8'))
    project_id = report.get('project_id')
    if not isinstance(project_id, str) or not project_id.isalnum():
        raise ValueError('The report has no valid scratch project ID')
    projects = (report_path.parent / 'projects').resolve()
    if not projects.is_relative_to(report_path.parent):
        raise ValueError('The scratch projects folder is outside the evaluation')
    folder = (projects / project_id).resolve()
    if not folder.is_relative_to(projects):
        raise ValueError('The scratch project is outside the evaluation')
    project = json.loads((folder / 'project.json').read_text(encoding='utf-8'))
    shots = project.get('shots')
    reported = report.get('shots')
    if project.get('id') != project_id or not isinstance(shots, list) or not isinstance(reported, list) or len(shots) != len(reported):
        raise ValueError('The report and scratch project do not match')
    for shot, snapshot in zip(shots, reported):
        if any(shot.get(key) != snapshot.get(key) for key in ('id', 'keyframe', 'video')):
            raise ValueError('Selected takes changed after this report; inspect the matching latest report')
    if report.get('film') != project.get('film'):
        raise ValueError('The selected film changed after this report; inspect the matching latest report')
    return report, project, folder


def probe(path: Path, ffprobe: str) -> dict:
    result = subprocess.run([ffprobe, '-v', 'error', '-show_entries',
                             'format=duration:stream=codec_type,codec_name,width,height,r_frame_rate,duration',
                             '-of', 'json', str(path)], capture_output=True, text=True, check=True, timeout=30)
    info = json.loads(result.stdout)
    seconds = float(info['format']['duration'])
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError('A selected clip has no positive playable duration')
    return {'duration_seconds': seconds, 'streams': info.get('streams', [])}


def sample_times(metadata: dict) -> list[float]:
    """Stay at or before the last frame even when audio outlasts video."""
    video = next((stream for stream in metadata['streams'] if stream.get('codec_type') == 'video'), {})
    duration = metadata['duration_seconds']
    try:
        stream_duration = float(video.get('duration', duration))
        if math.isfinite(stream_duration) and stream_duration > 0:
            duration = min(duration, stream_duration)
    except (TypeError, ValueError):
        pass
    try:
        fps = float(Fraction(video.get('r_frame_rate', '0/1')))
        frame_duration = 1 / fps if math.isfinite(fps) and fps > 0 else 0.1
    except (TypeError, ValueError, ZeroDivisionError):
        frame_duration = 0.1
    latest = max(0.0, duration - frame_duration)
    return [round(min(duration * fraction, latest), 4) for fraction in FRACTIONS]


def mean_audio_db(path: Path, ffmpeg: str) -> float | None:
    result = subprocess.run([ffmpeg, '-nostdin', '-hide_banner', '-i', str(path), '-vn',
                             '-af', 'volumedetect', '-f', 'null', '-'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=120, check=True)
    match = re.search(r'mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB', result.stderr)
    return float(match.group(1)) if match else None


def inspect(report_path: Path, output: Path, speech_enabled: bool = False) -> dict:
    report, project, folder = load_evaluation(report_path)
    output = output.resolve()
    if output == folder or output.is_relative_to(folder):
        raise ValueError('Choose an output outside the scratch project folder')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('Choose a new or empty output folder; existing files were kept')
    ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        raise RuntimeError('FFmpeg and FFprobe are required to inspect film samples')
    from PIL import Image, ImageDraw
    if speech_enabled:
        import speech
    shots = project['shots']
    media = [media_file(folder, shot['video']) for shot in shots if shot.get('video')]
    if len(media) != len(shots) or not media:
        raise ValueError('Every shot needs a selected playable clip before inspection')
    output.mkdir(parents=True, exist_ok=True)
    width, cell_height, heading = 320, 205, 24
    sheet = Image.new('RGB', (width * len(FRACTIONS), cell_height * len(shots)), '#181818')
    draw = ImageDraw.Draw(sheet)
    records = []
    for row, (shot, path) in enumerate(zip(shots, media)):
        meta = probe(path, ffprobe)
        audio = any(stream.get('codec_type') == 'audio' for stream in meta['streams'])
        line = shot.get('line', '')
        speech_result = speech.check(path, line) if speech_enabled and line.strip() else None
        timestamps = sample_times(meta)
        for col, timestamp in enumerate(timestamps):
            frame = subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-ss', str(timestamp), '-i', str(path),
                                    '-frames:v', '1', '-vf', f'scale={width}:{cell_height - heading}:force_original_aspect_ratio=decrease',
                                    '-f', 'image2pipe', '-vcodec', 'png', '-'],
                                   capture_output=True, check=True, timeout=30)
            with Image.open(io.BytesIO(frame.stdout)) as image:
                image = image.convert('RGB')
                image.thumbnail((width, cell_height - heading))
                sheet.paste(image, (col * width + (width - image.width) // 2, row * cell_height + heading))
            draw.text((col * width + 5, row * cell_height + 4), f'Shot {row + 1} / {timestamp:.2f}s', fill='white')
        records.append({'shot': shot['id'], 'clip': path.name, 'clip_sha256': file_hash(path),
                        'scripted_action': shot.get('action', ''), 'opening_direction': shot.get('start_frame', ''),
                        'scripted_dialogue': line, 'audio_stream': audio,
                        'mean_audio_db': mean_audio_db(path, ffmpeg) if audio else None,
                        'speech_observation': speech_result, 'sample_times_seconds': timestamps, **meta})
    result = {'case': (project.get('evaluation') or {}).get('case'),
              'fixture_sha256': (project.get('evaluation') or {}).get('fixture_sha256'),
              'project_sha256': file_hash(folder / 'project.json'), 'source_report_sha256': file_hash(report_path),
              'film': project.get('film'), 'shots': records,
              'manual_review': {key: {'status': 'not_assessed', 'evidence': ''} for key in CHECKS},
              'guidance': ['Watch each full clip and its cut; contact-sheet frames are only samples.',
                           'Compare visible cast and defining features across shots; note extra or missing people.',
                           'Check the requested camera viewpoint and whether the scripted action actually occurs.',
                           'Listen for the scripted words, correct speaker, delivery and lip synchronization.',
                           'Audio levels do not establish speech; recognition can miss or invent words.']}
    if project.get('film'):
        film = media_file(folder, project['film'])
        result['film_sha256'] = file_hash(film)
        result['film_probe'] = probe(film, ffprobe)
    sheet.save(output / 'contact-sheet.png')
    (output / 'inspection.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path, help='Scratch evaluation report.json or report-resumed.json')
    parser.add_argument('--output', type=Path, required=True, help='New or empty output folder outside the project')
    parser.add_argument('--speech', action='store_true', help='Use the explicitly configured local speech checker, if available')
    args = parser.parse_args()
    result = inspect(args.report, args.output, args.speech)
    print(json.dumps({'case': result['case'], 'shots': len(result['shots']), 'output': str(args.output)}, ensure_ascii=False))
