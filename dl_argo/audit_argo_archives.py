"""只读验收 Argo 国内原始压缩包，核对冻结清单并抽查 NetCDF3 剖面。"""

import csv
import gzip
import hashlib
import io
import json
import logging
import tarfile
import time
from datetime import datetime
from pathlib import Path, PurePosixPath

import numpy as np
import xarray as xr

BASE_DIR = Path(__file__).resolve().parents[1]
INVENTORY = BASE_DIR / "research/audits/argo_inventory_20261111_211915.csv"
DOWNLOADS = Path(r"D:\system\Downloads")
DACS = ("kiost", "kma", "csio", "meds", "bodc", "jma", "csiro", "aoml")


def sha256_file(path: Path) -> str:
    """计算输入文件指纹，不改写输入。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_sample(data: bytes, row: dict[str, str]) -> dict:
    """完整解码一份样本，记录字段和与索引的日期、位置对应情况。"""
    result = {"file": row["file"], "bytes": len(data)}
    try:
        with xr.open_dataset(io.BytesIO(data), engine="scipy") as ds:
            ds.load()
            required = [
                "PRES", "TEMP", "PSAL", "PRES_QC", "TEMP_QC", "PSAL_QC",
                "PRES_ADJUSTED", "TEMP_ADJUSTED", "PSAL_ADJUSTED",
                "PRES_ADJUSTED_QC", "TEMP_ADJUSTED_QC", "PSAL_ADJUSTED_QC",
                "PRES_ADJUSTED_ERROR", "TEMP_ADJUSTED_ERROR", "PSAL_ADJUSTED_ERROR",
                "JULD", "LATITUDE", "LONGITUDE", "PLATFORM_NUMBER",
                "CYCLE_NUMBER", "DIRECTION", "DATA_MODE",
            ]
            result["missing_fields"] = [name for name in required if name not in ds]
            result["sizes"] = dict(ds.sizes)
            result["readable"] = True
            result["units"] = {name: str(ds[name].attrs.get("units")) for name in ("PRES", "TEMP", "PSAL") if name in ds}
            result["finite_values"] = {
                name: int(np.isfinite(ds[name].values).sum()) for name in ("PRES", "TEMP", "PSAL") if name in ds
            }
            lat = float(ds.LATITUDE.values.flat[0])
            lon = float(ds.LONGITUDE.values.flat[0])
            result["latitude"] = lat
            result["longitude"] = lon
            result["position_matches_index"] = bool(
                abs(lat - float(row["latitude"])) <= 0.0011
                and abs((lon - float(row["longitude"]) + 180) % 360 - 180) <= 0.0011
            )
            expected = np.datetime64(datetime.strptime(row["date"], "%Y%m%d%H%M%S"))
            actual = ds.JULD.values.flat[0]
            result["time"] = str(actual)
            result["time_matches_index"] = bool(abs(actual - expected) <= np.timedelta64(2, "s"))
    except Exception as exc:
        result["readable"] = False
        result["error_type"] = type(exc).__name__
        result["error"] = str(exc)
    return result


def audit_archive(path: Path, expected: dict[str, dict], writer: csv.DictWriter, logger: logging.Logger) -> tuple[dict, set]:
    """流式读取全部 tar 数据并读至 gzip 尾部，返回可信覆盖及有限样本。"""
    before = path.stat()
    result = {
        "archive": str(path), "compressed_bytes": before.st_size,
        "expected_files": len(expected), "members": 0, "regular_files": 0,
        "matched_files": 0, "matched_bytes": 0, "samples": [], "duplicates": [],
    }
    found = set()
    last_progress = time.monotonic()
    try:
        with path.open("rb") as raw, gzip.GzipFile(fileobj=raw) as uncompressed:
            with tarfile.open(fileobj=uncompressed, mode="r|", stream=True) as archive:
                for member in archive:
                    result["members"] += 1
                    if member.isfile():
                        result["regular_files"] += 1
                    relative = PurePosixPath(member.name)
                    if relative.is_absolute() or ".." in relative.parts:
                        raise ValueError("压缩包包含不安全路径")
                    name = relative.as_posix()
                    if member.isfile() and name in expected:
                        if name in found:
                            result["duplicates"].append(name)
                        else:
                            found.add(name)
                            result["matched_files"] += 1
                            result["matched_bytes"] += member.size
                            writer.writerow({"archive": str(path), "file": name, "bytes": member.size})
                        if len(result["samples"]) < 2:
                            payload = archive.extractfile(member).read()
                            result["samples"].append(inspect_sample(payload, expected[name]))
                    if time.monotonic() - last_progress >= 25:
                        logger.info("扫描 %s members=%s matched=%s/%s", path.name, result["members"], len(found), len(expected))
                        last_progress = time.monotonic()
            # tar 结束标记可能早于 gzip 尾部；继续读至 EOF，触发 CRC/长度检查。
            while uncompressed.read(4 * 1024 * 1024):
                pass
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("扫描期间压缩包发生变化")
        result["sha256"] = sha256_file(path)
        result["status"] = "PASS"
    except Exception as exc:
        result["status"] = "FAIL"
        result["error_type"] = type(exc).__name__
        result["error"] = str(exc)
        found.clear()
    result["missing_files"] = len(expected.keys() - found)
    return result, found


def main() -> None:
    """生成只读验收清单、逐包结果和完整缺口；不提取原始剖面。"""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    audit_dir = BASE_DIR / "research/audits" / f"argo_archives_{stamp}"
    audit_dir.mkdir(parents=True, exist_ok=False)
    logger = logging.getLogger("argo_archive_audit")
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(message)s")
    for handler in (logging.StreamHandler(), logging.FileHandler(audit_dir / "audit.log", encoding="utf-8")):
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    expected = {}
    with INVENTORY.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            dac = row["file"].split("/")[0]
            group = expected.setdefault(dac, {})
            if row["file"] in group:
                raise ValueError("基准清单有重复路径")
            group[row["file"]] = row
    summary = {
        "inventory": str(INVENTORY), "inventory_sha256": sha256_file(INVENTORY),
        "expected_total": sum(len(group) for group in expected.values()),
        "archives": [], "profiles_extracted": 0,
        "scope": "完整压缩包读取和CRC检查、清单路径覆盖；每包仅抽查两份NetCDF，非全部内容验收",
    }
    all_found = set()
    with (audit_dir / "matched_files.csv").open("x", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=["archive", "file", "bytes"])
        writer.writeheader()
        for dac in DACS:
            path = DOWNLOADS / f"{dac}.tar.gz"
            logger.info("开始 %s bytes=%s expected=%s", path, path.stat().st_size, len(expected[dac]))
            result, found = audit_archive(path, expected[dac], writer, logger)
            summary["archives"].append(result)
            all_found.update(found)
            output.flush()
            with (audit_dir / f"{dac}.json").open("x", encoding="utf-8") as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2)
            logger.info("完成 %s status=%s matched=%s missing=%s bytes_to_extract=%s", dac, result["status"], len(found), result["missing_files"], result["matched_bytes"])
    with (audit_dir / "missing_files.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["file", "reason"])
        for dac, group in expected.items():
            for name in group.keys() - all_found:
                writer.writerow([name, "archive_not_downloaded" if dac not in DACS else "missing_or_archive_failed"])
    summary["matched_total"] = len(all_found)
    summary["missing_total"] = summary["expected_total"] - len(all_found)
    summary["matched_bytes"] = sum(result["matched_bytes"] for result in summary["archives"] if result["status"] == "PASS")
    with (audit_dir / "summary.json").open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2)
    logger.info("全部完成 matched=%s missing=%s 报告=%s", summary["matched_total"], summary["missing_total"], audit_dir)


if __name__ == "__main__":
    main()
