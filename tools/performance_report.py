"""Summarize recorded Studio job timings without reading project content."""
import argparse
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median


def report(jobs, project=None):
    if project is not None:
        jobs = [job for job in jobs if job.get('project') == project]
    groups = defaultdict(list)
    for job in jobs:
        if job.get("state") in {"done", "needs_review", "failed", "cancelled"} and "timing" in job:
            groups[(job.get("kind", "unknown"), job.get("ai_mode", "normal"))].append(job)
    lines = ["Timing medians show observed jobs / total jobs; n/a means no recorded value.", "",
             "kind / mode | outcomes | median execution | median queue | median queue + execution | median Comfy wait | median observed transfers",
             "--- | --- | ---: | ---: | ---: | ---: | ---:"]
    for (kind, mode), items in sorted(groups.items()):
        def med(fn):
            values = [value for item in items if (value := fn(item)) is not None]
            return f"{median(values):.1f}s ({len(values)}/{len(items)})" if values else 'n/a'
        def seconds(value):
            return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None
        def end_to_end(job):
            queue, elapsed = seconds(job['timing'].get('queue_seconds')), seconds(job.get('elapsed'))
            return queue + elapsed if queue is not None and elapsed is not None else None
        def transfers(job):
            values = [seconds(job['timing'].get(key)) for key in ('upload_seconds', 'download_seconds')]
            observed = [value for value in values if value is not None]
            return sum(observed) if observed else None
        outcomes = ", ".join(f"{state}: {count}" for state, count in sorted(Counter(j['state'] for j in items).items()))
        lines.append(f"{kind} / {mode} | {outcomes} | {med(lambda j: seconds(j.get('elapsed')))} | "
                     f"{med(lambda j: seconds(j['timing'].get('queue_seconds')))} | {med(end_to_end)} | "
                     f"{med(lambda j: seconds(j['timing'].get('wait_seconds')))} | {med(transfers)}")
    counters = [("history_requests", "History requests"), ("upload_cache_hits", "Upload reuse"),
                ("reviewer_retries", "Reviewer retries"), ("image_repairs", "Image repairs"),
                ("repair_rejections", "Worse repairs rejected"), ("review_cache_hits", "Review reuse"),
                ("candidate_reuse", "Candidate reuse")]
    if groups:
        lines += ["", "Counts are observed values only; missing instrumentation is not counted as zero.",
                  "kind / mode | " + " | ".join(label for _, label in counters),
                  "--- | " + " | ".join("---:" for _ in counters)]
        for (kind, mode), items in sorted(groups.items()):
            counts = []
            for key, _ in counters:
                values = [item['timing'][key] for item in items if isinstance(item['timing'].get(key), int)
                          and not isinstance(item['timing'].get(key), bool) and item['timing'][key] >= 0]
                counts.append(str(sum(values)) if values else 'n/a')
            lines.append(f"{kind} / {mode} | " + " | ".join(counts))
    # A render request has an explicit shared start marker; older jobs have no
    # marker and are not inferred into runs from proximity in the job history.
    first_playable = {}
    for job in jobs:
        if job.get('kind') != 'video':
            continue
        start, ready = job.get('render_started_at'), job.get('timing', {}).get('playable_at')
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
                   for value in (start, ready)) or ready < start:
            continue
        key = (job.get('project', 'unknown'), start)
        first_playable[key] = min(first_playable.get(key, ready), ready)
    if first_playable:
        lines += ['', 'Render request to first selected playable shot (excludes earlier story writing)',
                  'film / request (UTC) | seconds', '--- | ---:']
        for (film, start), ready in sorted(first_playable.items(), key=lambda item: item[0][1]):
            stamp = datetime.fromtimestamp(start, timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            lines.append(f'{film} / {stamp} | {ready - start:.1f}s')
    node_totals = defaultdict(lambda: [0.0, 0])
    for job in jobs:
        for kind, value in job.get('timing', {}).get('observed_nodes', {}).items():
            node_totals[kind][0] += value['seconds']
            node_totals[kind][1] += value['spans']
    if node_totals:
        lines += ['', 'Observed ComfyUI node spans (partial event-stream observations; not full execution accounting)',
                  'node class | total observed | spans', '--- | ---: | ---:']
        for kind, (seconds, spans) in sorted(node_totals.items(), key=lambda item: -item[1][0]):
            lines.append(f'{kind} | {seconds:.1f}s | {spans}')
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jobs", nargs="?", type=Path,
                        default=Path(__file__).resolve().parents[1] / "runtime" / "studio-jobs.json")
    parser.add_argument('--project', help='Limit the report to one project ID')
    args = parser.parse_args()
    print(report(json.loads(args.jobs.read_text(encoding="utf-8")), project=args.project))
