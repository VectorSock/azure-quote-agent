---
name: input-pdf-extraction
description: 通过 Azure Document Intelligence 从 PDF 中抽取 VM 报价所需字段，输出标准化中间 CSV 供后续 skill 复用。
---

# 技能：PDF 原始数据第一步抽取

## 概述
当用户提供 PDF 报价单或资源清单时，先用本技能做第一步抽取。输出字段与 input-excel-extraction 对齐，便于直接接入后续流水线。

## 运行前准备
安装依赖：

python -m pip install azure-ai-documentintelligence

设置凭证（或用命令行参数传入）：

- AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT
- AZURE_DOCUMENT_INTELLIGENCE_KEY

## 运行方式
标准抽取：

python .github/skills/input-pdf-extraction/scripts/extract_pdf_inputs.py --input-pdf input/sample_input.pdf --output output/extracted_inputs_from_pdf.csv

通用抽取：

python .github/skills/input-pdf-extraction/scripts/extract_pdf_inputs.py --input-pdf input/sample_input.pdf --profile all_resources --output output/extracted_all_resources_from_pdf.csv

## 关键参数
- --profile: aws_vm 或 all_resources
- --include-review: 保留 status != ok 的记录
- --provider / --resource-type: 批量过滤
- --endpoint / --key / --auth-mode / --model-id: DI 连接与模型配置

## 输出约定
- quantity 优先从同一文本行解析，缺失默认为 1.0
- profile=aws_vm 时输出 instance_type，供 vm-aws-instance-to-config 使用
- 输出为 CSV 主数据流 + JSON 摘要

## 执行规则
1. 后续流程只消费脚本输出，不补猜字段。
2. extracted_rows=0 时必须明确提示未识别到可用实例型号。
3. 精度优化优先改抽取规则或更换自定义 DI 模型，不在后续 skill 隐式修正。

## 列名规范
统一列名请参考：
.github/skills/references/column-schema.md
