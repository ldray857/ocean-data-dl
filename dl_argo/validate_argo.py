"""Read-only validation of frozen Core-Argo files, with one read per file.

No hashes, downloads, filtering of original files, interpolation or depth
conversion. QC counts are diagnostic scenarios, not a final science selection.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import os
import re
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import h5netcdf
import numpy as np
from scipy.io import netcdf_file

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "research/audits/argo_inventory_20261111_211915.csv"
RAW = ROOT / "data/raw/argo"
PARAMETERS = ("PRES", "TEMP", "PSAL")
METADATA = ("LATITUDE", "LONGITUDE", "JULD", "JULD_QC", "POSITION_QC", "DATA_MODE",
            "PLATFORM_NUMBER", "CYCLE_NUMBER", "DIRECTION", "DATE_UPDATE")
FIELDS = ["file", "format", "bytes", "readable", "profiles", "modes", "paired_finite_points",
          "paired_qc1_points", "paired_qc12_points", "profiles_with_qc12_pairs",
          "selected_pres_finite_points", "selected_temp_finite_points", "selected_psal_finite_points",
          "pressure_min_qc12_dbar", "pressure_max_qc12_dbar", "issues", "error"]


def text(value: object) -> str:
    """Decode an Argo character scalar or character array."""
    array = np.asarray(value)
    if array.dtype.kind == "S":
        result = array.tobytes().decode("ascii", errors="replace")
    elif array.dtype.kind == "U":
        result = "".join(array.flatten())
    else:
        result = str(value)
    return result.strip(" \x00")


def read_arrays(payload: bytes) -> tuple[str, dict, dict, int]:
    """Fully read every root variable in a NetCDF3 or NetCDF4 profile."""
    if payload.startswith(b"CDF"):
        with netcdf_file(io.BytesIO(payload), mode="r", mmap=False) as dataset:
            arrays = {key: variable.data.copy() for key, variable in dataset.variables.items()}
            attributes = {key: dict(variable._attributes) for key, variable in dataset.variables.items()}
            return "NetCDF3", arrays, attributes, int(dataset.dimensions.get("N_PROF", 0) or 0)
    if payload.startswith(b"\x89HDF\r\n\x1a\n"):
        with h5netcdf.File(io.BytesIO(payload), "r") as dataset:
            arrays = {key: variable[...] for key, variable in dataset.variables.items()}
            attributes = {key: dict(variable.attrs) for key, variable in dataset.variables.items()}
            return "NetCDF4", arrays, attributes, len(dataset.dimensions["N_PROF"])
    raise ValueError("文件头不是 NetCDF3/4")


def numeric(array: np.ndarray, attributes: dict) -> np.ndarray:
    """Decode numeric fill values and optional packing without QC screening."""
    result = np.asarray(array, dtype=np.float64).copy()
    invalid = ~np.isfinite(result) | (np.abs(result) > 1e30)
    for key in ("_FillValue", "missing_value"):
        for fill in np.asarray(attributes.get(key, [])).flatten():
            invalid |= result == float(fill)
    result = result * float(attributes.get("scale_factor", 1)) + float(attributes.get("add_offset", 0))
    return np.where(invalid, np.nan, result)


def flag_histogram(array: np.ndarray) -> dict[str, int]:
    """Count QC characters, including padding/missing flags."""
    flags = np.asarray(array).astype("S1")
    counts = np.bincount(flags.view(np.uint8).flatten(), minlength=256)
    return {chr(i) if i >= 32 else f"byte_{i}": int(count) for i, count in enumerate(counts) if count}


def inspect_arrays(arrays: dict, attributes: dict, nprof: int, row: dict) -> dict:
    """Inspect metadata and DATA_MODE-selected parameters without altering data."""
    issues = set()
    result = {
        "profiles": nprof, "modes": "", "paired_finite_points": 0, "paired_qc1_points": 0,
        "paired_qc12_points": 0, "profiles_with_qc12_pairs": 0,
        "pressure_min_qc12_dbar": "", "pressure_max_qc12_dbar": "",
        "qc_counts": {}, "mode_counts": {}, "profile_keys": [],
        "selected_pres_finite_points": 0, "selected_temp_finite_points": 0, "selected_psal_finite_points": 0,
    }
    for name in METADATA + PARAMETERS:
        if name not in arrays:
            issues.add(f"missing:{name}")
    if nprof < 1:
        issues.add("invalid:N_PROF")
        result["issues"] = sorted(issues)
        return result

    def scalar(name: str, index: int) -> object | None:
        if name not in arrays:
            return None
        if arrays[name].ndim < 1 or arrays[name].shape[0] != nprof:
            issues.add(f"shape:{name}")
            return None
        return arrays[name][index]

    def number(name: str, index: int) -> float:
        value = scalar(name, index)
        if value is None:
            return float("nan")
        decoded = numeric(np.asarray(value), attributes.get(name, {}))
        if decoded.size != 1:
            issues.add(f"shape:{name}")
            return float("nan")
        return float(decoded.item())

    units = text(attributes.get("JULD", {}).get("units", ""))
    time_unit_ok = "days since 1950-01-01" in units
    if not time_unit_ok:
        issues.add("units:JULD")
    if "REFERENCE_DATE_TIME" in arrays and text(arrays["REFERENCE_DATE_TIME"]) != "19500101000000":
        issues.add("reference_date:JULD")
    if "DATE_UPDATE" in arrays:
        update = text(arrays["DATE_UPDATE"])
        if update != row["date_update"]:
            issues.add("index_difference:DATE_UPDATE")
    expected_time = datetime.strptime(row["date"], "%Y%m%d%H%M%S")
    expected_cycle = int(re.search(r"_(\d+)(?:D)?\.nc$", row["file"]).group(1))
    expected_direction = "D" if row["file"].endswith("D.nc") else "A"
    mode_counts = Counter()
    qc_counts = defaultdict(Counter)
    pressure_bounds = []

    for index in range(nprof):
        mode_value = scalar("DATA_MODE", index)
        mode = text(mode_value) if mode_value is not None else "?"
        mode_counts[mode] += 1
        if mode not in ("R", "A", "D"):
            issues.add("invalid:DATA_MODE")
        platform_value = scalar("PLATFORM_NUMBER", index)
        platform = text(platform_value) if platform_value is not None else ""
        if platform and platform != row["file"].split("/")[1]:
            issues.add("path_mismatch:PLATFORM_NUMBER")
        cycle = number("CYCLE_NUMBER", index)
        if np.isfinite(cycle) and cycle != expected_cycle:
            issues.add("path_mismatch:CYCLE_NUMBER")
        direction_value = scalar("DIRECTION", index)
        direction = text(direction_value) if direction_value is not None else ""
        if direction and direction != expected_direction:
            issues.add("path_mismatch:DIRECTION")
        if platform and np.isfinite(cycle) and direction:
            result["profile_keys"].append((platform, int(cycle), direction, index))
        latitude = number("LATITUDE", index)
        longitude = number("LONGITUDE", index)
        days = number("JULD", index)
        if not np.isfinite(latitude) or not -90 <= latitude <= 90:
            issues.add("invalid:LATITUDE")
        elif abs(latitude - float(row["latitude"])) > 0.0011:
            issues.add("index_mismatch:LATITUDE")
        if not np.isfinite(longitude) or not -180 <= longitude <= 360:
            issues.add("invalid:LONGITUDE")
        elif abs((longitude - float(row["longitude"]) + 180) % 360 - 180) > 0.0011:
            issues.add("index_mismatch:LONGITUDE")
        if np.isfinite(latitude) and np.isfinite(longitude):
            if not (-20 <= latitude <= 20 and 120 <= longitude % 360 <= 280):
                issues.add("outside:research_box")
        if time_unit_ok:
            if not np.isfinite(days) or abs(days) > 200000:
                issues.add("invalid:JULD")
            else:
                timestamp = datetime(1950, 1, 1) + timedelta(days=days)
                if abs((timestamp - expected_time).total_seconds()) > 2:
                    issues.add("index_mismatch:JULD")
                if not datetime(2005, 1, 1) <= timestamp < datetime(2025, 7, 1):
                    issues.add("outside:research_time")
        for name in ("POSITION_QC", "JULD_QC"):
            value = scalar(name, index)
            if value is not None:
                qc_counts[name].update(flag_histogram(np.asarray(value)))

        values = {}
        flags = {}
        suffix = "_ADJUSTED" if mode in ("A", "D") else ""
        if mode not in ("A", "D", "R"):
            continue
        for parameter in PARAMETERS:
            selected = parameter + suffix
            value = scalar(selected, index)
            qc_value = scalar(selected + "_QC", index)
            if value is None:
                issues.add(f"missing_selected:{selected}")
                continue
            if np.asarray(value).ndim != 1:
                issues.add(f"shape:{selected}")
                continue
            values[parameter] = numeric(value, attributes.get(selected, {}))
            result[f"selected_{parameter.lower()}_finite_points"] += int(np.isfinite(values[parameter]).sum())
            if qc_value is None:
                issues.add(f"missing_selected:{selected}_QC")
            elif np.asarray(qc_value).shape != np.asarray(value).shape:
                issues.add(f"shape:{selected}_QC")
            else:
                flags[parameter] = np.asarray(qc_value).astype("S1")
                qc_counts[parameter].update(flag_histogram(flags[parameter]))
            unit = text(attributes.get(selected, {}).get("units", ""))
            allowed = {"PRES": ("decibar", "dbar"), "TEMP": ("degree_Celsius", "degrees_Celsius"),
                       "PSAL": ("psu", "1", "PSS-78", "0.001")}
            if unit not in allowed[parameter]:
                issues.add(f"units:{selected}:{unit}")
            for bound in ("valid_min", "valid_max"):
                if bound in attributes.get(selected, {}):
                    limit = float(attributes[selected][bound])
                    outside = values[parameter] < limit if bound == "valid_min" else values[parameter] > limit
                    if np.any(outside):
                        issues.add(f"declared_range:{selected}")
            if not np.any(np.isfinite(values[parameter])):
                issues.add(f"no_finite_selected:{parameter}")
        if len(values) != 3:
            continue
        if len({value.shape for value in values.values()}) != 1:
            issues.add("shape:paired_parameters")
            continue
        paired = np.logical_and.reduce([np.isfinite(values[parameter]) for parameter in PARAMETERS])
        result["paired_finite_points"] += int(paired.sum())
        if len(flags) != 3:
            continue
        qc1 = paired & np.logical_and.reduce([flags[parameter] == b"1" for parameter in PARAMETERS])
        qc12 = paired & np.logical_and.reduce([
            (flags[parameter] == b"1") | (flags[parameter] == b"2") for parameter in PARAMETERS
        ])
        result["paired_qc1_points"] += int(qc1.sum())
        result["paired_qc12_points"] += int(qc12.sum())
        if qc12.any():
            result["profiles_with_qc12_pairs"] += 1
            pressure = values["PRES"][qc12]
            pressure_bounds.extend([float(pressure.min()), float(pressure.max())])
            if np.any(np.diff(pressure) <= 0):
                issues.add("non_increasing_selected_pressure")
    if pressure_bounds:
        result["pressure_min_qc12_dbar"] = min(pressure_bounds)
        result["pressure_max_qc12_dbar"] = max(pressure_bounds)
    result["mode_counts"] = dict(mode_counts)
    result["modes"] = ";".join(sorted(mode_counts))
    result["qc_counts"] = {name: dict(counts) for name, counts in qc_counts.items()}
    result["issues"] = sorted(issues)
    return result


def inspect_file(task: tuple[str, dict]) -> dict:
    """Read one original file; return corruption separately from content issues."""
    root, row = task
    result = {name: "" for name in FIELDS}
    result.update(file=row["file"], readable=False, issues=[], bytes=0, qc_counts={}, mode_counts={}, profile_keys=[])
    try:
        payload = (Path(root) / row["file"]).read_bytes()
        result["bytes"] = len(payload)
        file_format, arrays, attributes, nprof = read_arrays(payload)
        result.update(format=file_format, readable=True)
    except Exception as exc:
        result.update(error=f"{type(exc).__name__}: {exc}", issues=["unreadable"])
        return result
    try:
        result.update(inspect_arrays(arrays, attributes, nprof, row))
    except Exception as exc:
        result.update(error=f"{type(exc).__name__}: {exc}", issues=["inspection_error"])
    return result


def inspect_batch(tasks: list[tuple[str, dict]]) -> list[dict]:
    """Amortize worker IPC without retaining large arrays in the parent process."""
    return [inspect_file(task) for task in tasks]


def scan_paths(root: Path) -> tuple[set[str], list[str]]:
    """Enumerate filenames once, without opening raw data."""
    files, temporary = set(), []
    for parent, _, names in os.walk(root):
        relative = Path(parent).relative_to(root)
        for name in names:
            path = (relative / name).as_posix()
            if name.endswith(".nc"):
                files.add(path)
            elif ".part" in name:
                temporary.append(path)
    return files, temporary


def main() -> None:
    """Write independent coverage, per-file and aggregate validation reports."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=INVENTORY)
    parser.add_argument("--raw", type=Path, default=RAW)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, help="Pilot only; full coverage is still reported")
    args = parser.parse_args()
    if not 1 <= args.workers <= 8 or (args.limit is not None and args.limit < 1):
        parser.error("workers 必须为 1—8；limit 必须大于 0")
    with args.inventory.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    expected = {row["file"] for row in rows}
    if len(expected) != len(rows):
        raise ValueError("冻结清单包含重复文件路径，不能直接执行")
    report = ROOT / "research/audits" / ("argo_validation_" + datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f"))
    report.mkdir(parents=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", force=True, handlers=[
        logging.FileHandler(report / "validation.log", encoding="utf-8"), logging.StreamHandler(),
    ])
    logging.info("开始只读覆盖统计：%s", args.raw)
    actual, temporary = scan_paths(args.raw)
    missing, unexpected = sorted(expected - actual), sorted(actual - expected)
    coverage = {"expected": len(expected), "actual_nc": len(actual), "missing": len(missing),
                "unexpected": len(unexpected), "temporary": len(temporary),
                "by_dac": dict(Counter(name.split("/")[0] for name in actual))}
    for filename, names in (("missing_files.csv", missing), ("unexpected_files.csv", unexpected),
                            ("temporary_files.csv", temporary)):
        with (report / filename).open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["file"])
            writer.writerows([name] for name in names)
    (report / "coverage.json").write_text(json.dumps(coverage, indent=2), encoding="utf-8")
    selected = rows[:args.limit] if args.limit else rows
    logging.info("覆盖=%s；本次读取=%d；报告=%s", coverage, len(selected), report)
    totals = Counter()
    issue_counts, mode_counts, formats = Counter(), Counter(), Counter()
    qc_counts = defaultdict(Counter)
    by_dac = defaultdict(Counter)
    by_month = defaultdict(Counter)
    duplicate_keys = {}
    seen_keys = {}
    started = last_progress = time.monotonic()
    row_lookup = {row["file"]: row for row in selected}

    def batches():
        for offset in range(0, len(selected), 32):
            yield [(str(args.raw), row) for row in selected[offset:offset + 32]]

    with (report / "files.csv").open("w", encoding="utf-8-sig", newline="") as all_handle, (
        report / "issues.csv"
    ).open("w", encoding="utf-8-sig", newline="") as issues_handle:
        writer = csv.DictWriter(all_handle, fieldnames=FIELDS, extrasaction="ignore")
        issue_writer = csv.DictWriter(issues_handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        issue_writer.writeheader()
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            for batch in pool.map(inspect_batch, batches(), chunksize=1, buffersize=args.workers * 2):
                for item in batch:
                    totals["checked"] += 1
                    totals["readable"] += int(item["readable"])
                    totals["unreadable"] += int(not item["readable"])
                    totals["files_with_issues"] += bool(item["issues"])
                    totals["files_without_issues"] += not item["issues"]
                    totals["files_with_qc12_pairs"] += int(bool(item["profiles_with_qc12_pairs"]))
                    for parameter in PARAMETERS:
                        totals[f"files_with_finite_selected_{parameter.lower()}"] += int(
                            bool(item[f"selected_{parameter.lower()}_finite_points"])
                        )
                    for key in ("bytes", "profiles", "paired_finite_points", "paired_qc1_points",
                                "paired_qc12_points", "profiles_with_qc12_pairs", "selected_pres_finite_points",
                                "selected_temp_finite_points", "selected_psal_finite_points"):
                        totals[key] += int(item.get(key) or 0)
                    issue_counts.update(item["issues"])
                    mode_counts.update(item["mode_counts"])
                    formats[item["format"]] += 1
                    for name, counts in item["qc_counts"].items():
                        qc_counts[name].update(counts)
                    row = row_lookup[item["file"]]
                    for group in (by_dac[item["file"].split("/")[0]], by_month[row["date"][:6]]):
                        group["checked"] += 1
                        group["readable"] += int(item["readable"])
                        group["with_issues"] += bool(item["issues"])
                        group["with_qc12_pairs"] += int(bool(item["profiles_with_qc12_pairs"]))
                    for key in item["profile_keys"]:
                        key = tuple(key)
                        if key in seen_keys:
                            duplicate_keys.setdefault("/".join(map(str, key)), [seen_keys[key]]).append(item["file"])
                        else:
                            seen_keys[key] = item["file"]
                    item["issues"] = ";".join(item["issues"])
                    writer.writerow(item)
                    if item["issues"]:
                        issue_writer.writerow(item)
                if time.monotonic() - last_progress >= 20:
                    elapsed = time.monotonic() - started
                    logging.info("已检查=%d/%d 可读=%d 不可读=%d 含问题=%d 速度=%.1f份/秒",
                                 totals["checked"], len(selected), totals["readable"], totals["unreadable"],
                                 totals["files_with_issues"], totals["checked"] / elapsed)
                    all_handle.flush()
                    issues_handle.flush()
                    (report / "progress.json").write_text(json.dumps(dict(totals)), encoding="utf-8")
                    last_progress = time.monotonic()
    summary = {
        "inventory": str(args.inventory.resolve()), "raw": str(args.raw.resolve()), "report": str(report),
        "full_scan": args.limit is None, "coverage": coverage, "totals": dict(totals),
        "formats": dict(formats), "issue_counts": dict(issue_counts), "data_modes": dict(mode_counts),
        "qc_counts": {name: dict(counts) for name, counts in qc_counts.items()},
        "by_dac": dict(by_dac), "by_month": dict(by_month), "duplicate_profile_keys": duplicate_keys,
        "elapsed_seconds": round(time.monotonic() - started, 1),
        "scope": "read-only single-pass all-root-variable decoding; no hash, repair, filtering or depth interpolation",
        "limitations": ["QC1/QC12 paired counts exclude fill/nonfinite values but do not enforce time/position QC or error bounds",
                        "QC histograms include padded/missing levels; pressure is dbar, not depth in metres",
                        "DATE_UPDATE differences are version information, not proof of corruption",
                        "No remote-byte or archive-byte equivalence is claimed"],
        "qc_reference": "https://argo.ucsd.edu/data/how-to-use-argo-files/",
    }
    (report / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    logging.info("完成：%s；报告=%s", dict(totals), report)


if __name__ == "__main__":
    main()
