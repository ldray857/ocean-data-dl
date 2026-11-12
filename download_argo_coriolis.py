"""Download only the frozen missing Core-Argo files from the Coriolis DAC.

Existing nonempty files are skipped by path. No NetCDF parsing, QC filtering,
depth selection, or hash calculation is performed. Resume is file-level:
an unfinished .part file is downloaded again on the next attempt.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent
DEFAULT_MANIFEST = ROOT / "research/audits/argo_fast_20261112_120214/missing_files.csv"
DEFAULT_OUTPUT = ROOT / "data/raw/argo"
BASE_URL = "https://data-argo.ifremer.fr/dac/"
FILE_PATTERN = re.compile(r"coriolis/(\d+)/profiles/[RD]\1_\d+D?\.nc")
THREAD_LOCAL = threading.local()


@dataclass
class DownloadResult:
    """One transfer outcome, without scientific content validation."""

    file: str
    status: str
    bytes: int = 0
    attempts: int = 0
    error: str = ""


def read_manifest(path: Path) -> list[str]:
    """Read unique, relative Coriolis Core-profile paths from a CSV manifest."""
    files = []
    seen = set()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            name = row["file"].strip()
            if not FILE_PATTERN.fullmatch(name):
                raise ValueError(f"清单路径不是 Coriolis Core 单剖面：{name!r}")
            if name not in seen:
                seen.add(name)
                files.append(name)
    return files


def get_session() -> requests.Session:
    """Reuse one HTTP session per worker; keep normal TLS and proxy settings."""
    if not hasattr(THREAD_LOCAL, "session"):
        session = requests.Session()
        session.headers.update({"Accept-Encoding": "identity", "User-Agent": "Argo-Core-subset/1.0"})
        THREAD_LOCAL.session = session
    return THREAD_LOCAL.session


def download_file(
    name: str,
    output: Path,
    stop: threading.Event,
    *,
    base_url: str = BASE_URL,
    attempts: int = 3,
    timeout: float = 30,
) -> DownloadResult:
    """Stream one file to .part and publish it only after a complete transfer."""
    target = output / name
    if target.exists():
        if target.is_file() and target.stat().st_size > 0:
            return DownloadResult(name, "skipped")
        return DownloadResult(name, "failed", error="目标已存在但为空或不是普通文件；未覆盖")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    session = get_session()
    last_error = ""

    for attempt in range(1, attempts + 1):
        if stop.is_set():
            return DownloadResult(name, "cancelled", attempts=attempt - 1)
        try:
            with session.get(base_url.rstrip("/") + "/" + name, stream=True, timeout=(10, timeout)) as response:
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError(f"不完整的 HTTP 响应状态：{response.status_code}")
                content_type = response.headers.get("Content-Type", "").lower()
                if content_type.startswith("text/") or "json" in content_type:
                    raise ValueError(f"服务器返回错误页面而非数据文件：{content_type}")
                received = 0
                with partial.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=128 * 1024):
                        if stop.is_set():
                            return DownloadResult(name, "cancelled", attempts=attempt)
                        handle.write(chunk)
                        received += len(chunk)
                # These are transfer checks only; the NetCDF content is not opened.
                expected = response.headers.get("Content-Length")
                if received == 0:
                    raise ValueError("服务器返回空文件")
                if expected and not response.headers.get("Content-Encoding") and received != int(expected):
                    raise requests.ConnectionError(f"传输不完整：{received}/{expected} 字节")
            if stop.is_set():
                return DownloadResult(name, "cancelled", attempts=attempt)
            if target.exists():
                return DownloadResult(name, "failed", attempts=attempt, error="下载期间目标已出现；未覆盖")
            # On Windows rename refuses an existing destination.
            partial.rename(target)
            return DownloadResult(name, "downloaded", bytes=received, attempts=attempt)
        except requests.HTTPError as exc:
            status = exc.response.status_code
            last_error = f"HTTP {status}"
            if status != 429 and status < 500:
                break
        except requests.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        except (OSError, ValueError) as exc:
            return DownloadResult(name, "failed", attempts=attempt, error=f"{type(exc).__name__}: {exc}")
        if attempt < attempts and stop.wait(min(2 ** (attempt - 1), 8)):
            return DownloadResult(name, "cancelled", attempts=attempt)
    return DownloadResult(name, "failed", attempts=attempt, error=last_error)


def positive_int(value: str) -> int:
    """Parse a positive CLI integer."""
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError("必须大于 0")
    return result


def main() -> int:
    """Run the explicitly requested download and save per-file outcomes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST, help="含 file 列的缺失清单")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Argo 根目录，下面自动建立 coriolis")
    parser.add_argument("--workers", type=positive_int, default=4, help="并发连接数，默认 4，最多 8")
    parser.add_argument("--limit", type=positive_int, help="最多下载多少个尚未落盘的文件，用于小批量运行")
    parser.add_argument("--attempts", type=positive_int, default=3, help="每文件最大尝试次数，默认 3")
    parser.add_argument("--timeout", type=positive_int, default=30, help="单次读取超时秒数，默认 30")
    parser.add_argument("--dry-run", action="store_true", help="仅显示清单数量与路径，不联网、不写文件")
    args = parser.parse_args()
    if args.workers > 8:
        parser.error("--workers 最大为 8")
    names = read_manifest(args.manifest)
    output = args.output.resolve()
    existing = [name for name in names if (output / name).is_file() and (output / name).stat().st_size > 0]
    existing_set = set(existing)
    pending_names = [name for name in names if name not in existing_set]
    selected = pending_names[:args.limit] if args.limit else pending_names
    print(f"清单={len(names)} 已有={len(existing)} 未完成={len(pending_names)} 本次计划={len(selected)}", flush=True)
    print(f"保存位置：{output / 'coriolis'}", flush=True)
    if args.dry_run:
        print("仅预览，未联网、未下载。", flush=True)
        return 0

    stamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d_%H%M%S_%f")
    report = ROOT / "logs/download" / f"argo_coriolis_{stamp}"
    report.mkdir(parents=True)
    logging.basicConfig(
        level=logging.INFO,
        force=True,
        format="%(asctime)s %(message)s",
        handlers=[logging.FileHandler(report / "download.log", encoding="utf-8"), logging.StreamHandler()],
    )
    logging.info("开始：本次计划 %d；日志：%s", len(selected), report)
    stop = threading.Event()
    counts = {"downloaded": 0, "skipped": 0, "failed": 0, "cancelled": 0}
    started = time.monotonic()
    last_progress = started
    iterator = iter(selected)
    interrupted = False
    pool = ThreadPoolExecutor(max_workers=args.workers)
    pending = {}
    with (report / "results.csv").open("w", encoding="utf-8-sig", newline="") as result_handle, (
        report / "failed_files.csv"
    ).open("w", encoding="utf-8-sig", newline="") as failed_handle:
        writer = csv.DictWriter(result_handle, fieldnames=list(DownloadResult.__dataclass_fields__))
        failed_writer = csv.DictWriter(failed_handle, fieldnames=["file", "error"])
        writer.writeheader()
        failed_writer.writeheader()

        def fill_queue() -> None:
            while len(pending) < args.workers * 2 and not stop.is_set():
                name = next(iterator, None)
                if name is None:
                    break
                future = pool.submit(
                    download_file, name, output, stop, attempts=args.attempts, timeout=args.timeout
                )
                pending[future] = name

        try:
            fill_queue()
            while pending:
                try:
                    done, _ = wait(pending, timeout=1, return_when=FIRST_COMPLETED)
                except KeyboardInterrupt:
                    interrupted = True
                    stop.set()
                    logging.info("收到暂停请求；等待当前连接退出，保留已完成文件。")
                    continue
                for future in done:
                    name = pending.pop(future)
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = DownloadResult(name, "failed", error=f"{type(exc).__name__}: {exc}")
                    counts[result.status] += 1
                    writer.writerow(asdict(result))
                    if result.status == "failed":
                        failed_writer.writerow({"file": result.file, "error": result.error})
                        failed_handle.flush()
                        logging.warning("失败 %s：%s", result.file, result.error)
                if done:
                    result_handle.flush()
                if time.monotonic() - last_progress >= 10 or not pending:
                    logging.info(
                        "本次完成=%d/%d 下载=%d 失败=%d",
                        sum(counts.values()), len(selected), counts["downloaded"], counts["failed"],
                    )
                    last_progress = time.monotonic()
                fill_queue()
        except KeyboardInterrupt:
            interrupted = True
            stop.set()
        finally:
            pool.shutdown(wait=True, cancel_futures=True)

    summary = {
        "manifest": str(args.manifest.resolve()), "output": str(output), "source": BASE_URL,
        "manifest_files": len(names), "existing_before": len(existing), "selected": len(selected),
        "results": counts, "interrupted": interrupted,
        "remaining_not_confirmed_complete": len(pending_names) - counts["downloaded"] - counts["skipped"],
        "elapsed_seconds": round(time.monotonic() - started, 1),
        "scope": "download only; no NetCDF, field, QC or hash validation",
    }
    (report / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    logging.info("结束：下载=%d 已有=%d 失败=%d；报告：%s", counts["downloaded"], len(existing), counts["failed"], report)
    return 130 if interrupted else (1 if counts["failed"] else 0)


if __name__ == "__main__":
    raise SystemExit(main())
