"""Compare previous-end and storyboard-led reframing on a recorded scratch shot.

This writes frames to an empty folder, does not modify a project, and uses the
same seeds for both strategies. The prompts and references intentionally differ.
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from comfy import Comfy
import graphs
from studio import director, starting_cast, lead_identity, review_requirements
from benchmark_film_pipeline import queue_is_idle, studio_is_idle
from compare_frame_editors import local_image


def run(project_file: Path, shot_number: int, seeds: list[int], output: Path, comfy: str, studio: str):
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('Choose a new or empty output folder')
    if not seeds or len(set(seeds)) != len(seeds) or any(seed < 0 or seed >= 2**31 for seed in seeds):
        raise ValueError('Choose unique 31-bit seeds')
    if studio and not studio_is_idle(studio) or not queue_is_idle(comfy):
        raise RuntimeError('Studio or ComfyUI is busy')
    project_file = project_file.resolve()
    project = json.loads(project_file.read_text(encoding='utf-8'))
    if not 1 <= shot_number <= len(project['shots']):
        raise ValueError('Shot number is outside the film')
    shot = project['shots'][shot_number-1]
    take = next((t for t in shot.get('takes', {}).get('keyframe', []) if t.get('name') == shot.get('keyframe')), None)
    recipe = (take or {}).get('recipe') or {}
    if recipe.get('frame_source') != 'previous_end' or not take.get('prompt') or not shot.get('sketch') or not project.get('reference'):
        raise ValueError('A selected linked frame, storyboard and lead portrait are required')
    lead, others = starting_cast(project, shot)
    support = project.get('character_references') or {}
    usable = [v['image'] for name,v in support.items() if isinstance(v, dict) and v.get('image') and name.casefold() in others.casefold()]
    if len(usable) != 1:
        raise ValueError('Exactly one visible supporting portrait is required for this comparison')
    folder = project_file.parent
    sources = [local_image(folder, recipe['source_frame']), local_image(folder, shot['sketch']),
               local_image(folder, project['reference']), local_image(folder, usable[0])]
    prompt = director.shot_prompt(shot['action'], shot['shot_size'], project['look'],
              has_cast=True, camera_move=shot['camera_move'], lead=lead, world=project['scene'],
              identity=lead_identity(project), cast=project.get('cast', ''), storyboard=True,
              others=others, line=shot.get('line', ''), start_frame=shot.get('start_frame', ''), world_reference=False)
    prompt += ' ' + director.state_direction(review_requirements(project, shot, 'start')['state'])
    prompt += ' Picture 3 is the visible supporting character; preserve their face, appearance and wardrobe.'
    output.mkdir(parents=True, exist_ok=True)
    client = Comfy(comfy)
    previous, board, lead_ref, supporting = [client.upload(p) for p in sources]
    results = []
    for seed in seeds:
        variants = (('previous', take['prompt'], previous, None, None),
                    ('storyboard', prompt, board, lead_ref, supporting))
        for variant, text, first, second, third in variants:
            graph = graphs.coverage_graph(text, seed, first, f'open-cinema-reframe-strategy/{variant}-{seed}',
                                         project['aspect'], second_reference=second, third_reference=third)
            started = time.monotonic()
            image = client.run(graph, timeout=900)[0]
            filename = f'{variant}-{seed}.png'
            client.download(image, output / filename)
            results.append({'variant': variant, 'seed': seed, 'image': filename,
                            'seconds': round(time.monotonic()-started, 3)})
            (output / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
            print(json.dumps(results[-1]), flush=True)
    return results


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('project', type=Path)
    p.add_argument('--shot', type=int, required=True)
    p.add_argument('--seed', type=int, action='append', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--comfy', default='http://127.0.0.1:8288')
    p.add_argument('--studio', default='http://127.0.0.1:8420')
    a = p.parse_args()
    run(a.project, a.shot, a.seed, a.output, a.comfy, a.studio)
