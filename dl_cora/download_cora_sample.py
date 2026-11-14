"""下载固定202603版本的2018年1月CORA温盐原始场小样本。"""

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "data" / "raw" / "cora" / "original_202603" / "201801"
DATASET_ID = "cmems_obs-ins_glo_phy-temp-sal_my_cora-oa_P1M"
VERSION = "202603"
SOURCE_URL = (
    "https://s3.waw3-1.cloudferro.com/mdl-native-03/native/"
    "INSITU_GLO_PHY_TS_OA_MY_013_052/"
    f"{DATASET_ID}_{VERSION}/field/2018"
)
# 文件名和大小来自该固定版本官方对象存储的2018年目录。
FILES = {
    "OA_CORA5.2_20180115_fld_PSAL.nc": 62_201_077,
    "OA_CORA5.2_20180115_fld_TEMP.nc": 91_493_738,
}


def sha256_file(path: Path) -> str:
    """记录落盘文件校验和，便于后续交接。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_file(name: str, expected_size: int) -> dict:
    """单并发流式下载，大小核对后改为正式文件名。"""
    target = OUTPUT_DIR / name
    url = f"{SOURCE_URL}/{name}"
    etag = None
    if target.exists():
        if target.stat().st_size != expected_size:
            raise ValueError(f"已有文件大小不符，请单独检查：{target}")
        print(f"Existing: {name}", flush=True)
    else:
        partial = target.with_suffix(".nc.part")
        received = 0
        last_update = time.monotonic()
        with requests.get(url, stream=True, timeout=(20, 90)) as response:
            response.raise_for_status()
            etag = response.headers.get("ETag")
            with partial.open("xb") as stream:
                for chunk in response.iter_content(1024 * 1024):
                    if not chunk:
                        continue
                    stream.write(chunk)
                    received += len(chunk)
                    if time.monotonic() - last_update >= 10:
                        print(f"{name}: {received / 1024**2:.1f}/{expected_size / 1024**2:.1f} MiB", flush=True)
                        last_update = time.monotonic()
        if received != expected_size:
            raise ValueError(f"下载大小不符：{name}，实际{received}，预期{expected_size}")
        partial.rename(target)
        print(f"Downloaded: {name} ({received} bytes)", flush=True)
    return {
        "file": name,
        "source_url": url,
        "size_bytes": target.stat().st_size,
        "sha256": sha256_file(target),
        "etag": etag,
    }


def main() -> None:
    """仅获取一个月两份原始fld，不进行插值、裁剪或温盐转换。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    records = [download_file(name, size) for name, size in FILES.items()]
    manifest = {
        "dataset_id": DATASET_ID,
        "dataset_version": VERSION,
        "sample_month": "2018-01",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "processing": "Original global fld files; no regridding, cropping or variable conversion.",
        "files": records,
    }
    manifest_path = OUTPUT_DIR / "download_manifest.json"
    if manifest_path.exists():
        print(f"Manifest already exists: {manifest_path}", flush=True)
    else:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Complete: {OUTPUT_DIR}", flush=True)


if __name__ == "__main__":
    main()
