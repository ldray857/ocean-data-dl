"""下载 NOAA OISST v2.1 AVHRR 全球逐日原始文件，按月存放。"""

import argparse
import calendar
import hashlib
import logging
import shutil
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np
import xarray as xr

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "data" / "raw" / "oisst"
SOURCE_URLS = {
    "google": (
        "https://storage.googleapis.com/noaa-cdr-sea-surface-temp-optimum-interpolation"
        "/data/v2.1/avhrr"
    ),
    "ncei": "https://www.ncei.noaa.gov/data/sea-surface-temperature-optimum-interpolation/v2.1/access/avhrr",
    "aws": (
        "https://noaa-cdr-sea-surface-temp-optimum-interpolation-pds"
        ".s3.us-east-1.amazonaws.com/data/v2.1/avhrr"
    ),
}


class FileValidationError(ValueError):
    """原始文件不符合项目要求。"""


def day_list(start: str, end: str) -> list[date]:
    """生成项目范围内、首尾月份均完整包含的日期序列。"""
    for value in (start, end):
        if len(value) != 6 or not value.isdigit():
            raise ValueError("月份必须为 YYYYMM 格式")
        datetime.strptime(value, "%Y%m")
    if not "200411" <= start <= end <= "202506":
        raise ValueError("时间范围必须在 200411—202506 内，且起月不晚于止月")
    first = date(int(start[:4]), int(start[4:]), 1)
    year, month = int(end[:4]), int(end[4:])
    last = date(year, month, calendar.monthrange(year, month)[1])
    return [first + timedelta(days=offset) for offset in range((last - first).days + 1)]


def filename_for(day: date) -> str:
    """返回 NOAA 最终版日文件的原始名称。"""
    return f"oisst-avhrr-v02r01.{day:%Y%m%d}.nc"


