# OISST 下载说明

## 明天继续下载

当前推荐使用 Google Cloud，并在主源返回 404 时使用 AWS 同版本镜像。Google 镜像有缺月，续传时需要同时指定 `--source google --fallback-source aws`。

如果原下载任务仍在运行，就让它继续，不要重复启动。如果已经停止、退出或电脑已重启，可在 PowerShell 运行：

```powershell
& 'F:\AAAzxz\SRTP_M\data_dl\.venv-data\Scripts\python.exe' 'F:\AAAzxz\SRTP_M\data_dl\dl_oisst\download_oisst.py' --source google --fallback-source aws --start 201011 --end 202506
```

- 此命令可重复使用：已有正式文件先校验再复用，只下载缺失日期；不完整的 `.nc.part` 会重新完整下载。
- `201011` 是本次恢复下载的起始月份，不是明天的实时断点。如果明天已经下载到更晚月份，可以把 `--start` 改成最新日志中尚未完成日期所在的月份，以减少重新校验的等待；不确定时保留 `201011` 即可，不要跳过缺失月份。
- 输出仍是 `F:\AAAzxz\SRTP_M\data_dl\data\raw\oisst\YYYYMM\`。
- 日志在 `F:\AAAzxz\SRTP_M\data_dl\logs\download\`，按修改时间查看最新的 `oisst_google_*.log`。日志中出现“批次完成”才表示该批次结束；失败时记录停止日期和原因。
- 更详细的来源与后台运行说明见同目录的 `OISST谷歌源下载说明.md`。

下面保留 NOAA NCEI 原站下载方法，命令显式指定 `--source ncei`。如果省略 `--source`，脚本默认仍使用 NCEI 原站。

## 产品与范围

- 产品：NOAA OISST v2.1 AVHRR 最终版（`v02r01`），全球 0.25° 逐日 NetCDF。
- 时间：2004-11-01—2025-06-30，共 7,547 天。2004 年 11、12 月为历史输入缓冲月。
- 文件：`oisst-avhrr-v02r01.YYYYMMDD.nc`，每天一份，保留官方原始文件全部内容，包括 `sst`、`err`、`ice` 和 `anom`。
- 输出：`F:\AAAzxz\SRTP_M\data_dl\data\raw\oisst\YYYYMM\`。
- 原始文件为全球数据；本脚本不裁剪、不计算月平均。后续预处理再提取 20°S—20°N、120—280°E。
- 无需账号、令牌或额外安装依赖，使用已有的 `.venv-data` 环境。
- 官方入口：https://www.ncei.noaa.gov/products/optimum-interpolation-sst
- 下载根目录：https://www.ncei.noaa.gov/data/sea-surface-temperature-optimum-interpolation/v2.1/access/avhrr/

## 执行命令

在 PowerShell 中进入工作目录：

```powershell
Set-Location 'F:\AAAzxz\SRTP_M\data_dl'
```

查看全期计划（不联网、不写文件）：

```powershell
& '.\.venv-data\Scripts\python.exe' '.\dl_oisst\download_oisst.py' --source ncei --start 200411 --end 202506 --plan
```

试下载第一个月（30 份，已有合格文件会复用）：

```powershell
& '.\.venv-data\Scripts\python.exe' '.\dl_oisst\download_oisst.py' --source ncei --start 200411 --end 200411
```

原站全期下载示例（除首月外共 7,517 份，已有合格文件会复用）：

```powershell
& '.\.venv-data\Scripts\python.exe' '.\dl_oisst\download_oisst.py' --source ncei --start 200412 --end 202506
```

也可以分年下载，例如：

```powershell
& '.\.venv-data\Scripts\python.exe' '.\dl_oisst\download_oisst.py' --source ncei --start 201904 --end 202506
```

全期下载完成后，只校验、不下载：

```powershell
& '.\.venv-data\Scripts\python.exe' '.\dl_oisst\download_oisst.py' --start 200411 --end 202506 --check-only
```

## 运行与验收

- 同时只运行一个 OISST 下载进程；脚本逐日串行下载。
- 每份新文件先写入 `.nc.part`，验证成功后才改为正式名称。
- 网络失败最多尝试三次；首个无法完成的日期出现后停止。日志保存在 `F:\AAAzxz\SRTP_M\data_dl\logs\download\oisst_*.log`。
- 中断后重新运行原命令：已有正式文件校验后复用；完整的临时文件可以转正；不完整临时文件重新完整下载，不进行字节级续传。
- 异常的正式文件不会被自动覆盖；需要先查看失败日期和校验原因。
- 检查产品版本、最终版标识、目标日期、完整全球网格、变量维度和单位；读取全部数据块，确认研究区 `sst` 和 `err` 各自存在有效值。`ice` 可在无海冰区域缺失。
- 日文件时间坐标通常标为当天 12:00，代表该日数据。
- 每份通过校验的文件记录字节数及 SHA-256；它是本地文件指纹，不是与官方发布校验和进行比对。
- 下载验证/测试期原始数据沿用原研究划分，不涉及训练或查看模型效果。

## 首次首月验证记录（2026-11-11，历史记录）

- 日期范围、闰年和跨年检查通过；全期计划为 7,547 份。
- 错误版本、日期不符、缺失文件的拒绝检查通过；临时文件重新下载、完整临时文件恢复及正式文件复用检查通过。
- 2004 年 11 月已完成：新下载 29 份，复用手动下载样本 1 份，共 30 份，50,111,222 字节。
- 首月再次运行 `--check-only`，30 份均通过并复用；无 `.part` 或零字节文件。
- 实际下载中发生一次网络错误，自动重试成功。
- 下载日志：`F:\AAAzxz\SRTP_M\data_dl\logs\download\oisst_200411_200411_20261111_173610_585260.log`。
- 复核日志：`F:\AAAzxz\SRTP_M\data_dl\logs\download\oisst_200411_200411_20261111_173953_401180.log`。
- 首次验证时只完成了 2004 年 11 月；后续下载进度以最新日志和本地文件为准，不以此处历史记录判断。
