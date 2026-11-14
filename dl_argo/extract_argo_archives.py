"""从已验收国内压缩包提取冻结清单中的 Argo Core 剖面并逐份检查、记录哈希。"""

import argparse
import csv
import hashlib
import io
import json
import logging
import re
import tarfile
import time
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import h5netcdf
import numpy as np
from scipy.io import netcdf_file

from audit_argo_archives import BASE_DIR, DOWNLOADS, INVENTORY, sha256_file

OUTPUT_DIR = BASE_DIR / "data/raw/argo"
PREPARED_PARENTS = set()


def configure_worker(output_dir: str) -> None:
    """在独立工作进程中使用指定输出目录。"""
    global OUTPUT_DIR
    OUTPUT_DIR = Path(output_dir)


@contextmanager
def open_profile(payload: bytes):
    """完整读取 NetCDF3 或 NetCDF4 原始剖面。"""
    if payload.startswith(b"CDF"):
        with netcdf_file(io.BytesIO(payload), mode="r", mmap=False) as ds:
            yield ds
    elif payload.startswith(b"\x89HDF\r\n\x1a\n"):
        with h5netcdf.File(io.BytesIO(payload), mode="r") as ds:
            variables = {
                name: SimpleNamespace(data=variable[...], units=variable.attrs.get("units", b""))
                for name, variable in ds.variables.items()
            }
            yield SimpleNamespace(variables=variables)
    else:
        raise ValueError("不是可识别的 NetCDF3/4 文件")


def profile_issues(payload: bytes, row: dict[str, str]) -> list[str]:
    """读取全部 NetCDF3/4 变量，标记元数据问题；不执行剖面质量筛选。"""
    issues = []
    with open_profile(payload) as ds:
        required = [
            "PRES", "TEMP", "PSAL", "PRES_QC", "TEMP_QC", "PSAL_QC",
            "PRES_ADJUSTED", "TEMP_ADJUSTED", "PSAL_ADJUSTED",
            "PRES_ADJUSTED_QC", "TEMP_ADJUSTED_QC", "PSAL_ADJUSTED_QC",
            "PRES_ADJUSTED_ERROR", "TEMP_ADJUSTED_ERROR", "PSAL_ADJUSTED_ERROR",
            "JULD", "LATITUDE", "LONGITUDE", "PLATFORM_NUMBER", "CYCLE_NUMBER",
            "DIRECTION", "DATA_MODE", "DATE_UPDATE",
        ]
        issues.extend(f"missing:{name}" for name in required if name not in ds.variables)
        for name, expected in (("LATITUDE", float(row["latitude"])), ("LONGITUDE", float(row["longitude"]))):
            if name in ds.variables:
                actual = float(ds.variables[name].data.flat[0])
                difference = actual - expected
                if name == "LONGITUDE":
                    difference = (difference + 180) % 360 - 180
                if not np.isfinite(actual) or abs(difference) > 0.0011:
                    issues.append(f"index_mismatch:{name}")
        if "JULD" in ds.variables:
            variable = ds.variables["JULD"]
            units = getattr(variable, "units", b"")
            if isinstance(units, bytes):
                units = units.decode("ascii")
            if "days since 1950-01-01" not in units:
                issues.append("unexpected:JULD_units")
            else:
                expected = (datetime.strptime(row["date"], "%Y%m%d%H%M%S") - datetime(1950, 1, 1)).total_seconds()
                actual = float(variable.data.flat[0]) * 86400
                if not np.isfinite(actual) or abs(actual - expected) > 2:
                    issues.append("index_mismatch:JULD")
        if "PLATFORM_NUMBER" in ds.variables:
            actual = ds.variables["PLATFORM_NUMBER"].data[0].tobytes().decode("ascii").strip(" \x00")
            if actual != row["file"].split("/")[1]:
                issues.append("path_mismatch:PLATFORM_NUMBER")
        if "CYCLE_NUMBER" in ds.variables:
            match = re.search(r"_(\d+)(?:D)?\.nc$", row["file"])
            if match and int(ds.variables["CYCLE_NUMBER"].data.flat[0]) != int(match.group(1)):
                issues.append("path_mismatch:CYCLE_NUMBER")
        if "DATE_UPDATE" in ds.variables:
            actual = ds.variables["DATE_UPDATE"].data.tobytes().decode("ascii").strip(" \x00")
            if actual != row["date_update"]:
                issues.append("version_difference:DATE_UPDATE")
    return issues


