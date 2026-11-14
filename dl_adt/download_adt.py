"""按月下载 DUACS 逐日 ADT；使用 copernicusmarine login 保存的本机凭据。"""

import argparse
import calendar
import hashlib
import logging
from datetime import datetime
from pathlib import Path

import copernicusmarine
import numpy as np
import xarray as xr

BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "data" / "raw" / "adt"
LEGACY_DIR = BASE_DIR / "data" / "raw" / "dat"
DATASET_ID = "cmems_obs-sl_glo_phy-ssh_my_allsat-l4-duacs-0.125deg_P1D"
VERSION = "202411"
BLOCKS = {"west": (120, 180), "east": (-180, -80)}


class FileValidationError(ValueError):
    """本地数据校验失败，可安全显示原因。"""


def month_list(start: str, end: str) -> list[str]:
    """生成项目允许范围内的连续月份。"""
    for value in (start, end):
        if len(value) != 6 or not value.isdigit():
            raise ValueError("月份必须为 YYYYMM 格式")
        datetime.strptime(value, "%Y%m")
    if not "200411" <= start <= end <= "202506":
        raise ValueError("时间范围必须在 200411—202506 内，且起月不晚于止月")
    result = []
    year, month = int(start[:4]), int(start[4:])
    while f"{year:04d}{month:02d}" <= end:
        result.append(f"{year:04d}{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return result


def request_parameters(month: str, block: str) -> dict:
    """沿用官网参数，固定版本、空间范围及自然月。"""
    year, number = int(month[:4]), int(month[4:])
    last_day = calendar.monthrange(year, number)[1]
    west, east = BLOCKS[block]
    return {
        "dataset_id": DATASET_ID,
        "dataset_version": VERSION,
        "variables": ["adt"],
        # strict-inside 检查的是坐标中心范围；±180 超出最外侧中心。
        "minimum_longitude": west + 0.0625,
        "maximum_longitude": east - 0.0625,
        "minimum_latitude": -19.9375,
        "maximum_latitude": 19.9375,
        "start_datetime": f"{year:04d}-{number:02d}-01T00:00:00",
        "end_datetime": f"{year:04d}-{number:02d}-{last_day:02d}T00:00:00",
        "coordinates_selection_method": "strict-inside",
        "netcdf_compression_level": 1,
        "disable_progress_bar": True,
        "file_format": "netcdf",
    }


def validate_file(path: Path, month: str, block: str) -> None:
    """检查版本、逐日时间轴、完整网格及每天的有效 ADT。"""
    year, number = int(month[:4]), int(month[4:])
    days = calendar.monthrange(year, number)[1]
    expected_time = np.datetime64(f"{year:04d}-{number:02d}-01") + np.arange(days)
    west, east = BLOCKS[block]
    with xr.open_dataset(path, engine="h5netcdf") as ds:
        # 网页下载标注 subset:*，Toolbox 2.5.1 保留源产品的版本与标题。
        dataset = ds.attrs.get("subset:datasetId")
        if dataset is not None:
            if dataset != f"{DATASET_ID}_{VERSION}":
                raise FileValidationError("文件的数据集或版本不符合要求")
        elif ds.attrs.get("product_version") != "vNov2024":
            raise FileValidationError("文件缺少可确认的 vNov2024 版本信息")
        product = ds.attrs.get("subset:productId")
        if product is not None:
            if product != "SEALEVEL_GLO_PHY_L4_MY_008_047":
                raise FileValidationError("文件产品不符合要求")
        elif ds.attrs.get("title") != (
            "DT merged all satellites Global Ocean Gridded SSALTO/DUACS "
            "Sea Surface Height L4 product and derived variables"
        ):
            raise FileValidationError("文件缺少可确认的 DUACS MY 产品信息")
        if "adt" not in ds or ds.adt.attrs.get("units") != "m":
            raise FileValidationError("缺少以 m 为单位的 adt")
        if ds.adt.dims != ("time", "latitude", "longitude"):
            raise FileValidationError("adt 维度不符合要求")
        if not np.array_equal(ds.time.values, expected_time.astype("datetime64[ns]")):
            raise FileValidationError("逐日时间轴存在缺失、重复或日期不符")
        for name, expected in (
            ("latitude", np.arange(-20 + 0.0625, 20, 0.125)),
            ("longitude", np.arange(west + 0.0625, east, 0.125)),
        ):
            values = ds[name].values
            if values.shape != expected.shape or not np.allclose(values, expected, rtol=0, atol=1e-6):
                raise FileValidationError(f"{name} 网格不符合要求")
        if not np.isfinite(ds.adt.values).any(axis=(1, 2)).all():
            raise FileValidationError("至少一天的 adt 全部缺失")


def sha256_file(path: Path) -> str:
    """计算原始文件校验和。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_file(month: str, block: str, logger: logging.Logger, check_only: bool) -> bool:
    """复用合格文件，或下载到临时文件，校验后才改为正式名称。"""
    filename = f"adt_{month}_{block}.nc"
    target = OUTPUT_DIR / filename
    # 兼容此前手动下载的 dat 目录，不移动或覆盖原文件。
    existing = target if target.exists() else LEGACY_DIR / filename
    if existing.exists():
        validate_file(existing, month, block)
        logger.info("已校验并复用 %s bytes=%s sha256=%s", existing, existing.stat().st_size, sha256_file(existing))
        return False
    if check_only:
        raise FileNotFoundError(filename)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    partial = OUTPUT_DIR / f"adt_{month}_{block}.part.nc"
    if partial.exists():
        try:
            validate_file(partial, month, block)
        except (OSError, ValueError, KeyError):
            # 保留中断文件，重新请求完整月文件，不尝试字节级续传。
            saved = partial.with_name(f"{partial.stem}.{datetime.now():%Y%m%d_%H%M%S_%f}.nc")
            partial.rename(saved)
            logger.info("保留未完成文件 %s", saved)
        else:
            partial.rename(target)
            logger.info("已恢复 %s bytes=%s sha256=%s", target, target.stat().st_size, sha256_file(target))
            return True

    logger.info("开始下载 %s version=%s", filename, VERSION)
    copernicusmarine.subset(
        **request_parameters(month, block),
        output_directory=OUTPUT_DIR,
        output_filename=partial.name,
    )
    validate_file(partial, month, block)
    partial.rename(target)
    logger.info("下载并校验完成 %s bytes=%s sha256=%s", target, target.stat().st_size, sha256_file(target))
    return True


def main() -> int:
    """按时间顺序串行下载，首个失败目标出现后停止，便于重跑。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="200501", help="起始月份 YYYYMM，默认 200501")
    parser.add_argument("--end", default="202506", help="结束月份 YYYYMM，默认 202506")
    parser.add_argument("--plan", action="store_true", help="仅列出请求范围，不联网或写入文件")
    parser.add_argument("--check-only", action="store_true", help="仅校验本地文件，不下载")
    args = parser.parse_args()
    try:
        months = month_list(args.start, args.end)
    except ValueError as exc:
        parser.error(str(exc))
    if args.plan:
        print(f"固定数据集：{DATASET_ID}，版本：{VERSION}")
        for month in months:
            print(f"{month}: west + east，逐日 adt")
        print(f"共 {len(months)} 个月，{len(months) * 2} 个文件；新文件目录：{OUTPUT_DIR}")
        return 0

    log_dir = BASE_DIR / "logs" / "download"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"adt_{args.start}_{args.end}_{datetime.now():%Y%m%d_%H%M%S_%f}.log"
    logger = logging.getLogger("adt_download")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    formatter = logging.Formatter("%(asctime)s %(message)s")
    for handler in (logging.StreamHandler(), logging.FileHandler(log_path, encoding="utf-8")):
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    # 只记录本脚本的目标与异常类型，不记录库异常正文、签名 URL 或凭据。
    logging.getLogger("copernicusmarine").setLevel(logging.CRITICAL)
    logger.info("范围=%s—%s version=%s 预期文件数=%s", args.start, args.end, VERSION, len(months) * 2)
    downloaded = reused = 0
    for month in months:
        for block in BLOCKS:
            try:
                if download_file(month, block, logger, args.check_only):
                    downloaded += 1
                else:
                    reused += 1
            except KeyboardInterrupt:
                logger.info("已中断，重跑相同命令即可继续；临时文件保留。")
                return 130
            except Exception as exc:
                logger.error("失败目标=%s_%s 异常类型=%s", month, block, type(exc).__name__)
                if isinstance(exc, FileValidationError):
                    logger.error("校验原因：%s", exc)
                logger.error("已完成=%s 已复用=%s；排查后重跑相同命令。日志：%s", downloaded, reused, log_path)
                return 1
    logger.info("批次完成：下载/恢复=%s，复用=%s，合计=%s。日志：%s", downloaded, reused, downloaded + reused, log_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
