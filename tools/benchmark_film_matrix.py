"""Run scripted films serially across modes and seeds, retaining failures and evidence.

Prints the planned matrix unless --run is supplied. Each cell is an isolated
subprocess so Studio's worker threads and project roots cannot leak across cells.
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def matrix(cases: list[str], modes: list[str], offsets: list[int]) -> list[dict]:
    if (not cases or not modes or not offsets or len(set(cases)) != len(cases)
            or len(set(modes)) != len(modes) or len(set(offsets)) != len(offsets)
            or any(not re.fullmatch(r'[A-Za-z0-9_-]+', case) for case in cases)
            or any(mode not in ('fast', 'normal') for mode in modes)
            or any(type(offset) is not int or not 0 <= offset < 2**31 for offset in offsets)):
        raise ValueError('Choose unique safe case names, Fast/Normal modes and nonnegative 31-bit seed offsets')
    return [dict(case=case, mode=mode, seed_offset=offset,
                 folder=f'{case}-{mode}-{offset}')
            for case, mode, offset in itertools.product(cases, modes, offsets)]


def execute(cells: list[dict], output: Path, cases_path: Path, comfy: str, studio: str,
            backend: str, timeout: int, speech: bool = False) -> list[dict]:
    from benchmark_film_pipeline import load_case
    # Validate every fixture before creating output or submitting GPU work.
    for cell in cells:
        load_case(cases_path, cell['case'], seed_offset=cell['seed_offset'])
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('Choose a new or empty matrix output directory')
    output.mkdir(parents=True, exist_ok=True)
    records = []
    for cell in cells:
        folder = output / cell['folder']
        command = [sys.executable, str(ROOT / 'tools/benchmark_film_pipeline.py'),
                   '--case', cell['case'], '--cases', str(cases_path.resolve()),
                   '--mode', cell['mode'], '--seed-offset', str(cell['seed_offset']),
                   '--frame-backend', backend, '--output', str(folder.resolve()),
                   '--comfy', comfy, '--studio', studio, '--timeout', str(timeout)]
        print(json.dumps({'starting': cell}), flush=True)
        # Keep logs per cell; a failed render is evidence, never a successful score.
        with (output / (cell['folder'] + '.log')).open('w', encoding='utf-8') as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=False)
        row = {**cell, 'exit_code': result.returncode, 'pipeline_complete': result.returncode == 0,
               'quality': 'not_assessed', 'inspection': None}
        report = folder / 'report.json'
        if report.is_file():
            try:
                from inspect_film_pipeline import inspect
                inspect(report, folder / 'inspection', speech)
                row['inspection'] = str(Path(cell['folder']) / 'inspection/inspection.json')
            except Exception as error:
                row['inspection_error'] = str(error)
        records.append(row)
        (output / 'matrix.json').write_text(json.dumps(
            {'planned': cells, 'completed': records, 'frame_backend': backend}, indent=2), encoding='utf-8')
        print(json.dumps(row), flush=True)
        if result.returncode == 2:
            # The pipeline timed out with GPU work potentially still active.
            # Never overlap a new film or interrupt someone else's Comfy job.
            break
    return records


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, default=ROOT / 'tests/fixtures/film_pipeline_cases.json')
    parser.add_argument('--case', action='append')
    parser.add_argument('--mode', action='append', choices=('fast', 'normal'))
    parser.add_argument('--seed-offset', action='append', type=int)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--frame-backend', choices=('qwen', 'klein'), default='qwen')
    parser.add_argument('--comfy', default='http://127.0.0.1:8288')
    parser.add_argument('--studio', default='http://127.0.0.1:8420')
    parser.add_argument('--timeout', type=int, default=1800)
    parser.add_argument('--speech', action='store_true')
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    cases = args.case or [case['id'] for case in json.loads(args.cases.read_text(encoding='utf-8'))]
    cells = matrix(cases, args.mode or ['fast', 'normal'], args.seed_offset or [0, 100])
    if not args.run:
        print(json.dumps(cells, indent=2))
    else:
        records = execute(cells, args.output, args.cases, args.comfy, args.studio,
                          args.frame_backend, args.timeout, args.speech)
        raise SystemExit(0 if len(records) == len(cells) and all(row['pipeline_complete'] for row in records) else 1)
