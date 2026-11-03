"""Compare first and subsequent video renders after requesting a ComfyUI model unload.

This is an opt-in GPU benchmark. Model unloading affects ComfyUI's shared model
cache; disk caches and other clients are not controlled. Source projects are read
only and results go into a new output folder.
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
from benchmark_film_pipeline import queue_is_idle, studio_is_idle
from compare_frame_editors import local_image


def run(project_file: Path, shot_number: int, output: Path, comfy: str, studio: str):
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('Choose a new or empty output folder')
    if studio and not studio_is_idle(studio) or not queue_is_idle(comfy):
        raise RuntimeError('Studio or ComfyUI is busy')
    project_file = project_file.resolve()
    project = json.loads(project_file.read_text(encoding='utf-8'))
    if not 1 <= shot_number <= len(project['shots']):
        raise ValueError('Shot number is outside the film')
    shot = project['shots'][shot_number - 1]
    take = next((v for v in shot.get('takes', {}).get('video', []) if v.get('name') == shot.get('video')), None)
    if not take or not take.get('prompt') or not take.get('keyframe'):
        raise ValueError('A selected video with recorded prompt and keyframe is required')
    opening = local_image(project_file.parent, take['keyframe'])
    output.mkdir(parents=True, exist_ok=True)
    client = Comfy(comfy)
    image = client.upload(opening)
    results = []
    for mode in ('fast', 'normal'):
        if not queue_is_idle(comfy):
            raise RuntimeError('ComfyUI became busy; stopping the benchmark')
        client._json('/free', {'unload_models': True, 'free_memory': True}, timeout=10)
        for index, label in enumerate(('after_unload', 'subsequent')):
            if not queue_is_idle(comfy):
                raise RuntimeError('ComfyUI became busy; stopping the benchmark')
            seed = 900001 + index
            graph = graphs.shot_graph(image, take['prompt'], seed, project['aspect'], float(shot['seconds']),
                                      f'open-cinema-cache-eval/{mode}-{label}', performance=mode)
            started = time.monotonic()
            video = client.run(graph, timeout=900)[0]
            seconds = round(time.monotonic() - started, 3)
            filename = f'{mode}-{label}.mp4'
            client.download(video, output / filename)
            results.append({'mode': mode, 'sample': label, 'seed': seed, 'video': filename,
                            'seconds': seconds, 'cache': 'model unload requested' if index == 0 else 'not controlled'})
            (output / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
            print(json.dumps(results[-1]), flush=True)
    return results


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('project', type=Path)
    p.add_argument('--shot', type=int, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--comfy', default='http://127.0.0.1:8288')
    p.add_argument('--studio', default='http://127.0.0.1:8420')
    a = p.parse_args()
    run(a.project, a.shot, a.output, a.comfy, a.studio)
