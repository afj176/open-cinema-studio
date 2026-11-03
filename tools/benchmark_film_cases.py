"""Render a reproducible, local, frame-only editor comparison for the film test briefs.

This opt-in GPU benchmark writes to a new output directory and never creates or
changes a Studio project. It does not render videos or score visual quality.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
import graphs
from comfy import Comfy
from studio import director


def run(cases: list[dict], output: Path, comfy_url: str) -> list[dict]:
    names = [case['id'] for case in cases]
    if not names or len(set(names)) != len(names) or any(not re.fullmatch(r'[A-Za-z0-9_-]+', name) for name in names):
        raise ValueError('Evaluation case IDs must be unique simple names')
    if output.exists() and any(output.iterdir()):
        raise FileExistsError('Choose an empty output folder; existing evaluation files were kept')
    output.mkdir(parents=True, exist_ok=True)
    client = Comfy(comfy_url)
    anchors = {}
    for case in cases:
        name, seed, look = case['id'], case['seed'], case['look']
        portrait_prompt = director.cast_prompt(case['subject'], case['brief'], look)
        board_prompt = director.sketch_prompt(case['brief'], 'Medium', 'Static', has_cast=True,
                                              lead=True, world=case['brief'], cast=case['subject'])
        graphs_for_case = [
            ('portrait', graphs.keyframe_graph(portrait_prompt, seed, '16:9',
                f'open-cinema-case-evaluation/{name}-portrait', size=graphs.CAST_SIZE, backend='klein')),
            ('storyboard', graphs.storyboard_graph(board_prompt, seed, '16:9',
                f'open-cinema-case-evaluation/{name}-board', backend='klein')),
        ]
        saved = {}
        for label, graph in graphs_for_case:
            file = client.run(graph, timeout=900)[0]
            path = output / f'{name}-{label}.png'
            client.download(file, path)
            saved[label] = client.upload(path)
        anchors[name] = saved
    records = []
    for backend, build in (('qwen', graphs.coverage_graph), ('klein', graphs.klein_coverage_graph)):
        for case in cases:
            name, seed = case['id'], case['seed']
            prompt = director.shot_prompt(case['brief'], 'Medium', case['look'], has_cast=True,
                                          cast=case['subject'], storyboard=True, start_frame=case['brief'])
            graph = build(prompt, seed, anchors[name]['storyboard'],
                          f'open-cinema-case-evaluation/{name}-{backend}', '16:9',
                          second_reference=anchors[name]['portrait'])
            start = time.monotonic()
            result = client.run(graph, timeout=900)
            seconds = time.monotonic() - start
            image = f'{name}-{backend}.png'
            client.download(result[0], output / image)
            records.append({'case': name, 'seed': seed, 'variant': backend, 'image': image,
                            'timings': {'opening_frame_seconds': round(seconds, 3)}})
            (output / 'results.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
            print(json.dumps(records[-1]), flush=True)
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, default=ROOT / 'tests' / 'fixtures' / 'film_evaluation_cases.json')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--comfy', default='http://127.0.0.1:8288')
    args = parser.parse_args()
    run(json.loads(args.cases.read_text(encoding='utf-8')), args.output, args.comfy)


if __name__ == '__main__':
    main()