def sha256_file(path: Path) -> str:
    """计算原始文件的 SHA-256。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_file(path: Path, day: date) -> None:
    """核验产品、日期、全球网格、所需变量和研究区有效数据。"""
    with xr.open_dataset(path, engine="h5netcdf") as ds:
        if ds.attrs.get("product_version") != "Version v02r01":
            raise FileValidationError("文件版本不是 OISST v2.1")
        title = str(ds.attrs.get("title", ""))
        if "Optimum Interpolation Sea Surface Temperature" not in title or not title.endswith(" - Final"):
            raise FileValidationError("文件缺少 OISST 最终版标识")
        if ds.attrs.get("id") != filename_for(day):
            raise FileValidationError("文件产品标识或日期不符")
        if ds.sizes.get("time") != 1 or ds.sizes.get("zlev") != 1:
            raise FileValidationError("time/zlev 维度不符")
        if ds.time.values.astype("datetime64[D]")[0] != np.datetime64(day):
            raise FileValidationError("文件时间与目标日期不符")
        if not np.array_equal(ds.zlev.values, [0]):
            raise FileValidationError("不是海表数据")
        for name, expected in (
            ("lat", np.arange(-89.875, 90, 0.25)),
            ("lon", np.arange(0.125, 360, 0.25)),
        ):
            if name not in ds.coords or not np.array_equal(ds[name].values, expected):
                raise FileValidationError(f"{name} 不是完整的全球 0.25 度网格")
        for name, units in (("sst", "Celsius"), ("err", "Celsius"), ("ice", "%")):
            if name not in ds or ds[name].dims != ("time", "zlev", "lat", "lon"):
                raise FileValidationError(f"缺少 {name} 或维度不符")
            if ds[name].attrs.get("units") != units:
                raise FileValidationError(f"{name} 单位不符")
        # 读取所有变量，检查压缩数据块能否完整解码；不改写原文件。
        ds.load()
        region = ds.sel(lat=slice(-20, 20), lon=slice(120, 280))
        for name in ("sst", "err"):
            if not np.isfinite(region[name].values).any():
                raise FileValidationError(f"研究区 {name} 全部缺失")
        # 热带无海冰区域的 ice 可为缺失，不要求它全区有值。


def fetch_file(url: str, partial: Path, logger: logging.Logger) -> None:
    """串行下载；网络错误最多尝试三次，每次重新获取该日完整文件。"""
    for attempt in range(1, 4):
        try:
            request = Request(url, headers={"User-Agent": "SRTP-OISST-downloader/1.0"})
            with urlopen(request, timeout=60) as response, partial.open("wb") as stream:
                expected_size = response.headers.get("Content-Length")
                shutil.copyfileobj(response, stream, length=1024 * 1024)
            if expected_size is not None and partial.stat().st_size != int(expected_size):
                raise OSError("下载字节数与 Content-Length 不一致")
            return
        except (URLError, OSError) as exc:
            status = exc.code if isinstance(exc, HTTPError) else None
            logger.warning("下载尝试=%s 异常类型=%s HTTP=%s", attempt, type(exc).__name__, status)
            if attempt == 3 or (status is not None and status < 500 and status not in (408, 429)):
                raise
            time.sleep(attempt * 2)


def download_day(
    day: date,
    logger: logging.Logger,
    check_only: bool,
    source: str = "ncei",
    fallback_source: str | None = None,
) -> bool:
    """复用合格日文件；新文件经校验后才从 .part 转为正式名称。"""
    target = OUTPUT_DIR / f"{day:%Y%m}" / filename_for(day)
    if target.exists():
        validate_file(target, day)
        logger.info("复用 %s bytes=%s sha256=%s", target, target.stat().st_size, sha256_file(target))
        return False
    if check_only:
        raise FileNotFoundError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".nc.part")
    if partial.exists():
        try:
            validate_file(partial, day)
        except (OSError, ValueError, KeyError):
            logger.info("重新下载未完成的临时文件 %s", partial.name)
        else:
            partial.rename(target)
            logger.info("恢复 %s bytes=%s sha256=%s", target, target.stat().st_size, sha256_file(target))
            return True
    logger.info("开始下载 %s source=%s", target.name, source)
    actual_source = source
    try:
        fetch_file(f"{SOURCE_URLS[source]}/{day:%Y%m}/{target.name}", partial, logger)
    except HTTPError as exc:
        if exc.code != 404 or fallback_source is None or fallback_source == source:
            raise
        actual_source = fallback_source
        logger.warning("源文件不存在 日期=%s source=%s HTTP=404；改用 source=%s", day, source, actual_source)
        fetch_file(f"{SOURCE_URLS[actual_source]}/{day:%Y%m}/{target.name}", partial, logger)
    validate_file(partial, day)
    partial.rename(target)
    logger.info(
        "下载完成 %s bytes=%s sha256=%s source=%s",
        target, target.stat().st_size, sha256_file(target), actual_source,
    )
    return True


def main() -> int:
    """按日期顺序下载，首个失败目标出现后停止，保留现场供重跑。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="200411", help="起始月份 YYYYMM，默认 200411")
    parser.add_argument("--end", default="202506", help="结束月份 YYYYMM，默认 202506")
    parser.add_argument("--source", choices=SOURCE_URLS, default="ncei", help="下载源，默认 ncei；推荐显式选择 google")
    parser.add_argument("--fallback-source", choices=SOURCE_URLS, help="主源返回 404 时使用的同产品备用源，默认不切源")
    parser.add_argument("--plan", action="store_true", help="仅打印计划，不联网、不写文件")
    parser.add_argument("--check-only", action="store_true", help="仅校验本地文件，不下载")
    args = parser.parse_args()
    try:
        days = day_list(args.start, args.end)
    except ValueError as exc:
        parser.error(str(exc))
    if args.plan:
        print("产品：NOAA OISST v2.1 AVHRR 最终版，全球 0.25 度逐日原始 NetCDF")
        print(f"下载源：{args.source}，地址：{SOURCE_URLS[args.source]}")
        print(f"404 备用源：{args.fallback_source or '无'}")
        print(f"时间：{days[0]}—{days[-1]}，共 {len(days)} 份；目录：{OUTPUT_DIR}")
        return 0

    log_dir = BASE_DIR / "logs" / "download"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"oisst_{args.source}_{args.start}_{args.end}_{datetime.now():%Y%m%d_%H%M%S_%f}.log"
    logger = logging.getLogger("oisst_download")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    formatter = logging.Formatter("%(asctime)s %(message)s")
    for handler in (logging.StreamHandler(), logging.FileHandler(log_path, encoding="utf-8")):
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.info(
        "范围=%s—%s source=%s fallback_source=%s 预期文件数=%s check_only=%s",
        args.start, args.end, args.source, args.fallback_source, len(days), args.check_only,
    )
    downloaded = reused = 0
    for index, day in enumerate(days, start=1):
        try:
            logger.info("进度=%s/%s 日期=%s", index, len(days), day)
            if download_day(day, logger, args.check_only, args.source, args.fallback_source):
                downloaded += 1
            else:
                reused += 1
        except KeyboardInterrupt:
            logger.info("已中断；重跑相同命令可复用已完成文件，未完成日文件会重新下载。")
            return 130
        except Exception as exc:
            logger.error("失败日期=%s 异常类型=%s", day, type(exc).__name__)
            if isinstance(exc, FileValidationError):
                logger.error("校验原因：%s", exc)
            if isinstance(exc, FileNotFoundError):
                logger.error("本地缺少目标日文件")
            logger.error("下载/恢复=%s 复用=%s；停止，排查后重跑相同命令。日志：%s", downloaded, reused, log_path)
            return 1
    logger.info("批次完成：下载/恢复=%s，复用=%s，合计=%s。日志：%s", downloaded, reused, len(days), log_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
