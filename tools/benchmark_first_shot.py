"""Measure first-playable scheduling on a copied, already-planned first shot.

This opt-in benchmark creates a scratch project in an empty output directory.
Run one process per variant. It never modifies the source film. The world-first
variant simulates the old ordering using current code; it is not an old build.
Both Studio and ComfyUI must be idle before starting shared GPU work.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import time
import uuid
from pathlib import Path

from benchmark_film_pipeline import queue_is_idle, studio_is_idle
from compare_frame_editors import local_image
import studio
from setup import Setup

ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = ('app/studio.py', 'app/graphs.py', 'app/comfy.py', 'custom_nodes/comfyui-open-cinema/director.py')


def source_fingerprint() -> str:
    digest = hashlib.sha256()
    for name in SOURCE_FILES:
        digest.update(name.encode('utf-8'))
        digest.update(hashlib.sha256((ROOT / name).read_bytes()).digest())
    return digest.hexdigest()


def prepare(source: dict, mode: str, seed: int, world_seed: int) -> tuple[dict, list[str]]:
    """Build a fresh single-shot draft using the source's cast and planned state."""
    project = copy.deepcopy(source)
    shots = project.get('shots')
    if not isinstance(shots, list) or not shots or not isinstance(shots[0], dict):
        raise ValueError('Source film needs a first shot')
    shot = shots[0]
    if shot.get('shot_size') in studio.director.WIDE_SIZES or shot.get('frame_source') == 'previous_end':
        raise ValueError('Choose a non-wide first shot that does not use a previous frame')
    if not isinstance(project.get('continuity_plan'), dict) or not studio.plan_usable(project):
        raise ValueError('Source film needs a usable continuity plan')
    if project.get('cast', '').strip() and (not project.get('reference') or studio.cast_stale(project)
                                             or not studio.lead_identity(project)):
        raise ValueError('Source film needs a current lead portrait and description')
    for key in ('sketch', 'keyframe', 'video', 'endframe'):
        shot[key] = None
    for key in ('quality', 'frame_repairs', 'sketches'):
        shot.pop(key, None)
    shot['takes'] = {'keyframe': [], 'video': []}
    shot['seed'] = seed
    project['shots'] = [shot]
    project.update(id=uuid.uuid4().hex[:10], created=time.time(), review_policy='draft', ai_mode=mode,
                   film=None, world={'seed': world_seed, 'takes': [], 'plate': None})
    for key in ('film_of', 'film_wave', 'film_marked_draft', 'review_cache', 'continuity_error'):
        project.pop(key, None)
    project['continuity_plan']['of'] = studio.continuity_inputs(project)
    names = {project['reference']} if project.get('reference') else set()
    for entry in (project.get('character_references') or {}).values():
        if isinstance(entry, dict) and entry.get('image'):
            names.add(entry['image'])
    for prop in project.get('props', []):
        for variant in (prop.get('variants') or {}).values():
            if isinstance(variant, dict) and variant.get('name'):
                names.add(variant['name'])
    if any(not isinstance(name, str) or not name for name in names):
        raise ValueError('Invalid source reference image')
    return project, sorted(names)


def finish_after_preview(worker, project_id: str) -> int:
    """Drop only this scratch run's queued assembly/reviews; never interrupt running work."""
    removed = 0
    with worker.lock:
        for job in worker.jobs:
            if job.get('project') == project_id and job.get('state') == 'queued' and job.get('kind') in ('stitch', 'review', 'review_frame'):
                job.update(state='cancelled', error='First-shot benchmark completed; scratch follow-up skipped')
                removed += 1
        if removed:
            worker._save_jobs()
    return removed


