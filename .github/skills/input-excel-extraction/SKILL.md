---
name: input-excel-extraction
description: 从原始 Excel 中做第一步结构化抽取，输出标准化中间数据供后续各类云资源 skill 复用。
---

# 技能：Excel 原始数据第一步抽取

## 概述
用于将原始 Excel 统一抽取为标准中间 CSV，便于后续 region mapping、规格映射、定价与报价写入。

## 运行方式
标准抽取：

python .github/skills/input-excel-extraction/scripts/extract_excel_inputs.py --input-excel input/sample_input.xlsx --output output/extracted_inputs.csv

通用抽取：

python .github/skills/input-excel-extraction/scripts/extract_excel_inputs.py --input-excel input/sample_input.xlsx --profile all_resources --output output/extracted_all_resources.csv

## 参数说明
- --profile: aws_vm 或 all_resources
- --include-review: 保留 status != ok 的记录
- --provider / --resource-type: 过滤指定资源

## 输出要点
- 自动归一化 provider、resource_type、os
- profile=aws_vm 时输出 instance_type
- SAP 相关列（system/env/SAP_workload/workload_type/disk）会透传

## 执行规则
1. 后续流程仅消费脚本输出，不补猜字段。
2. extracted_rows=0 时应提示当前 profile 未命中。
3. 新资源类型优先通过新增 profile 扩展。

## 列名规范
统一列名请参考：
.github/skills/references/column-schema.md
