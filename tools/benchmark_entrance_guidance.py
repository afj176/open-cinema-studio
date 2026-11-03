"""Compare a reference-guided ending with an unguided entrance in a scratch film.

Requires a completed scratch project, an opening image with the returning person
offscreen, and an explicit portrait of that person. Writes only to an empty
output folder. GPU-intensive; never changes the source project.
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
import graphs
from comfy import Comfy
from studio import director, performing_cast
from benchmark_film_pipeline import queue_is_idle, studio_is_idle


def run(project_file: Path, shot_number: int, opening: Path, portrait: Path,
        actor: str, seeds: list[int], output: Path, mode: str, comfy_url: str, studio_url: str):
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('Choose a new or empty output folder')
    if not actor.strip() or not seeds or len(set(seeds)) != len(seeds) or any(s < 0 or s >= 2**31 for s in seeds):
        raise ValueError('A character and unique 31-bit seeds are required')
    if studio_url and not studio_is_idle(studio_url) or not queue_is_idle(comfy_url):
        raise RuntimeError('Studio or ComfyUI is busy')
    project_file = project_file.resolve()
    project = json.loads(project_file.read_text(encoding='utf-8'))
    if not 1 <= shot_number <= len(project['shots']):
        raise ValueError('Shot number is outside the film')
    shot = project['shots'][shot_number - 1]
    opening, portrait = opening.resolve(), portrait.resolve()
    if not opening.is_file() or not portrait.is_file():
        raise ValueError('Opening image and portrait must exist')
    output.mkdir(parents=True, exist_ok=True)
    client = Comfy(comfy_url)
    start = client.upload(opening)
    person = client.upload(portrait)
    lead, cast = performing_cast(project, shot)
    end_prompt = (f"Edit Picture 1 into the final moment of the same shot. {shot.get('end_state', '')}. "
                  f"Picture 2 is {actor}; preserve this person's face, hair, clothing and distinguishing features. "
                  "Keep the same location, lighting, existing characters and visual style. One frame, no text.")
    motion = director.motion_prompt(shot['action'], shot['camera_move'], shot.get('sound', ''),
                                    project['look'], project.get('cast', ''), shot['shot_size'],
                                    project.get('continuity', ''), lead,
                                    cast, shot.get('line', ''), shot.get('start_frame', ''), shot.get('end_state', ''))
    results = []
    for seed in seeds:
        begin = time.monotonic()
        target_graph = graphs.coverage_graph(end_prompt, seed, start, f'open-cinema-entrance-eval/end-{seed}',
                                             project['aspect'], second_reference=person)
        target = client.run(target_graph, timeout=900)[0]
        target_file = output / f'end-{seed}.png'
        client.download(target, target_file)
        target_image = client.upload(target_file)
        for variant in ('baseline', 'guided'):
            graph = graphs.shot_graph(start, motion, seed, project['aspect'], float(shot['seconds']),
                    f'open-cinema-entrance-eval/{variant}-{seed}',
                    end_image=target_image if variant == 'guided' else None, performance=mode)
            started = time.monotonic()
            video = client.run(graph, timeout=900)[0]
            filename = f'{variant}-{seed}.mp4'
            client.download(video, output / filename)
            results.append({'seed': seed, 'variant': variant, 'video': filename, 'end_frame': target_file.name,
                            'seconds': round(time.monotonic() - started, 3), 'mode': mode})
            (output / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
            print(json.dumps(results[-1]), flush=True)
        print(json.dumps({'seed': seed, 'pair_elapsed': round(time.monotonic()-begin, 3)}), flush=True)
    return results


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('project', type=Path)
    p.add_argument('--shot', type=int, required=True)
    p.add_argument('--opening', type=Path, required=True)
    p.add_argument('--portrait', type=Path, required=True)
    p.add_argument('--actor', required=True)
    p.add_argument('--seed', action='append', type=int, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--mode', choices=('fast', 'normal'), default='fast')
    p.add_argument('--comfy', default='http://127.0.0.1:8288')
    p.add_argument('--studio', default='http://127.0.0.1:8420')
    a = p.parse_args()
    run(a.project, a.shot, a.opening, a.portrait, a.actor, a.seed, a.output, a.mode, a.comfy, a.studio)
