"""逐文件核对 Argo 提取清单与落盘大小和 SHA-256；不改动原始数据。"""

import argparse
import csv
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path, PurePosixPath

from audit_argo_archives import BASE_DIR, sha256_file


def verify_one(row: dict) -> dict:
    """只读核对一份文件，允许有限并行读取。"""
    relative = PurePosixPath(row["file"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("清单包含不安全路径")
    path = (BASE_DIR / "data/raw/argo").joinpath(*relative.parts)
    reason = None
    if not path.is_file():
        reason = "missing"
    elif path.stat().st_size != int(row["bytes"]):
        reason = "size_mismatch"
    elif sha256_file(path) != row["sha256"]:
        reason = "sha256_mismatch"
    return {"file": row["file"], "bytes": int(row["bytes"]), "reason": reason}


def main() -> None:
    """核验已关闭的完整 manifest，生成独立复核报告。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    result = {"manifest": str(args.manifest), "manifest_sha256": sha256_file(args.manifest), "checked": 0, "bytes": 0, "failures": []}
    seen = set()
    last_progress = time.monotonic()
    with args.manifest.open(encoding="utf-8", newline="") as stream, ThreadPoolExecutor(max_workers=4) as pool:
        for row in pool.map(verify_one, csv.DictReader(stream), buffersize=64):
            if row["file"] in seen:
                raise ValueError("清单包含重复或不安全路径")
            seen.add(row["file"])
            if row["reason"]:
                result["failures"].append({"file": row["file"], "reason": row["reason"]})
            result["checked"] += 1
            result["bytes"] += int(row["bytes"])
            if time.monotonic() - last_progress > 25:
                print(f"复核 checked={result['checked']} failures={len(result['failures'])}", flush=True)
                last_progress = time.monotonic()
    result["status"] = "PASS" if not result["failures"] else "FAIL"
    output = args.manifest.parent / f"verified_{datetime.now():%Y%m%d_%H%M%S}.json"
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False))
    print("REPORT", output)


if __name__ == "__main__":
    main()
