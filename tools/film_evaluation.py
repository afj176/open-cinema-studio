"""Compare reproducible film-evaluation records; no generation or downloads are started.

Each record identifies a case, seed, variant, measured timings in seconds, and
optional human scores on a 0–5 scale. Only matching case/seed pairs are compared.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import median

TIMINGS = ('first_shot_seconds', 'playable_film_seconds', 'opening_frame_seconds')
SCORES = ('identity', 'style', 'continuity', 'action', 'dialogue', 'viewpoint', 'audio_quality')


def compare(records: list[dict], baseline: str, candidate: str) -> dict:
    """Return per-metric matched samples; missing observations never count as zero."""
    indexed = {}
    for item in records:
        key = (item['case'], item['seed'], item.get('mode'), item['variant'])
        if key in indexed:
            raise ValueError(f'Duplicate evaluation record: {key}')
        indexed[key] = item
    pairs = []
    for case, seed, mode, variant in sorted(indexed, key=lambda key: tuple(map(str, key))):
        if variant != baseline or (case, seed, mode, candidate) not in indexed:
            continue
        before, after = indexed[(case, seed, mode, baseline)], indexed[(case, seed, mode, candidate)]
        if before.get('fixture_sha256') != after.get('fixture_sha256'):
            continue
        pairs.append((before, after))
    metrics = {}
    for section, names in (('timings', TIMINGS), ('scores', SCORES)):
        for name in names:
            values = []
            for before, after in pairs:
                a, b = before.get(section, {}).get(name), after.get(section, {}).get(name)
                if a is None or b is None:
                    continue
                if isinstance(a, bool) or isinstance(b, bool) or not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
                    raise ValueError(f'{name} must be numeric or null')
                if not math.isfinite(a) or not math.isfinite(b):
                    raise ValueError(f'{name} must be finite')
                if section == 'scores' and not (0 <= a <= 5 and 0 <= b <= 5):
                    raise ValueError(f'{name} must be scored between 0 and 5')
                if section == 'timings' and (a < 0 or b < 0):
                    raise ValueError(f'{name} must be nonnegative')
                values.append((a, b))
            if values:
                metrics[name] = {'pairs': len(values), 'baseline_median': median(a for a, _ in values),
                                 'candidate_median': median(b for _, b in values),
                                 'median_change': median(b - a for a, b in values)}
    return {'baseline': baseline, 'candidate': candidate, 'matched_pairs': len(pairs),
            'unique_cases': len({before['case'] for before, _ in pairs}), 'metrics': metrics}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('records', type=Path, help='JSON array of recorded cases and human scores')
    parser.add_argument('--baseline', required=True)
    parser.add_argument('--candidate', required=True)
    args = parser.parse_args()
    print(json.dumps(compare(json.loads(args.records.read_text(encoding='utf-8')), args.baseline, args.candidate), indent=2))


if __name__ == '__main__':
    main()
