# Argo Core 国内镜像下载教程

整理日期：2026-11-11。适用于本项目的原始 Core 单剖面资料下载。

## 1. 本项目要下载什么

目标时间为 2005-01—2025-06，研究区为纬度 −20—20、经度 120—280（0—360 经度制），索引海盆标记为 P。已冻结清单共有 532,122 份候选文件。

国内网站按资料中心（DAC）提供全球原始资料压缩包。资料中心名不代表观测海区；整包还包含研究时间、区域之外的数据。我们下载整包后，再按已冻结清单提取需要的 R/D 开头的 Core 单剖面文件。

候选数量不是通过温盐、深度和质量控制筛选的有效剖面数。

## 2. 全部国内下载地址

以下链接均来自[中国 Argo 实时资料中心官方实时资料页面](https://www.argo.org.cn/index.php?a=lists&c=index&catid=26&m=content)，已于整理日期核对。官网列出链接不等于各包均已在本机下载验证。

| 推荐顺序 | 资料中心 | 文件名与国内下载链接 | 本项目候选文件数 | 本次是否需要 | 是否下载 |
|---:|---|---|---:|---|---|
| 1 | 美国 AOML | [aoml.tar.gz](https://data.argo.org.cn/mirror_gdac/aoml.tar.gz) | 415,396 | 需要；你已开始尝试，显示约 22 GB |  |·
| 2 | 日本 JMA | [jma.tar.gz](https://data.argo.org.cn/mirror_gdac/jma.tar.gz) | 40,608 | 需要 | 1 |
| 3 | 中国 CSIO | [csio.tar.gz](https://data.argo.org.cn/mirror_gdac/csio.tar.gz) | 29,824 | 需要 | 1 |
| 4 | 澳大利亚 CSIRO | [csiro.tar.gz](https://data.argo.org.cn/mirror_gdac/csiro.tar.gz) | 18,351 | 需要 | 1 |
| 5 | 韩国 KMA | [kma.tar.gz](https://data.argo.org.cn/mirror_gdac/kma.tar.gz) | 2,998 | 需要 | 1 |
| 6 | 韩国 KIOST | [kiost.tar.gz](https://data.argo.org.cn/mirror_gdac/kiost.tar.gz) | 713 | 需要 | 1 |
| 7 | 英国 BODC | [bodc.tar.gz](https://data.argo.org.cn/mirror_gdac/bodc.tar.gz) | 557 | 需要 | 1 |
| 8 | 加拿大 MEDS | [meds.tar.gz](https://data.argo.org.cn/mirror_gdac/meds.tar.gz) | 209 | 需要 | 1 |
| — | 印度 INCOIS | [incois.tar.gz](https://data.argo.org.cn/mirror_gdac/incois.tar.gz) | 0 | 本次不用下载 |  |
| — | 中国 NMDIS | [nmdis.tar.gz](https://data.argo.org.cn/mirror_gdac/nmdis.tar.gz) | 0 | 本次不用下载 |  |
| — | 索引包 | [argo_index.tar.gz](https://data.argo.org.cn/mirror_gdac/argo_index.tar.gz) | 不适用 | 已下载并核对，不用重复下载 |  |

法国 Coriolis 对应本项目 23,466 份候选文件，但上述官方页面没有列出它的压缩包链接，不能编造一个地址当作可用镜像。后续需核实其他入口，或按清单从 GDAC 下载。

注意区分：`csiro` 是澳大利亚机构，`coriolis` 才是法国资料中心。官方页面把 CSIRO 的国家写成了法国，不要因此把两者当成同一个包。

本项目需要的上述 8 个国内包涉及 508,656 个候选路径；加上 Coriolis 共 532,122 个。这是索引统计，实际包内覆盖需提取后核验。

## 3. 在浏览器下载

1. 保持你已经测得约 5 MB/s 的直连网络配置。
2. 点击表格第一行的 `aoml.tar.gz`。如果已经在下载，继续当前任务即可，不重复新建同名任务。
3. 建议先保存到 `D:\system\Downloads\`，保持原文件名。例如：`D:\system\Downloads\aoml.tar.gz`。也可以保存到其他有足够空间的磁盘，完成后提供实际路径即可。
4. 在浏览器下载列表中查看进度和速度。浏览器一般可通过 `Ctrl+J` 打开下载列表；若失败，先使用该任务的继续或重试功能。
5. 等到任务显示完成，文件名没有 `.crdownload`、`.part` 等未完成后缀。
6. 将完整保存路径发给我。我检查并处理这个包后，再按表中顺序继续其他包，便于控制存储占用和排查缺口。

按稳定 5 MB/s 粗略估计，22 GB 约需 75 分钟；实际时间受单位换算和网络波动影响。其他包的大小尚未验证，以浏览器显示为准，不能根据所需候选文件数推算整包大小。

下载前确认保存盘能容纳压缩包；后续提取还需要额外空间。具体提取占用要检查包内文件大小后才能确定。

## 4. 下载完成后由我处理

你不需要先全部解压，直接提供压缩包路径。

我会依次检查：

1. 压缩包能否完整读取，计算并记录包的 SHA-256，保留原压缩包。
2. 按已冻结基准清单，只提取本项目需要的文件，保留原始 NetCDF 内容和目录结构。例如 AOML 文件保存到 `F:\AAAzxz\SRTP_M\data_dl\data\raw\argo\aoml\<浮标编号>\profiles\`。
3. 核对文件路径、时间、位置、浮标编号及关键字段，检查 NetCDF 可读性，记录文件大小和 SHA-256。
4. 输出已提取、异常、缺失和索引更新时间差异的处理记录。不能因为清单包含某个路径，就假定包中一定存在或内容完全相同。
5. 下载其余资料中心的包，最后按冻结清单从 GDAC 补缺。

下载和提取阶段保留完整原始剖面及 QC 字段，不计算月平均，不截断深度，不提前按质量控制排除候选文件。后续预处理再实施温盐、深度和 QC 筛选。

## 5. 容易混淆的地方

- 选择 `mirror_gdac` 下的原始资料包。页面推荐的“全球海洋 Argo 散点资料集”经过额外处理，不作为本次原始 Core 剖面的替代品。
- `argo_index.tar.gz` 是文件目录和元数据索引，不包含本项目全部实际温盐剖面；它已在本机完成核对。
- 8 个国内包不代表全部工作完成，仍要检查实际缺失并处理 Coriolis 部分。
- 如浏览器提示证书或连接错误，保留具体提示后排查，不直接忽略证书错误。本机此前自动读取包信息遇到过证书链校验失败；这不代表你浏览器中的下载一定失败。

## 6. 已有清单与报告

- 基准清单：`F:\AAAzxz\SRTP_M\data_dl\research\audits\argo_inventory_20261111_211915.csv`
- 国内镜像索引核对报告：`F:\AAAzxz\SRTP_M\data_dl\research\audits\argo_china_mirror_20261111_213729.md`
- 国内镜像统计与校验和：`F:\AAAzxz\SRTP_M\data_dl\research\audits\argo_china_mirror_20261111_213729.json`
- 已下载索引包：`D:\system\Downloads\argo_index.tar.gz`

国内索引标记更新日期为 2026-11-10，与 2026-11-11 的 GDAC 基准清单相比，候选路径相同；20 条记录仅 `date_update` 字段不同。后续以实际包内内容核验为准。
