"""Compare local frame editors on a copy of one existing shot's references.

This opt-in tool does not modify a film. It submits image generation jobs to the
configured ComfyUI and writes comparison outputs to an explicitly chosen folder.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
import graphs
from comfy import Comfy


def local_image(project_dir: Path, name: str) -> Path:
    path = (project_dir / name).resolve()
    if path.parent != project_dir.resolve() or not path.is_file():
        raise ValueError('Reference image must be an existing file within the selected film')
    return path


def recorded_inputs(project_dir: Path, take: dict) -> tuple[list[Path], str]:
    """Recover the recorded storyboard and ordered references, or refuse an incomplete recipe."""
    recipe = take.get('recipe') or {}
    required = ('frame_source', 'source_frame', 'sketch', 'lead', 'world', 'world_reference',
                'character_references', 'visual')
    if (recipe.get('kind') != 'shot' or any(key not in recipe for key in required)
            or recipe['frame_source'] != 'storyboard' or recipe['source_frame'] != recipe['sketch']
            or not isinstance(recipe['visual'], dict) or not isinstance(recipe['character_references'], list)
            or not isinstance(recipe['world_reference'], bool)):
        raise ValueError('The selected frame has incomplete or unsupported reference provenance; generate a new storyboard-based frame first')
    visual = recipe['visual']
    prop = visual.get('prop')
    if not isinstance(prop, dict) or 'aspect' not in visual:
        raise ValueError('The selected frame has incomplete reference provenance')
    names = [recipe['source_frame']]
    if recipe['lead']:
        names.append(recipe['lead'])
    if prop:
        if not prop.get('image'):
            raise ValueError('The selected frame has no recorded prop reference')
        names.append(prop['image'])
    for entry in recipe['character_references']:
        if not isinstance(entry, dict) or not entry.get('image'):
            raise ValueError('The selected frame has incomplete character references')
        names.append(entry['image'])
    if recipe['world_reference']:
        memory = recipe.get('visual_memory')
        location_image = (memory.get('plate') or memory.get('image')) if isinstance(memory, dict) else recipe['world']
        if not location_image:
            raise ValueError('The selected frame has no recorded location reference')
        names.append(location_image)
    if len(names) > 3 or any(not isinstance(name, str) or not name for name in names):
        raise ValueError('The selected frame has invalid reference provenance')
    referenced_numbers = [int(number) for number in re.findall(r'\bPicture\s+(\d+)\b', take.get('prompt', ''), re.I)]
    if any(number < 1 or number > len(names) for number in referenced_numbers):
        raise ValueError('The recorded prompt references an image missing from the recorded recipe')
    if visual['aspect'] not in graphs.COVERAGE_SIZES or visual['aspect'] not in graphs.KLEIN_IMAGE_SIZES:
        raise ValueError('The selected frame has an unsupported recorded aspect ratio')
    return [local_image(project_dir, name) for name in names], visual['aspect']


def compare(project_id: str, shot_number: int, seeds: list[int], output: Path,
            studio_url: str, comfy_url: str) -> list[dict]:
    if not project_id.isalnum():
        raise ValueError('Invalid project id')
    if not seeds or len(set(seeds)) != len(seeds) or any(type(seed) is not int or not 0 <= seed < 2**31 for seed in seeds):
        raise ValueError('Choose unique non-negative 31-bit seeds')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise FileExistsError('Choose an empty output folder; existing evaluation files were kept')
    with urllib.request.urlopen(studio_url.rstrip('/') + '/api/projects/' + urllib.parse.quote(project_id), timeout=30) as response:
        project = json.load(response)
    if not 1 <= shot_number <= len(project['shots']):
        raise ValueError('Shot number is outside the film')
    shot = project['shots'][shot_number - 1]
    take = next((item for item in shot.get('takes', {}).get('keyframe', []) if item.get('name') == shot.get('keyframe')), None)
    if not take or not take.get('prompt'):
        raise ValueError('The shot needs a selected frame with a recorded prompt')
    folder = ROOT / 'projects' / project_id
    references, aspect = recorded_inputs(folder, take)
    output.mkdir(parents=True, exist_ok=True)
    client = Comfy(comfy_url)
    uploaded = [client.upload(path) for path in references]
    results = []
    detailed = take['recipe']['visual'].get('image_quality') == 'detailed'
    # Identical inputs and seeds; cache and model-loading state are not verified.
    for backend, build in (('qwen', graphs.coverage_graph), ('klein', graphs.klein_coverage_graph)):
        for index, seed in enumerate(seeds):
            options = {'second_reference': uploaded[1] if len(uploaded) > 1 else None,
                       'third_reference': uploaded[2] if len(uploaded) > 2 else None}
            if backend == 'qwen':
                options['detailed'] = detailed
            graph = build(take['prompt'], seed, uploaded[0], f'open-cinema-evaluation/{backend}-{index}',
                          aspect, **options)
            start = time.monotonic()
            files = client.run(graph, timeout=900)
            seconds = time.monotonic() - start
            filename = f'{backend}-{index}.png'
            client.download(files[0], output / filename)
            results.append({'case': project_id + ':' + str(shot_number), 'seed': seed, 'variant': backend,
                            'sample': 'first_in_variant' if index == 0 else 'subsequent_in_variant', 'image': filename,
                            'editor_quality': 'detailed' if backend == 'qwen' and detailed else 'fast',
                            'timings': {'opening_frame_seconds': round(seconds, 3)}})
            (output / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project_id')
    parser.add_argument('--shot', type=int, default=1)
    parser.add_argument('--seed', type=int, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--studio', default='http://127.0.0.1:8420')
    parser.add_argument('--comfy', default='http://127.0.0.1:8288')
    args = parser.parse_args()
    print(json.dumps(compare(args.project_id, args.shot, args.seed, args.output, args.studio, args.comfy), indent=2))


if __name__ == '__main__':
    main()
