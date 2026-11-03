"""Compare Qwen and Klein on a recorded linked-shot reframe without modifying a film.

Both variants use the same saved previous-end image, prompt, optional cast
count instruction, and seed. Generated images and results are saved only in
the requested new or empty output directory. This submits GPU work to ComfyUI.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from benchmark_film_pipeline import queue_is_idle, studio_is_idle
from compare_frame_editors import local_image
from comfy import Comfy
import graphs


def compare(project_file: Path, shot_number: int, seed: int, output: Path,
            comfy_url: str, studio_url: str, expected_cast: int | None = None) -> list[dict]:
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('Choose a new or empty output folder; existing files were kept')
    if studio_url and not studio_is_idle(studio_url):
        raise RuntimeError('Studio has active jobs. Wait for them to finish first.')
    if not queue_is_idle(comfy_url):
        raise RuntimeError('ComfyUI is busy. Wait until its queue is empty first.')
    project_file = project_file.resolve()
    project = json.loads(project_file.read_text(encoding='utf-8'))
    if not 1 <= shot_number <= len(project['shots']):
        raise ValueError('Shot number is outside the film')
    shot = project['shots'][shot_number-1]
    take = next((item for item in shot.get('takes', {}).get('keyframe', []) if item.get('name') == shot.get('keyframe')), None)
    recipe = (take or {}).get('recipe') or {}
    if recipe.get('frame_source') != 'previous_end' or not recipe.get('source_frame') or not (take or {}).get('prompt'):
        raise ValueError('Select a completed linked-shot frame with its recorded previous-end image and prompt')
    if expected_cast is not None and not 1 <= expected_cast <= 20:
        raise ValueError('Expected cast count must be between 1 and 20')
    source = local_image(project_file.parent, recipe['source_frame'])
    prompt = take['prompt']
    if expected_cast is not None:
        prompt += f' Exactly {expected_cast} visible characters; show each individual once, with no duplicates or extra people.'
    output.mkdir(parents=True, exist_ok=True)
    client = Comfy(comfy_url)
    uploaded = client.upload(source)
    results = []
    for backend, build in (('qwen', graphs.coverage_graph), ('klein', graphs.klein_coverage_graph)):
        graph = build(prompt, seed, uploaded, f'open-cinema-reframe-evaluation/{backend}', project['aspect'])
        start = time.monotonic()
        files = client.run(graph, timeout=900)
        elapsed = time.monotonic() - start
        image = f'{backend}.png'
        client.download(files[0], output / image)
        results.append({'case': 'linked-reframe', 'seed': seed, 'variant': backend, 'image': image,
                        'expected_cast': expected_cast, 'timings': {'opening_frame_seconds': round(elapsed, 3)}})
        (output / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
        print(json.dumps(results[-1]), flush=True)
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project_file', type=Path)
    parser.add_argument('--shot', type=int, required=True)
    parser.add_argument('--seed', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--expected-cast', type=int)
    parser.add_argument('--comfy', default='http://127.0.0.1:8288')
    parser.add_argument('--studio', default='http://127.0.0.1:8420')
    args = parser.parse_args()
    compare(args.project_file, args.shot, args.seed, args.output, args.comfy, args.studio, args.expected_cast)
