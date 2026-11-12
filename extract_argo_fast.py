"""只按冻结清单提取 AOML；跳过已有正式文件，不解析 NetCDF、不计算哈希。"""

import csv
import json
import os
import tarfile
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path, PurePosixPath

BASE_DIR = Path(__file__).resolve().parent
INVENTORY = BASE_DIR / "research/audits/argo_inventory_20261111_211915.csv"
OUTPUT_DIR = BASE_DIR / "data/raw/argo"
SOURCE = Path(r"D:\system\Downloads\aoml.tar.gz")


def existing_files() -> set[str]:
    """仅列举文件名，不打开或校验数据内容。"""
    return {
        (Path(folder) / name).relative_to(OUTPUT_DIR).as_posix()
        for folder, _, names in os.walk(OUTPUT_DIR)
        for name in names if name.endswith(".nc")
    }


def write_file(name: str, payload: bytes, parents: set) -> None:
    """写入尚缺文件，完成写入后改为正式名称。"""
    target = OUTPUT_DIR.joinpath(*PurePosixPath(name).parts)
    if target.parent not in parents:
        target.parent.mkdir(parents=True, exist_ok=True)
        parents.add(target.parent)
    partial = target.with_suffix(".nc.part")
    with partial.open("wb") as stream:
        stream.write(payload)
    partial.rename(target)


def main() -> None:
    """顺序读取压缩包，有限并行落盘；只报告文件覆盖，不验收内容。"""
    expected = set()
    with INVENTORY.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            name = row["file"]
            relative = PurePosixPath(name)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("冻结清单含不安全路径")
            expected.add(name)
    selected = {name for name in expected if name.startswith("aoml/")}
    before = existing_files()
    needed = selected - before
    count = 0
    parents = set()
    pending = deque()
    started = time.monotonic()
    last_progress = started
    report = BASE_DIR / "research/audits" / f"argo_fast_{datetime.now():%Y%m%d_%H%M%S}"
    report.mkdir(parents=True, exist_ok=False)

    def progress(message: str) -> None:
        print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}", flush=True)
        with (report / "extract.log").open("a", encoding="utf-8") as stream:
            stream.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}\n")

    progress(f"快速提取：已有 AOML={len(selected & before)}，还需={len(needed)}；不进行内容、字段或哈希检查")
    with ThreadPoolExecutor(max_workers=4) as pool, tarfile.open(SOURCE, "r|gz", stream=True) as archive:
        for member in archive:
            name = member.name.removeprefix("./")
            if member.isfile() and name in needed:
                pending.append(pool.submit(write_file, name, archive.extractfile(member).read(), parents))
                if len(pending) >= 32:
                    pending.popleft().result()
                    count += 1
            if count + len(pending) == len(needed):
                break
            if time.monotonic() - last_progress >= 25:
                progress(f"已新增={count}/{len(needed)}，已扫描包成员={archive.offset // 1024 // 1024} MiB（解压后偏移）")
                last_progress = time.monotonic()
        while pending:
            pending.popleft().result()
            count += 1
    actual = existing_files()
    missing = sorted(expected - actual)
    with (report / "missing_files.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["file"])
        writer.writerows([name] for name in missing)
    result = {
        "output": str(OUTPUT_DIR), "source": str(SOURCE), "mode": "extract_only_no_content_validation",
        "skipped_existing_aoml": len(selected & before), "newly_written": count,
        "actual_files": len(actual), "aoml_files": len(selected & actual),
        "expected_total": len(expected), "missing_total": len(missing),
        "missing_aoml": len(selected - actual), "unexpected_files": len(actual - expected),
        "elapsed_seconds": round(time.monotonic() - started, 1),
    }
    with (report / "summary.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    progress(f"完成 {json.dumps(result, ensure_ascii=False)} 报告={report}")


if __name__ == "__main__":
    main()
