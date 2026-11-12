# ocean-data-dl

本仓库用于保存海洋数据下载、原始文件提取和校验代码，是本人 SRTP 项目“热带太平洋稀疏观测条件下的月尺度三维温盐重建”的组成部分。

本地工作目录为主项目中的 `SRTP_M/data_dl/`，单独作为 Git 仓库管理。仓库保存 Python 脚本和使用说明，下载数据及本机运行产物保留在本地。

## 当前支持

| 数据 | 内容 | 当前脚本范围 |
|---|---|---|
| DUACS ADT | 逐日绝对动力地形 | Copernicus Marine 按月、分区下载及校验 |
| NOAA OISST v2.1 | 全球逐日海表温度、误差、海冰辅助字段 | NCEI、Google Cloud、AWS 同产品下载源及校验 |
| Argo Core | 压力、温度、盐度及调整值、QC和元数据 | 国内压缩包按冻结清单提取、Coriolis 按缺失清单下载、原始文件校验 |

脚本中的研究区和时间范围沿用本项目设定：20°S—20°N，120°E 向东跨日界线至80°W；主体时间为2005年1月—2025年6月。ADT和OISST包含2004年11—12月缓冲数据。OISST保存全球原始日文件，Argo保留完整原始剖面。

## 代码索引

| 文件 | 用途 |
|---|---|
| `download_adt.py` | 下载与校验DUACS ADT，固定数据集版本 `202411` |
| `download_oisst.py` | 下载与校验NOAA OISST v2.1 AVHRR最终版 |
| `download_argo_coriolis.py` | 根据 `file` 列缺失清单下载Coriolis Core单剖面，跳过已有非空文件 |
| `audit_argo_archives.py` | 检查国内Argo压缩包完整性、冻结清单覆盖及少量样本 |
| `extract_argo_fast.py` | 从AOML压缩包按冻结清单快速提取，跳过已有正式文件，不解析NetCDF或计算哈希 |
| `extract_argo_archives.py` | 按资料中心选择性提取，检查字段、记录哈希并支持恢复 |
| `verify_argo_files.py` | 根据完整提取清单核对落盘文件大小和SHA-256 |
| `finalize_argo_inventory.py` | 汇总已有完整提取清单并复核历史格式问题 |
| `validate_argo.py` | 只读检查NetCDF3/4可读性、元数据和QC，生成逐文件诊断 |
| `report_argo_validation.py` | 从完整校验结果生成中文报告和分类清单 |

## 环境

建议使用Python 3.14。部分批量校验代码使用Python 3.14新增的 `Executor.map(buffersize=...)`。`requirements.txt`记录当前工作环境中直接依赖的版本，不是完整环境锁文件。

在PowerShell中，根据自己的环境位置选择Python解释器安装依赖。例如，在仓库内创建环境：

```powershell
py -3.14 -m venv .venv-data
& '.\.venv-data\Scripts\python.exe' -m pip install -r requirements.txt
```

已有项目环境可以直接使用，不必重新创建。虚拟环境不提交Git。

## 常用命令

以下命令在本仓库根目录执行。

### ADT

先通过Copernicus Marine官方工具登录，本机保存凭据：

```powershell
& '.\.venv-data\Scripts\copernicusmarine.exe' login
```

预览一个月的下载计划，不联网、不下载：

```powershell
& '.\.venv-data\Scripts\python.exe' '.\download_adt.py' --start 200501 --end 200501 --plan
```

下载时去掉 `--plan`。结果保存到 `data/raw/adt/`，每月west/east两份文件。

### OISST

预览一个月的下载计划：

```powershell
& '.\.venv-data\Scripts\python.exe' '.\download_oisst.py' --start 200501 --end 200501 --source google --plan
```

下载时去掉 `--plan`。结果按月份保存到 `data/raw/oisst/YYYYMM/`。可通过 `--source ncei` 或 `--source aws` 选择其他已配置下载源。

### Argo

Argo流程依赖已经冻结的本地候选清单和审计记录，这些运行产物不随仓库提交。当前代码保留了本次研究的日期命名默认路径；在其他电脑使用时，必须准备相应清单并检查路径。

缺失清单至少包含 `file` 列，路径形如 `coriolis/<WMO>/profiles/<文件名>.nc`。可显式指定清单，先预览数量：

```powershell
& '.\.venv-data\Scripts\python.exe' '.\download_argo_coriolis.py' --manifest '.\research\audits\missing_files.csv' --dry-run
```

去掉 `--dry-run` 开始下载；`--limit 10` 限制本次最多下载10个尚未落盘的文件。默认4并发，完成的文件直接跳过；未完成的 `.part` 文件下次从头下载。结果保存到 `data/raw/argo/coriolis/`。

国内包流程仍使用本机路径：`audit_argo_archives.py` 的 `DOWNLOADS` 默认指向 `D:\system\Downloads`；`extract_argo_fast.py` 的 `SOURCE` 指向其中的 `aoml.tar.gz`。迁移时修改这些配置常量，并准备 `INVENTORY` 指向的冻结清单。不要在没有本地清单、原包或完整提取记录的情况下直接执行这些脚本。

全量只读校验可显式指定冻结索引清单。该清单需要包含 `file,date,latitude,longitude,ocean,profiler_type,institution,date_update` 列：

```powershell
& '.\.venv-data\Scripts\python.exe' '.\validate_argo.py' --inventory '.\research\audits\argo_inventory.csv' --raw '.\data\raw\argo' --workers 4
```

校验报告写入 `research/audits/argo_validation_<时间戳>/`。再将实际生成的报告目录传给 `report_argo_validation.py`，生成中文汇总。

Argo不同脚本的检查强度不同：快速提取和Coriolis下载不做科学质控；完整提取可以记录哈希；全量校验提供QC诊断统计。文件齐全、可读或包含QC1/2配对点，都不等于整条剖面已经满足最终研究筛选规则。当前代码未完成5—500 m深度标准化或月平均。

## 本地目录与Git范围

```text
data/raw/       原始数据
logs/           下载日志
research/audits/ 冻结清单、校验记录和生成报告
```

这些目录由运行过程创建或由使用者准备，均已加入 `.gitignore`。“下载说明”目录、虚拟环境、缓存和本机凭据也保留在本地。不要把账号密码直接写入代码。

下载时应遵循各数据提供方的许可、引用要求和访问限制；数据集版本按研究约定固定，不在下载过程中静默切换。
