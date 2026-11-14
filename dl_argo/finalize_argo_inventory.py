"""汇总已提取 Argo 清单，复审格式兼容性问题，核对目录覆盖并生成交付报告。"""

import argparse
import csv
import json
import os
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from audit_argo_archives import BASE_DIR, INVENTORY, sha256_file
from extract_argo_archives import OUTPUT_DIR, profile_issues


def main() -> None:
    """保留原报告和全部原始文件，只生成新的汇总与复审结果。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifests", type=Path, nargs="+")
    args = parser.parse_args()
    output = BASE_DIR / "research/audits" / f"argo_delivery_{datetime.now():%Y%m%d_%H%M%S}"
    output.mkdir(parents=True, exist_ok=False)
    issue_map = {}
    for manifest in args.manifests:
        with (manifest.parent / "issues.csv").open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                issue_map[row["file"]] = row["issues"].split(";")
    repair_names = {name for name, issues in issue_map.items() if any(issue.startswith("netcdf_read_error:") for issue in issues)}
    expected = set()
    repair_rows = {}
    with INVENTORY.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            expected.add(row["file"])
            if row["file"] in repair_names:
                repair_rows[row["file"]] = row
    repair_results = []
    last_progress = time.monotonic()
    for name in sorted(repair_names):
        try:
            issues = profile_issues((OUTPUT_DIR / name).read_bytes(), repair_rows[name])
        except Exception as exc:
            issues = [f"netcdf_read_error:{type(exc).__name__}"]
        repair_results.append({"file": name, "previous_issues": issue_map[name], "reviewed_issues": issues})
        issue_map[name] = issues
        if time.monotonic() - last_progress > 25:
            print(f"复审格式问题 {len(repair_results)}/{len(repair_names)}", flush=True)
            last_progress = time.monotonic()
    with (output / "format_review.json").open("x", encoding="utf-8") as stream:
        json.dump(repair_results, stream, ensure_ascii=False, indent=2)
    seen = set()
    dacs = Counter()
    sizes = Counter()
    issue_counts = Counter()
    issues_files = 0
    with (output / "manifest.csv").open("x", encoding="utf-8", newline="") as merged, (output / "issues.csv").open("x", encoding="utf-8", newline="") as problems:
        writer = csv.DictWriter(merged, fieldnames=["file", "bytes", "sha256", "archive_sha256", "status"])
        anomalies = csv.DictWriter(problems, fieldnames=["file", "issues"])
        writer.writeheader()
        anomalies.writeheader()
        for manifest in args.manifests:
            with manifest.open(encoding="utf-8", newline="") as stream:
                for row in csv.DictReader(stream):
                    name = row["file"]
                    if name in seen or name not in expected:
                        raise ValueError("汇总清单有重复或范围外路径")
                    if row["status"] == "ISSUE" and name not in issue_map:
                        raise ValueError("异常状态缺少明细，不可生成最终报告")
                    issues = issue_map.get(name, [])
                    row["status"] = "ISSUE" if issues else "PASS"
                    writer.writerow(row)
                    if issues:
                        anomalies.writerow({"file": name, "issues": ";".join(issues)})
                        issues_files += 1
                        issue_counts.update(issues)
                    seen.add(name)
                    dac = name.split("/")[0]
                    dacs[dac] += 1
                    sizes[dac] += int(row["bytes"])
    actual = set()
    zero_bytes = []
    partials = []
    other_files = []
    for folder, _, files in os.walk(OUTPUT_DIR):
        for name in files:
            path = Path(folder) / name
            relative = path.relative_to(OUTPUT_DIR).as_posix()
            if name.endswith(".nc"):
                actual.add(relative)
                if path.stat().st_size == 0:
                    zero_bytes.append(relative)
            elif ".part" in name:
                partials.append(relative)
            else:
                other_files.append(relative)
    missing = sorted(expected - actual)
    with (output / "missing_files.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["file", "reason"])
        for name in missing:
            writer.writerow([name, "source_not_downloaded" if name.startswith("coriolis/") else "unexpected_missing"])
    result = {
        "output": str(OUTPUT_DIR), "inventory": str(INVENTORY), "inventory_sha256": sha256_file(INVENTORY),
        "source_manifests": [{"path": str(path), "sha256": sha256_file(path)} for path in args.manifests],
        "expected_total": len(expected), "manifest_files": len(seen), "actual_files": len(actual),
        "missing_total": len(missing), "missing_by_dac": dict(Counter(name.split('/')[0] for name in missing)),
        "actual_not_in_manifest": sorted(actual - seen), "manifest_not_on_disk": sorted(seen - actual),
        "zero_bytes": zero_bytes, "partials": partials, "other_files": other_files,
        "dac_counts": dict(sorted(dacs.items())), "dac_bytes": dict(sorted(sizes.items())),
        "total_bytes": sum(sizes.values()), "files_with_issues": issues_files,
        "issue_counts": dict(issue_counts), "format_rechecked": len(repair_results),
        "quality_filter_applied": False, "depth_truncated": False,
        "manifest_sha256": sha256_file(output / "manifest.csv"),
    }
    with (output / "summary.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("REPORT", output)


if __name__ == "__main__":
    main()
