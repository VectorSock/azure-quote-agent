---
name: vm-sap-workload-inference
description: 基于 system/env/workload_type 规则推断 SAP_workload（True/False），并回填 CSV/XLSX。
---

# 技能：SAP Workload 识别与回填

## 概述
用于新表头输入中的 SAP_workload 空值回填，输出推断值、置信度、分类与原因链路。

## 单条示例
python .github/skills/vm-sap-workload-inference/scripts/infer_sap_workload.py --system S4 --env PRD --workload-type DB

## 批量示例
python .github/skills/vm-sap-workload-inference/scripts/infer_sap_workload.py --input-file input/data.xlsx --output output/data_with_sap.xlsx

## 执行规则
1. 默认仅回填空值，--overwrite 才覆盖已有 SAP_workload。
2. 输入至少包含 system 或 workload_type 之一。
3. 该技能是规则推断，不替代 SAP 官方认证结论。

## 输出字段
- SAP_workload
- sap_workload_inferred
- sap_workload_confidence
- sap_workload_category
- sap_workload_reason

## 列名规范
统一列名请参考：
.github/skills/references/column-schema.md
