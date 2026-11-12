# DUACS ADT 批量下载

脚本：`F:\AAAzxz\SRTP_M\data_dl\download_adt.py`

固定数据集为 `cmems_obs-sl_glo_phy-ssh_my_allsat-l4-duacs-0.125deg_P1D`，版本 `202411`，仅下载逐日 `adt`，每月 west/east 各一个 NetCDF。使用已经执行 `copernicusmarine login` 保存的本机凭据，无需将账号密码写入代码。

## 运行

在 PowerShell 中执行，先下载一个月：

```powershell
Set-Location 'F:\AAAzxz\SRTP_M\data_dl'
& '.\.venv-data\Scripts\python.exe' '.\download_adt.py' --start 200501 --end 200501
```

成功后按年下载，例如 2005 年（已完成的 1 月会校验后跳过）：

```powershell
& '.\.venv-data\Scripts\python.exe' '.\download_adt.py' --start 200501 --end 200512
```

也可以用一个进程按时间顺序下载整个项目范围：

```powershell
& '.\.venv-data\Scripts\python.exe' '.\download_adt.py' --start 200411 --end 202506
```

共 248 个月、496 份文件。程序先完成 2005—2020 年训练侧，再经过 2020-12 隔离月，最后下载 2021 年以后的验证、测试数据；下载不涉及模型指标或拟合。

其他用法：

```powershell
# 只列出计划，不联网或写入文件
& '.\.venv-data\Scripts\python.exe' '.\download_adt.py' --start 200501 --end 200512 --plan

# 仅检查已经下载的文件；遇到缺失或不合格文件时停止
& '.\.venv-data\Scripts\python.exe' '.\download_adt.py' --start 200411 --end 200412 --check-only
```

## 文件和断点重跑

- 新文件保存到 `F:\AAAzxz\SRTP_M\data_dl\data\raw\adt\`。
- 原来 `F:\AAAzxz\SRTP_M\data_dl\data\raw\dat\` 中同名文件也会接受校验，合格后复用，不移动或重复下载。最终清点时应同时清点这两个目录。
- 检查版本、产品、adt 单位、完整逐日时间轴、0.125° 网格，以及每天存在有效 ADT；每个合格文件记录 SHA-256。
- 临时文件名为 `adt_YYYYMM_west.part.nc` 或 `adt_YYYYMM_east.part.nc`，校验成功后才改成正式文件名。
- 中断或失败后，重跑同一条命令。完整文件会复用，完整临时文件会验收；不完整临时文件保留为带时间戳的文件，再重新下载该月该块。不是字节级续传。
- 已有正式文件如不合格，程序停止，不覆盖原文件。失败只记录目标和异常类型，不输出凭据或异常正文中的签名 URL。
- 日志在 `F:\AAAzxz\SRTP_M\data_dl\logs\download\`，UTF-8 编码。
- 同一时间只运行一个 ADT 下载进程，不同时启动多个年份任务。

## strict-inside 的边界

官网示例采用 `strict-inside`，但该选项要求请求边界位于实际坐标中心范围内。数据最外侧经度中心为 ±179.9375°，直接填 ±180° 的试请求触发 `CoordinatesOutOfDatasetBounds`。

脚本使用西块 120.0625—179.9375°、东块 −179.9375—−80.0625°，纬度 −19.9375—19.9375°。这与指定研究区内的网格中心、已经验收的四份文件一致，不改变所需网格。

参数依据：[官方 Python subset 说明](https://help.marine.copernicus.eu/en/articles/8283072-copernicus-marine-toolbox-api-subset)，以及本机 Toolbox 2.5.1 的函数签名。

## 本次验证范围

已通过：现有 2004-11/12 四份文件完整校验；月份边界和闰年检查；临时文件转正、完整文件复用与中断文件恢复的本地模拟；2005-01 west/east 官方 `dry_run` 请求。

2026-11-11 实际下载验证：Toolbox 生成的文件使用 `product_version=vNov2024`，未包含网页下载文件的 `subset:*` 属性。已修正校验以支持两种元数据格式；错误或缺失的版本仍会被拒绝。2005-01 west 临时文件已复用并转正，east 已实际下载并通过校验，两份均覆盖完整 31 天。

尚未下载：2005-02 至 2025-06。
