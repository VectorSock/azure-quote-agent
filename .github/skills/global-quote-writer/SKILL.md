---
name: global-quote-writer
description: 将结构化报价结果写入标准 Excel 报价文件（Summary/LineItems/Assumptions/Evidence）。
---

# 技能：报价 Excel 写入器

## 概述
将结构化 quote payload 写入标准报价工作簿，用于交付、复核和审计留痕。

## 运行方式
初始化模板：

python .github/skills/global-quote-writer/scripts/write_quote_excel.py --init-template --template .github/skills/global-quote-writer/assets/summary-layout-template.xlsx

写入报价：

python .github/skills/global-quote-writer/scripts/write_quote_excel.py --input-json output/quote_payload.json --output-xlsx output/quote_result.xlsx --template .github/skills/global-quote-writer/assets/summary-layout-template.xlsx

从定价 CSV 生成 payload：

python .github/skills/global-quote-writer/scripts/build_vm_quote_payload.py --input-csv output/vm_pricing_results.csv --output-json output/quote_payload.json

## 输入要求
至少包含 summary 与 line_items，详细结构见 references/guide-input-schema.md。

## 列名规范
统一列名请参考：
.github/skills/references/column-schema.md