def run(source_file: Path, output: Path, mode: str, variant: str, seed: int, world_seed: int,
        comfy_url: str, studio_url: str, timeout: int, cache_state: str) -> dict:
    if mode not in ('fast', 'normal') or variant not in ('world-first', 'deferred'):
        raise ValueError('Choose a supported mode and scheduler variant')
    if any(isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 2**31
           for value in (seed, world_seed)) or timeout <= 0:
        raise ValueError('Seeds must be non-negative 31-bit integers and timeout must be positive')
    source_file = source_file.resolve()
    output = output.resolve()
    if source_file.parent == output or source_file.parent in output.parents:
        raise ValueError('Output must be outside the source film folder')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('Choose a new or empty output folder; existing files were kept')
    if studio_url and not studio_is_idle(studio_url):
        raise RuntimeError('Studio has active jobs; wait until they finish')
    if not queue_is_idle(comfy_url):
        raise RuntimeError('ComfyUI is busy; wait until its queue is empty')
    source_code = source_fingerprint()
    source_bytes = source_file.read_bytes()
    project, image_names = prepare(json.loads(source_bytes), mode, seed, world_seed)
    images = [local_image(source_file.parent, name) for name in image_names]
    digest = hashlib.sha256(source_bytes)
    for path in images:
        digest.update(path.name.encode('utf-8'))
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    digest.update(json.dumps({'mode': mode, 'seed': seed, 'world_seed': world_seed}, sort_keys=True).encode())
    output.mkdir(parents=True, exist_ok=True)
    studio.PROJECTS = output / 'projects'
    worker = studio.Studio(comfy_url)
    worker.setup = Setup(worker.comfy, preferences_path=output / 'setup-preferences.json')
    destination = worker.path(project['id'])
    destination.mkdir(parents=True, exist_ok=True)
    for path in images:
        shutil.copy2(path, destination / path.name)
    worker.save(project)
    # Hold the worker lock while the baseline world job is inserted and the
    # normal scheduler observes it. The recorded start includes both enqueue
    # operations. Current deferral is exercised through unmodified Studio code.
    with worker.lock:
        started = time.time()
        if variant == 'world-first':
            worker.enqueue('world', project['id'], None, 'Painting the world', auto=True)
        worker.queue_film(project['id'], render_started_at=started)
    deadline = time.monotonic() + timeout
    printed = {}
    preview_complete = False
    skipped_followups = 0
    while True:
        with worker.lock:
            jobs = copy.deepcopy([job for job in worker.jobs if job['project'] == project['id']])
        if not preview_complete and any(job.get('kind') == 'video' and job.get('state') == 'done'
                and job.get('timing', {}).get('playable_at') is not None for job in jobs):
            # The run only measures first playable. Let any running operation
            # and the world job finish, but avoid starting scratch-only review
            # and assembly work. Never interrupt a shared ComfyUI operation.
            skipped_followups += finish_after_preview(worker, project['id'])
            preview_complete = True
            continue
        for job in jobs:
            summary = (job['state'], job['label'], job.get('error'))
            if printed.get(job['id']) != summary:
                print(json.dumps({'kind': job['kind'], 'state': job['state'], 'label': job['label'],
                                  'error': job.get('error')}), flush=True)
                printed[job['id']] = summary
        if not any(job['state'] in ('running', 'queued') for job in jobs):
            break
        if time.monotonic() >= deadline:
            raise TimeoutError('Evaluation timed out; scratch files and job history were kept')
        time.sleep(1)
    video = next((job for job in jobs if job['kind'] == 'video' and job.get('shot') == project['shots'][0]['id']), None)
    world = next((job for job in jobs if job['kind'] == 'world'), None)
    playable = (video or {}).get('timing', {}).get('playable_at')
    ready = playable - started if isinstance(playable, (int, float)) and playable >= started else None
    def job_start(job):
        created, queued = (job or {}).get('created'), (job or {}).get('timing', {}).get('queue_seconds')
        return created + queued if isinstance(created, (int, float)) and isinstance(queued, (int, float)) else None
    video_start, world_start = job_start(video), job_start(world)
    observed_order = ('deferred' if video_start < world_start else 'world-first') if video_start is not None and world_start is not None else None
    result = {'variant': variant, 'mode': mode, 'seed': seed, 'world_seed': world_seed,
              'matched_input_sha256': digest.hexdigest(), 'cache_state_reported': cache_state,
              'working_tree_sha256_at_start': source_code,
              'observed_order': observed_order,
              'queued_followups_skipped': skipped_followups,
              'project_id': project['id'], 'first_shot_seconds': ready,
              'world_elapsed_seconds': (world or {}).get('elapsed'),
              'world_state': (world or {}).get('state'), 'video_state': (video or {}).get('state'),
              'limitations': ['One already-planned shot with existing cast; excludes writing, planning and casting.',
                              'World-first is a simulation using the current implementation.',
                              'Working-tree hash does not establish which node code ComfyUI loaded at startup.',
                              'Cache state is operator-reported; model loading and server caches may affect timings.'],
              'jobs': jobs}
    (output / 'report.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    if ready is None:
        raise RuntimeError('No first playable shot was produced; inspect the scratch report')
    if observed_order != variant:
        raise RuntimeError('Actual job order did not match the requested variant; inspect the scratch report')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='Path to the source film project.json')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=('fast', 'normal'), required=True)
    parser.add_argument('--variant', choices=('world-first', 'deferred'), required=True)
    parser.add_argument('--seed', type=int, required=True)
    parser.add_argument('--world-seed', type=int, default=1421)
    parser.add_argument('--cache-state', choices=('cold', 'warm', 'unknown'), default='unknown',
                        help='Record your observed model/cache state; the tool cannot verify it')
    parser.add_argument('--comfy', default='http://127.0.0.1:8288')
    parser.add_argument('--studio', default='http://127.0.0.1:8420')
    parser.add_argument('--timeout', type=int, default=1800)
    args = parser.parse_args()
    outcome = run(args.source, args.output, args.mode, args.variant, args.seed, args.world_seed,
                  args.comfy, args.studio, args.timeout, args.cache_state)
    print(json.dumps({key: value for key, value in outcome.items() if key != 'jobs'}, indent=2))
