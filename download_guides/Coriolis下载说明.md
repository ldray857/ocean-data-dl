# Coriolis 缺失剖面下载

准备日期：2026-11-12。脚本已经编写并通过本地模拟测试，尚未启动真实数据下载。

## 下载内容和保存位置

- 脚本：`F:\AAAzxz\SRTP_M\data_dl\dl_argo\download_argo_coriolis.py`。
- 默认清单：`F:\AAAzxz\SRTP_M\data_dl\research\audits\argo_fast_20261112_120214\missing_files.csv`，含 23,466 个 Coriolis Core 单剖面路径。
- 来源：`https://data-argo.ifremer.fr/dac/`，每个请求只拼接清单中的相对路径。
- 保存位置：`F:\AAAzxz\SRTP_M\data_dl\data\raw\argo\coriolis\<浮标编号>\profiles\*.nc`。
- 清单已按 2005-01—2025-06、20°S—20°N、120°E 向东跨日界线至 80°W、太平洋海盆筛选。本脚本不重新筛空间或时间，不下载整包。

## 下午开始运行

在 PowerShell 中执行以下命令；使用绝对路径，不要求先切换目录：

```powershell
& 'F:\AAAzxz\SRTP_M\data_dl\.venv-data\Scripts\python.exe' 'F:\AAAzxz\SRTP_M\data_dl\dl_argo\download_argo_coriolis.py'
```

默认 4 个并发连接，每个文件最多尝试 3 次，读取超时 30 秒。项目环境已有 requests，无需另装依赖。

如果想先下载 10 份看看速度：

```powershell
& 'F:\AAAzxz\SRTP_M\data_dl\.venv-data\Scripts\python.exe' 'F:\AAAzxz\SRTP_M\data_dl\dl_argo\download_argo_coriolis.py' --limit 10
```

之后运行不带 `--limit` 的命令即可继续其余文件。`--limit` 限制的是本次尚未落盘的文件数，重复运行会继续选择下一批。

仅查看数量、不联网、不写文件：

```powershell
& 'F:\AAAzxz\SRTP_M\data_dl\.venv-data\Scripts\python.exe' 'F:\AAAzxz\SRTP_M\data_dl\dl_argo\download_argo_coriolis.py' --dry-run
```

## 暂停、恢复和结果

按一次 `Ctrl+C` 暂停，等程序退出。再次执行相同命令即可恢复；不要同时运行两个实例。

恢复以整个文件为单位：已有非空正式文件直接跳过，不读内容。未完成的 `.nc.part` 会从头下载，传输完成后才改名为正式 `.nc`。不覆盖已有正式文件；若发现已有零字节正式文件，会报错并保留，等待人工处理。

每次运行生成独立报告目录：

`F:\AAAzxz\SRTP_M\data_dl\logs\download\argo_coriolis_<时间戳>\`

- `download.log`：每约 10 秒显示进度，以及失败原因。
- `results.csv`：本次排入队列的文件及处理结果；强制结束可能使末尾记录未写完。
- `failed_files.csv`：失败路径与原因；404 不会自动改成其他 R/D 版本。
- `summary.json`：本次下载数、失败数、暂停状态和未确认完成数量。

普通网络错误会自动重试；整个任务结束后，重跑同一命令即可再次尝试仍缺失的文件。退出码 0 表示本次任务正常完成，1 表示存在失败，130 表示暂停。

## 本次范围

只下载原始文件，不解析 NetCDF、不检查字段或版本、不算哈希、不筛 QC、不裁剪深度。脚本仅检查 HTTP 状态、明显错误页面和传输长度，避免把错误页面或中断传输发布为正式数据。

已有非空文件直接复用，因此下载数不能当作有效温盐剖面数。最后的数据质量处理仍属于后续研究步骤。

执行前仅做过连接探测，读取目标文件开头 8 字节，未保存数据；用户要求推迟下载后，未继续访问官网。编写阶段的功能测试全部使用本地模拟响应。
