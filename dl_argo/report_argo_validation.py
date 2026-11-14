"""Summarize a completed read-only Argo validation without reopening NetCDF files."""

import argparse
import csv
import json
from pathlib import Path


def main() -> None:
    """Produce readable conclusions and focused follow-up lists."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    report = args.report.resolve()
    summary = json.loads((report / "summary.json").read_text(encoding="utf-8"))
    if not summary["full_scan"]:
        raise ValueError("仅为试跑报告，不能生成正式全量校验结论")
    totals = summary["totals"]
    coverage = summary["coverage"]
    if totals["checked"] != coverage["expected"]:
        raise ValueError("读取数量与冻结清单不一致，不能生成已完成结论")
    counts = {"unreadable_files": 0, "no_selected_salinity_files": 0,
              "without_qc12_pairs_files": 0, "metadata_review_files": 0}
    handles = {}
    writers = {}
    try:
        with (report / "files.csv").open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for name in counts:
                handles[name] = (report / f"{name}.csv").open("w", encoding="utf-8-sig", newline="")
                writers[name] = csv.DictWriter(handles[name], fieldnames=reader.fieldnames)
                writers[name].writeheader()
            for row in reader:
                conditions = {
                    "unreadable_files": row["readable"] != "True",
                    "no_selected_salinity_files": int(row["selected_psal_finite_points"] or 0) == 0,
                    "without_qc12_pairs_files": int(row["paired_qc12_points"] or 0) == 0,
                    "metadata_review_files": any(
                        issue.startswith(("index_", "path_", "outside:", "invalid:", "units:", "shape:", "reference_date:"))
                        for issue in row["issues"].split(";")
                    ),
                }
                for name, matches in conditions.items():
                    if matches:
                        counts[name] += 1
                        writers[name].writerow(row)
    finally:
        for handle in handles.values():
            handle.close()
    for key in ("by_dac", "by_month"):
        with (report / f"{key}.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["group", "checked", "readable", "with_issues", "with_qc12_pairs"])
            writer.writeheader()
            for group, data in sorted(summary[key].items()):
                writer.writerow({"group": group, **data})
    (report / "followup_counts.json").write_text(json.dumps(counts, indent=2) + "\n", encoding="utf-8")
    complete = not any(coverage[key] for key in ("missing", "unexpected", "temporary"))
    readable = totals.get("unreadable", 0) == 0
    inspected = summary["issue_counts"].get("inspection_error", 0) == 0
    conclusion = (
        "文件覆盖、全变量读取及检查流程通过；科学使用前仍需质量筛选。"
        if complete and readable and inspected else
        "已完成全量扫描，但有缺口、读取失败或需复核的问题，见下列统计与异常清单。"
    )
    lines = [
        "# Argo 全量只读校验结果", "", conclusion, "",
        "本次按冻结清单逐文件读取一次，未重新解压压缩包，未计算原始文件哈希。",
        "原始数据未修改、删除或重新下载；没有做质量筛除、深度插值或月平均。", "",
        "## 文件完整性", "",
        f"- 冻结清单：{coverage['expected']:,} 份；正式 NetCDF：{coverage['actual_nc']:,} 份。",
        f"- 缺失：{coverage['missing']:,}；清单外文件：{coverage['unexpected']:,}；临时文件：{coverage['temporary']:,}。",
        f"- 本次读取：{totals['checked']:,}；可读：{totals['readable']:,}；不可读：{totals['unreadable']:,}。",
        f"- NetCDF 格式统计：{summary['formats']}。",
        f"- 读取字节数：{totals['bytes']:,}（{totals['bytes'] / 1024 ** 3:.2f} GiB）。",
        f"- 内容统计阶段耗时：{summary['elapsed_seconds']:.1f} 秒；不含文件路径枚举。", "",
        "| 资料中心 | 文件数 | 可读文件数 | 有QC1/2配对点的文件数 |",
        "|---|---:|---:|---:|",
    ]
    for dac, data in sorted(summary["by_dac"].items()):
        lines.append(f"| {dac} | {data['checked']:,} | {data['readable']:,} | {data['with_qc12_pairs']:,} |")
    followup_file = report / "metadata_followup.json"
    if followup_file.exists():
        details = json.loads(followup_file.read_text(encoding="utf-8"))["files"]
        boundary = [item for item in details if "outside:research_box" in item["issues"]]
        missing_position = [item for item in details if "invalid:LATITUDE" in item["issues"]]
        versions = [item for item in details if "index_difference:DATE_UPDATE" in item["issues"]]
        lines += [
            "", "## 30份元数据提示的针对性复核", "",
            "全量单次扫描结束后，仅重新读取这30份提示文件，补充保存为 `metadata_followup.json`。",
            f"- {len(boundary)}份边界提示：索引纬度四舍五入为±20°，原始纬度略超出边界，最大0.0005°。",
            "  它们符合冻结索引的候选条件，但不满足原始坐标的严格边界；后续空间筛选按原始坐标执行。",
            f"- {len(missing_position)}份位置缺失提示：均为第2条子剖面位置缺失、POSITION_QC=9；主剖面位置正常。",
            f"- {len(versions)}份DATE_UPDATE差异：文件更新时间早于冻结官方索引，记录为源版本差异。",
            "  不据此认定温盐数值相同或不同，也没有自动替换国内镜像文件。",
        ]
    lines += [
        "", "## 温盐与QC诊断", "",
        f"- 文件内共 {totals['profiles']:,} 条子剖面记录。一个文件可有多条记录，不能把记录数与文件数混用。",
        f"- DATA_MODE 分布（子剖面记录数）：{summary['data_modes']}。",
        f"- 按 DATA_MODE 选定参数后，至少存在有限盐度值的文件：{totals['files_with_finite_selected_psal']:,}；",
        f"  不存在有限盐度值的文件：{counts['no_selected_salinity_files']:,}。",
        f"- 同一层压力、温度、盐度均非填充值且有限的配对点：{totals['paired_finite_points']:,}。",
        f"- 三者QC均为1的配对点：{totals['paired_qc1_points']:,}。",
        f"- 三者QC均为1或2的配对点：{totals['paired_qc12_points']:,}，分布在",
        f"  {totals['files_with_qc12_pairs']:,} 个文件、{totals['profiles_with_qc12_pairs']:,} 条子剖面记录中。",
        f"- 无上述QC1/2配对点的文件：{counts['without_qc12_pairs_files']:,}。",
        f"- 出现任一内容诊断的文件：{totals['files_with_issues']:,}；这不是损坏文件数。",
        f"- 需要时间、位置、身份、单位、形状或索引版本复核的文件：{counts['metadata_review_files']:,}。",
        f"- 重复的浮标/循环/方向/记录序号键：{len(summary['duplicate_profile_keys']):,} 组。",
        "", "### 统计口径", "",
        "- DATA_MODE=R使用原始参数及其QC；A/D使用调整值及其QC。调整值缺失时不回退混用原值。",
        "- QC1和QC1/2是诊断情景，尚未固定研究筛选阈值；上述数量不是最终合格温盐剖面数。",
        "- 配对点数量未叠加时间/位置QC、误差上限或目标深度范围；QC直方图含填充层的缺失标记。",
        "- `no_finite_selected:*`表示至少一条子剖面缺该参数，不表示整文件都不能用；需结合每文件有限值总数。",
        "- `declared_range:*`仅提示值超出变量声明范围，未据此删除文件；轻微负压力也可能触发此项。",
        "- `index_difference:DATE_UPDATE`表示文件更新时间与冻结索引不同，不足以判定文件损坏。",
        "- CSV压力范围单位为dbar，尚未换算为米；未评价5—500 m目标层的完整覆盖或插值条件。",
        "- 全变量可读取不等同于与远端原文件逐字节一致，本次不作该声明。", "",
        "QC选择依据：[Argo官方文件使用指南](https://argo.ucsd.edu/data/how-to-use-argo-files/)。", "",
        "## 内容诊断项目（每项为涉及文件数，可重叠）", "",
        "| 项目 | 文件数 |", "|---|---:|",
    ]
    for issue, count in sorted(summary["issue_counts"].items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| {issue} | {count:,} |")
    lines += [
        "", "## 报告文件", "",
        f"报告目录：`{report}`", "",
        "- `summary.json`：完整机器可读汇总；`coverage.json`：路径覆盖。",
        "- `files.csv`：逐文件结果；`issues.csv`：出现内容诊断的文件。",
        "- `unreadable_files.csv`：打不开或全变量解码失败的文件。",
        "- `no_selected_salinity_files.csv`：按模式选择后完全没有有限盐度值的文件。",
        "- `without_qc12_pairs_files.csv`：没有三参数QC1/2配对点的文件。",
        "- `metadata_review_files.csv`：索引版本、时间、位置、身份、单位或形状等复核清单。",
        "- `by_dac.csv`、`by_month.csv`：资料中心及246个月的覆盖与QC诊断。",
        "- `missing_files.csv`、`unexpected_files.csv`、`temporary_files.csv`：路径异常清单。", "",
        "## 下一步", "",
        "保留全部原始文件，依据QC、误差和时间/位置质量规则生成独立的研究用筛选结果；",
        "逐条处理多子剖面记录，并在压力换算深度后检查5—500 m覆盖及必要的下边界支撑。",
        "本次不生成插值结果、不提前做月平均。", "",
    ]
    destination = report / "validation_report.md"
    destination.write_text("\n".join(lines), encoding="utf-8")
    print(destination)
    print(json.dumps({"conclusion": conclusion, **counts}, ensure_ascii=False))


if __name__ == "__main__":
    main()
