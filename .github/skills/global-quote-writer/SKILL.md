---
name: global-quote-writer
description: 将结构化报价结果写入标准 Excel 报价文件（Summary/LineItems/Assumptions/Evidence），用于交付、复核与审计留痕。
---

# 技能：报价 Excel 写入器

## 概述
当用户需要“导出报价文件”“生成可交付报价表”“沉淀审计证据”时，使用本技能。
本技能将结构化 JSON 报价数据写入标准化 Excel 工作簿。

## 触发场景
- 用户要求输出最终报价 Excel。
- 已有 VM/磁盘价格结果，需要整理为可审阅文件。
- 需要同时输出 Summary、LineItems、Assumptions、Evidence 四类信息。

## 运行方式

### 1) 初始化模板（首次使用）
`python .github/skills/global-quote-writer/scripts/write_quote_excel.py --init-template --template .github/skills/global-quote-writer/assets/summary-layout-template.xlsx`

### 2) 根据输入 JSON 生成报价 Excel
`python .github/skills/global-quote-writer/scripts/write_quote_excel.py --input-json output/quote_payload.json --output-xlsx output/quote_result.xlsx --template .github/skills/global-quote-writer/assets/summary-layout-template.xlsx`

### 2a)（可选）从 VM 流水线 CSV 生成 quote_payload.json
`python .github/skills/global-quote-writer/scripts/build_vm_quote_payload.py --input-csv output/vm_pricing_results.csv --output-json output/quote_payload.json --customer-project "Project A" --region "Singapore"`

## 输入要求
`--input-json` 需符合 `references/guide-input-schema.md`。
最少应包含：
- `summary`（对象）
- `line_items`（数组）

## 输出
脚本会：
1. 生成/更新目标 Excel 文件；
2. 在 stdout 返回 JSON 结果（`status`, `output_file`, `sheets_written`, `row_counts`）。

## 错误处理规则
- 若输入缺少必要字段：直接报错并返回 `status=error`。
- 若模板不存在：提示先执行 `--init-template` 或提供有效模板路径。
- 严禁在缺失数据时自行编造价格、数量或假设。
