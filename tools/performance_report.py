"""Summarize recorded Studio job timings without reading project content."""
import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import median


def report(jobs):
    groups = defaultdict(list)
    for job in jobs:
        if job.get("state") == "done" and "timing" in job:
            groups[(job.get("kind", "unknown"), job.get("ai_mode", "normal"))].append(job)
    lines = ["kind / mode | jobs | median total | median queue | median Comfy wait | median transfers",
             "--- | ---: | ---: | ---: | ---: | ---:"]
    for (kind, mode), items in sorted(groups.items()):
        def med(fn):
            return f"{median(fn(item) for item in items):.1f}s"
        lines.append(f"{kind} / {mode} | {len(items)} | {med(lambda j: j.get('elapsed', 0))} | "
                     f"{med(lambda j: j['timing'].get('queue_seconds', 0))} | "
                     f"{med(lambda j: j['timing'].get('wait_seconds', 0))} | "
                     f"{med(lambda j: j['timing'].get('upload_seconds', 0) + j['timing'].get('download_seconds', 0))}")
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jobs", nargs="?", type=Path,
                        default=Path(__file__).resolve().parents[1] / "runtime" / "studio-jobs.json")
    args = parser.parse_args()
    print(report(json.loads(args.jobs.read_text(encoding="utf-8"))))