def store_profile(payload: bytes, row: dict, prepared_parents=None) -> dict:
    """检查并写入一个独立目标；已有文件必须与原包内容完全相同。"""
    name = row["file"]
    digest = hashlib.sha256(payload).hexdigest()
    prior = row.get("_resume")
    if prior and prior["sha256"] == digest and prior["status"] == "PASS":
        issues = []
    else:
        try:
            issues = profile_issues(payload, row)
        except Exception as exc:
            issues = [f"netcdf_read_error:{type(exc).__name__}"]
    if prepared_parents is None:
        prepared_parents = PREPARED_PARENTS
    target = OUTPUT_DIR.joinpath(*PurePosixPath(name).parts)
    if target.parent not in prepared_parents:
        target.parent.mkdir(parents=True, exist_ok=True)
        prepared_parents.add(target.parent)
    reused = target.exists()
    if reused:
        if target.stat().st_size != len(payload) or sha256_file(target) != digest:
            raise ValueError(f"既有目标与原包不同，未覆盖：{target}")
    else:
        partial = target.with_suffix(".nc.part")
        with partial.open("wb") as stream:
            stream.write(payload)
        partial.rename(target)
    return {"file": name, "bytes": len(payload), "sha256": digest, "issues": issues, "reused": reused}


def extract_archive(dac: str, audit: Path, rows: dict, manifest: csv.DictWriter, anomalies: csv.DictWriter, logger: logging.Logger, flush_reports=None, resume_records=None) -> dict:
    """只写入冻结清单选中的普通文件，保留原内容，不覆盖不同的既有文件。"""
    checked = json.loads((audit / f"{dac}.json").read_text(encoding="utf-8"))
    source = DOWNLOADS / f"{dac}.tar.gz"
    if checked["status"] != "PASS" or sha256_file(source) != checked["sha256"]:
        raise ValueError(f"{dac} 原包未通过验收或哈希发生变化")
    found = set()
    scheduled = set()
    result = {"dac": dac, "expected": len(rows), "written": 0, "reused": 0, "bytes": 0, "files_with_issues": 0}
    last_progress = time.monotonic()
    pending = deque()

    def record_one() -> None:
        nonlocal last_progress
        item = pending.popleft().result()
        issues = item["issues"]
        name = item["file"]
        result["reused" if item["reused"] else "written"] += 1
        result["bytes"] += item["bytes"]
        manifest.writerow({"file": name, "bytes": item["bytes"], "sha256": item["sha256"], "archive_sha256": checked["sha256"], "status": "ISSUE" if issues else "PASS"})
        if issues:
            anomalies.writerow({"file": name, "issues": ";".join(issues)})
            result["files_with_issues"] += 1
        found.add(name)
        if time.monotonic() - last_progress >= 25:
            if flush_reports is not None:
                flush_reports()
            logger.info("提取 %s %s/%s written=%s reused=%s issues=%s", dac, len(found), len(rows), result["written"], result["reused"], result["files_with_issues"])
            last_progress = time.monotonic()

    with ProcessPoolExecutor(max_workers=4, initializer=configure_worker, initargs=(str(OUTPUT_DIR),)) as pool, tarfile.open(source, "r|gz", stream=True) as archive:
        for member in archive:
            relative = PurePosixPath(member.name)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("压缩包含不安全路径")
            name = relative.as_posix()
            if not member.isfile() or name not in rows:
                continue
            if name in scheduled:
                raise ValueError(f"压缩包中存在重复目标路径：{name}")
            payload = archive.extractfile(member).read()
            if len(payload) != member.size or not payload:
                raise ValueError(f"目标内容长度错误：{name}")
            scheduled.add(name)
            row = rows[name]
            prior = (resume_records or {}).get(name)
            if prior:
                if prior["archive_sha256"] != checked["sha256"]:
                    raise ValueError("恢复清单的原包 SHA-256 不一致")
                row = dict(row, _resume=prior)
            pending.append(pool.submit(store_profile, payload, row))
            if len(pending) >= 32:
                record_one()
            if len(scheduled) == len(rows):
                break
        while pending:
            record_one()
    result["missing"] = sorted(rows.keys() - found)
    return result


