"""Run a small, isolated two-shot Studio pipeline evaluation on local ComfyUI.

The script writes only to a new or empty output directory and never accesses
Studio's normal projects or job history. It uses the same Studio worker and
model readiness checks as the application. It submits GPU jobs to ComfyUI;
run it only when the shared ComfyUI queue is idle.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
import studio
from setup import Setup


def load_case(path: Path, case_id: str, viewpoint: str | None = None, seed_offset: int = 0) -> dict:
    """Load one independent scripted fixture without creating a project or GPU work."""
    cases = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(cases, list):
        raise ValueError('Evaluation cases must be a list')
    matches = [case for case in cases if isinstance(case, dict) and case.get('id') == case_id]
    if len(matches) != 1:
        raise ValueError('Choose one unique evaluation case ID')
    case = copy.deepcopy(matches[0])
    fields = ('id', 'scene', 'look', 'cast', 'characters')
    if any(not isinstance(case.get(field), str) or not case[field].strip() for field in fields):
        raise ValueError('Evaluation case needs a scene, look and named cast')
    if (not isinstance(case.get('beats'), list) or not all(isinstance(beat, str) and beat.strip() for beat in case['beats'])
            or len(case['beats']) != 2 or not isinstance(case.get('shots'), list) or len(case['shots']) != 2
            or any(not isinstance(shot, dict) or not isinstance(shot.get('seed'), int)
                   or isinstance(shot.get('seed'), bool) for shot in case['shots'])):
        raise ValueError('Evaluation case needs two beats and two seeded shots')
    for shot in case['shots']:
        if (any(not isinstance(shot.get(key), str) or not shot[key].strip()
                for key in ('action', 'start_frame', 'shot_size', 'camera_move'))
                or isinstance(shot.get('seconds'), bool) or not isinstance(shot.get('seconds'), (int, float))
                or not math.isfinite(shot['seconds']) or shot['seconds'] <= 0
                or not 0 <= shot['seed'] < 2**31):
            raise ValueError('Each evaluation shot needs staging, camera, a positive duration and a 31-bit seed')
    if not isinstance(case.get('checks', []), list) or any(not isinstance(check, str) for check in case.get('checks', [])):
        raise ValueError('Evaluation checks must be a list of names')
    if isinstance(seed_offset, bool) or not isinstance(seed_offset, int):
        raise ValueError('Seed offset must be an integer')
    for shot in case['shots']:
        shot['seed'] = (shot['seed'] + seed_offset) % (2**31)
    if viewpoint:
        case['shots'][1]['start_frame'] = viewpoint
    case['fixture_sha256'] = hashlib.sha256(json.dumps(case, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
    return case


def queue_is_idle(url: str) -> bool:
    with urllib.request.urlopen(url.rstrip('/') + '/queue', timeout=5) as response:
        queue = json.load(response)
    return not queue.get('queue_running') and not queue.get('queue_pending')


def studio_is_idle(url: str) -> bool:
    base = url.rstrip('/')
    with urllib.request.urlopen(base + '/api/health', timeout=5) as response:
        if json.load(response).get('service') != 'open-cinema':
            raise RuntimeError('The Studio URL does not identify Open Cinema.')
    with urllib.request.urlopen(base + '/api/jobs', timeout=5) as response:
        jobs = json.load(response)
    return not any(job.get('state') in ('running', 'queued') for job in jobs)


def run(output: Path, comfy_url: str, studio_url: str, mode: str, frame_backend: str, timeout: int,
        viewpoint: str | None = None, case: dict | None = None) -> int:
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('Choose a new or empty output directory; existing files were kept')
    if studio_url and not studio_is_idle(studio_url):
        raise RuntimeError('Studio has active jobs. Wait for them to finish before starting this benchmark.')
    if not queue_is_idle(comfy_url):
        raise RuntimeError('ComfyUI is busy. Wait until its queue is empty before starting this benchmark.')
    output.mkdir(parents=True, exist_ok=True)
    studio.PROJECTS = output.resolve() / 'projects'
    worker = studio.Studio(comfy_url)
    worker.setup = Setup(worker.comfy, preferences_path=output / 'setup-preferences.json')
    shots = [
        {'beat': 1, 'beat_source': 'Mira greets Noah at the bus stop.',
         'action': 'Mira turns to Noah and smiles', 'start_frame': 'Mira and Noah stand together at a bus stop',
         'end_state': 'Mira smiles at Noah', 'lead': True, 'others': 'Noah', 'shot_size': 'Medium',
         'camera_move': 'Static', 'seconds': 3, 'sound': 'Soft wind and distant traffic',
         'line': 'Lead: "You made it."', 'transition': 'cut', 'seed': 1701},
        {'beat': 2, 'beat_source': 'Noah answers from a new angle.',
         'action': 'Noah nods and replies to Mira', 'start_frame': viewpoint or 'Mira and Noah face one another at the same bus stop',
         'end_state': 'Noah smiles at Mira', 'lead': True, 'others': 'Noah', 'shot_size': 'Close-up',
         'camera_move': 'Static', 'seconds': 3, 'sound': 'Soft wind and distant traffic',
         'line': 'Noah: "I did."', 'transition': 'cut', 'frame_source': 'previous_end', 'seed': 1702},
    ]
    if case:
        shots = copy.deepcopy(case['shots'])
    project = worker.create({'title': 'Scratch evaluation', 'scene': case['scene'] if case else 'Two friends wait at a quiet city bus stop at sunrise.',
                             'look': case['look'] if case else 'Warm, hand-drawn 2D animation with clean cel shading', 'aspect': '16:9',
                             'cast': case['cast'] if case else 'Mira, short black hair, brown eyes and a yellow jacket', 'shots': shots,
                             'review_policy': 'draft', 'ai_mode': mode, 'image_backend': 'klein',
                             'frame_backend': frame_backend})
    project['characters'] = case['characters'] if case else 'Noah: curly brown hair, blue jacket and round glasses'
    project['beats'] = list(case['beats']) if case else ['Mira greets Noah at the bus stop.', 'Noah answers from a new angle.']
    if case:
        project['evaluation'] = {'case': case['id'], 'fixture_sha256': case['fixture_sha256'], 'checks': case.get('checks', [])}
    worker.save(project)
    return queue_and_report(worker, project, output, timeout, output / 'report.json')


def queue_and_report(worker, project: dict, output: Path, timeout: int, report_path: Path) -> int:
    source_hashes = {str(path.relative_to(ROOT)).replace('\\', '/'):
                     hashlib.sha256(path.read_bytes()).hexdigest()
                     for directory in (ROOT / 'app', ROOT / 'custom_nodes/comfyui-open-cinema')
                     for path in sorted(directory.glob('*.py'))}
    start = time.monotonic()
    previous_jobs = {job['id'] for job in worker.jobs}
    worker.queue_film(project['id'])
    printed = {}
    while True:
        with worker.lock:
            jobs = [dict(j) for j in worker.jobs if j['project'] == project['id']]
        for job in jobs:
            summary = (job['state'], job['label'], job.get('error'))
            if printed.get(job['id']) != summary:
                print(json.dumps({'elapsed': round(time.monotonic() - start, 2), 'kind': job['kind'],
                                  'state': job['state'], 'label': job['label'], 'error': job.get('error')}), flush=True)
                printed[job['id']] = summary
        if not any(job['state'] in ('running', 'queued') for job in jobs):
            break
        if time.monotonic() - start > timeout:
            print('Timed out while work remains active; the output and job history were preserved.', flush=True)
            return 2
        time.sleep(1)
    project = worker.load(project['id'])
    report = {'mode': project.get('ai_mode'), 'frame_backend': project.get('frame_backend'),
              'source_sha256': source_hashes,
              'source_note': 'Disk sources at launch; does not prove which custom-node version ComfyUI loaded.',
              'evaluation': project.get('evaluation'),
              'second_shot_start_frame': project['shots'][1].get('start_frame'),
              'elapsed_seconds': round(time.monotonic()-start, 2),
              'project_id': project['id'], 'film': project.get('film'),
              'shots': [{'id': s['id'], 'keyframe': s.get('keyframe'), 'video': s.get('video'),
                         'quality': s.get('quality', {})} for s in project['shots']], 'jobs': jobs}
    report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'film': project.get('film'), 'report': str(report_path)}), flush=True)
    new_failures = any(job['id'] not in previous_jobs and job['state'] in ('failed', 'blocked', 'cancelled') for job in jobs)
    complete = project.get('film') and all(s.get('video') for s in project['shots']) and not studio.film_review(project)['stale']
    return 0 if complete and not new_failures else 1


def resume(output: Path, comfy_url: str, studio_url: str, timeout: int) -> int:
    """Resume only a completed scratch evaluation; retain its original report and takes."""
    if not output.is_dir() or not (output / 'report.json').is_file():
        raise ValueError('Resume requires an existing evaluation output with report.json')
    report_path = output / 'report-resumed.json'
    if report_path.exists():
        raise ValueError('This evaluation was already resumed; the previous report was kept')
    original = json.loads((output / 'report.json').read_text(encoding='utf-8'))
    project_id = original.get('project_id')
    if not isinstance(project_id, str) or not project_id.isalnum():
        raise ValueError('The evaluation report has no valid scratch project ID')
    projects = output.resolve() / 'projects'
    if not (projects / project_id / 'project.json').is_file():
        raise ValueError('The scratch project in this evaluation was not found')
    if studio_url and not studio_is_idle(studio_url):
        raise RuntimeError('Studio has active jobs. Wait for them to finish before resuming this benchmark.')
    if not queue_is_idle(comfy_url):
        raise RuntimeError('ComfyUI is busy. Wait until its queue is empty before resuming this benchmark.')
    studio.PROJECTS = projects
    worker = studio.Studio(comfy_url)
    worker.setup = Setup(worker.comfy, preferences_path=output / 'setup-preferences.json')
    return queue_and_report(worker, worker.load(project_id), output, timeout, report_path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--comfy', default='http://127.0.0.1:8288')
    parser.add_argument('--studio', default='http://127.0.0.1:8420',
                        help='Studio URL to check for active jobs; pass an empty string only when Studio is stopped')
    parser.add_argument('--mode', choices=('fast', 'normal'), default='fast')
    parser.add_argument('--frame-backend', choices=('qwen', 'klein'), default='qwen')
    parser.add_argument('--viewpoint', help='Explicit second-shot opening description; report it when comparing runs')
    parser.add_argument('--seed-offset', type=int, default=0, help='Offset both fixture shot seeds for another reproducible sample')
    parser.add_argument('--case', help='Scripted case ID from --cases (defaults to the original bus-stop fixture)')
    parser.add_argument('--cases', type=Path, default=ROOT / 'tests/fixtures/film_pipeline_cases.json')
    parser.add_argument('--resume', action='store_true', help='Resume an existing scratch evaluation, keeping its takes and original report')
    parser.add_argument('--timeout', type=int, default=1800)
    args = parser.parse_args()
    if args.resume:
        raise SystemExit(resume(args.output, args.comfy, args.studio, args.timeout))
    if args.seed_offset and not args.case:
        parser.error('--seed-offset requires --case')
    case = load_case(args.cases, args.case, args.viewpoint, args.seed_offset) if args.case else None
    raise SystemExit(run(args.output, args.comfy, args.studio, args.mode, args.frame_backend, args.timeout, args.viewpoint, case))
