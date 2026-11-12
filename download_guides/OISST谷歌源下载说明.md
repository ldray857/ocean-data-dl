# OISST Google Cloud 下载说明

- 脚本：`F:\AAAzxz\SRTP_M\data_dl\download_oisst.py`。
- 新增 `--source google`；原 NCEI 源保留为 `--source ncei`，不指定时仍使用 NCEI。
- Google Cloud 地址：`https://storage.googleapis.com/noaa-cdr-sea-surface-temp-optimum-interpolation/data/v2.1/avhrr/`。
- AWS 区域入口：`https://noaa-cdr-sea-surface-temp-optimum-interpolation-pds.s3.us-east-1.amazonaws.com/data/v2.1/avhrr/`，使用 `--fallback-source aws` 启用。
- 该入口由 NOAA 产品页面列出：https://www.ncei.noaa.gov/products/climate-data-records/sea-surface-temperature-optimum-interpolation 。无需账号。
- 产品仍为 NOAA OISST v2.1 AVHRR 最终版；文件名、变量、网格及校验要求不变。
- 抽查 2004-11-01、2010-04-12 两份云端文件：完整校验通过，SHA-256 与本地 NCEI 原文件一致。
- 输出沿用 `F:\AAAzxz\SRTP_M\data_dl\data\raw\oisst\YYYYMM\`，已有正式文件先校验再复用，不重新下载。
- 未完成的 `.nc.part` 会重新完整下载；通过校验后转为正式文件。主源返回 404 时，若指定备用源，就从备用源获取同一日、同一版本文件，并在日志记录实际来源；其他错误或备用源失败仍会停止。不跳过缺失日期。

续传命令（2010 年 11 月至 2025 年 6 月，Google 优先，404 时用 AWS）：

```powershell
& 'F:\AAAzxz\SRTP_M\data_dl\.venv-data\Scripts\python.exe' 'F:\AAAzxz\SRTP_M\data_dl\download_oisst.py' --source google --fallback-source aws --start 201206 --end 202506
```

同时只运行一个 OISST 下载任务。若后台任务已启动，不要再次执行此命令。

Google Cloud 本次续传日志位于：`F:\AAAzxz\SRTP_M\data_dl\logs\download\oisst_google_201011_202506_*.log`。
可在另一个 PowerShell 窗口查看最新日志：

```powershell
$latestLog = Get-ChildItem -LiteralPath 'F:\AAAzxz\SRTP_M\data_dl\logs\download' -Filter 'oisst_google_201011_202506_*.log' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Get-Content -LiteralPath $latestLog.FullName -Encoding UTF8 -Tail 10 -Wait
```

查看日志窗口按 `Ctrl+C` 只会停止日志跟踪；后台下载任务仍会继续。

## 本次启动记录

- 启动时间：2026-11-11 21:21（Asia/Shanghai），以隐藏窗口方式在后台运行。
- 范围：2010-04-01—2025-06-30，共 5,570 份目标文件；启动时复用已有 12 份，需补下 5,558 份。
- 启动后已确认 2010-04-13 下载并完整校验成功，约 2.6 秒。该次任务后来在 2010-11-01 因 Google 返回 404 而停止；此前已完成至 2010-10-31。
- 下载日志：`F:\AAAzxz\SRTP_M\data_dl\logs\download\oisst_google_201004_202506_20261111_212124_228993.log`。
- 启动进程 PID：44244，实际 Python 子进程 PID：14960（仅供本次运行排查，进程状态以后续实时查询为准）。

## 镜像缺失排查与修复（2026-11-11）

- 核对 2010-04—2025-06 的远程目录清单：Google 列出 4,930/5,570 份，缺 640 份；AWS 区域入口列出全部 5,570 份。
- 这是对象名称覆盖检查，不代表所有对象的内容均已校验。
- 对 2010-11-01 实际读取并校验：AWS 与 NCEI 原站文件的 SHA-256 均为 `015672f5b7475203f2a906fa4b93894d0b26e136d07af8637e0e1fdef57a8d69`。
- 目录核对报告：`F:\AAAzxz\SRTP_M\data_dl\logs\download\oisst_mirror_inventory_20261111_213603_604170.json`。
- 新增显式参数 `--fallback-source aws`。已验证 Google 404 时切换、已有文件复用、非 404 错误不切换、备用源仍缺失时停止。
- 21:36（Asia/Shanghai）已按上面命令从 201011 恢复后台下载；2010-11-01 已经通过 AWS 下载并完整校验，SHA-256 与原站样本一致。
- 新日志：`F:\AAAzxz\SRTP_M\data_dl\logs\download\oisst_google_201011_202506_20261111_213639_601591.log`。
- 本次启动进程 PID：50796，实际 Python 子进程 PID：35844；全期尚在下载，后续状态以实时日志为准。