def main() -> None:
    """提取指定资料中心，记录逐文件来源与校验和，支持重跑复用。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True, help="原包验收报告目录")
    parser.add_argument("--dacs", nargs="+", required=True)
    parser.add_argument("--resume-manifest", type=Path, help="复用同一原包的已完成字段检查；仍重新核对源内容及目标哈希")
    args = parser.parse_args()
    if len(args.dacs) != len(set(args.dacs)):
        parser.error("DAC 不能重复")
    rows = {}
    with INVENTORY.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            dac = row["file"].split("/")[0]
            if dac in args.dacs:
                rows.setdefault(dac, {})[row["file"]] = row
    if set(rows) != set(args.dacs):
        parser.error("指定 DAC 不在冻结清单中")
    resume_records = {}
    if args.resume_manifest:
        audited_inventory = json.loads((args.audit / "summary.json").read_text(encoding="utf-8"))["inventory_sha256"]
        if sha256_file(INVENTORY) != audited_inventory:
            raise ValueError("冻结清单发生变化，停止复用之前的字段检查")
        with args.resume_manifest.open(encoding="utf-8", newline="") as stream:
            for record in csv.DictReader(stream):
                if record.get("status") in ("PASS", "ISSUE") and len(record.get("sha256", "")) == 64 and len(record.get("archive_sha256", "")) == 64:
                    resume_records[record["file"]] = record
    report = BASE_DIR / "research/audits" / f"argo_extract_{datetime.now():%Y%m%d_%H%M%S}"
    report.mkdir(parents=True, exist_ok=False)
    logger = logging.getLogger("argo_extract")
    logger.setLevel(logging.INFO)
    for handler in (logging.StreamHandler(), logging.FileHandler(report / "extract.log", encoding="utf-8")):
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger.addHandler(handler)
    summary = {"output": str(OUTPUT_DIR), "audit": str(args.audit), "inventory_sha256": sha256_file(INVENTORY), "dacs": [], "quality_filter_applied": False}
    with (report / "manifest.csv").open("x", encoding="utf-8", newline="") as files, (report / "issues.csv").open("x", encoding="utf-8", newline="", buffering=1) as problems:
        manifest = csv.DictWriter(files, fieldnames=["file", "bytes", "sha256", "archive_sha256", "status"])
        anomalies = csv.DictWriter(problems, fieldnames=["file", "issues"])
        manifest.writeheader()
        anomalies.writeheader()
        files.flush()
        problems.flush()
        for dac in args.dacs:
            logger.info("开始提取 %s expected=%s", dac, len(rows[dac]))
            result = extract_archive(dac, args.audit, rows[dac], manifest, anomalies, logger, files.flush, resume_records)
            summary["dacs"].append(result)
            files.flush()
            problems.flush()
            with (report / f"{dac}.json").open("x", encoding="utf-8") as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2)
            logger.info("完成 %s written=%s reused=%s missing=%s issues=%s", dac, result["written"], result["reused"], len(result["missing"]), result["files_with_issues"])
    with (report / "summary.json").open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2)
    logger.info("批次完成 报告=%s", report)


if __name__ == "__main__":
    main()
