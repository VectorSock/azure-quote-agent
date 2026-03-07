````skill
---
name: pdf-input-extraction
description: 通过 Azure Document Intelligence 从 PDF 中抽取 VM 报价所需字段，输出标准化中间 CSV 供后续 skill 复用。
---

# 技能：PDF 原始数据第一步抽取

## 概述
当用户提供 PDF 报价单或资源清单时，先用本技能做“第一步抽取”，通过 Azure Document Intelligence 识别文本并提取 VM 报价所需字段，输出和 `scripts/extract_excel_inputs.py` 对齐的标准中间数据。

本技能会：
- 调用 Azure Document Intelligence 解析 PDF；
- 识别 AWS VM 实例型号（如 `m6a.4xlarge`）；
- 生成统一记录（`provider`、`resource_type`、`instance_name`、`quantity`、`region_input`、`status` 等）；
- 输出 CSV 供 `region-mapping` 等后续 skill 链式消费。

## 何时使用
- 输入不是 Excel，而是 PDF 规格单/报价单。
- 你希望将 PDF 抽取结果复用到既有 VM 报价流水线。
- 你希望保留“CSV 主数据流 + JSON 摘要”模式。

## 运行前准备
安装 SDK：

`pip install azure-ai-documentintelligence`

设置凭证（或命令行传参）：

`export AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT="https://<your-resource>.cognitiveservices.azure.com/"`

`export AZURE_DOCUMENT_INTELLIGENCE_KEY="<your-key>"`

## 运行方式
所有路径默认基于当前工作目录。

### 标准抽取（默认 profile: `aws_vm`）
`python .github/skills/pdf-input-extraction/scripts/extract_pdf_inputs.py --input-pdf "input/sample_input.pdf" --output "output/extracted_inputs_from_pdf.csv"`

### 通用抽取（保留所有资源类型）
`python .github/skills/pdf-input-extraction/scripts/extract_pdf_inputs.py --input-pdf "input/sample_input.pdf" --profile all_resources --output "output/extracted_all_resources_from_pdf.csv"`

### 使用自定义模型
`python .github/skills/pdf-input-extraction/scripts/extract_pdf_inputs.py --input-pdf "input/sample_input.pdf" --model-id "prebuilt-layout" --output "output/extracted_inputs_from_pdf.csv"`

### 过滤抽取（按 provider / resource_type）
`python .github/skills/pdf-input-extraction/scripts/extract_pdf_inputs.py --input-pdf "input/sample_input.pdf" --profile all_resources --provider aws --resource-type vm --output "output/aws_vm_rows_from_pdf.csv"`

## 参数说明
- `--input-pdf`：输入 PDF 路径。
- `--output`：输出 CSV 路径（默认 `output/extracted_inputs_from_pdf.csv`）。
- `--profile`：抽取配置（支持 `aws_vm`、`all_resources`）。
- `--include-review`：是否保留 `status != ok` 的记录。
- `--provider`：可选 provider 过滤（如 `aws` / `azure` / `gcp`）。
- `--resource-type`：可选资源类型过滤（如 `vm` / `storage` / `db`）。
- `--endpoint`：Document Intelligence endpoint（可用环境变量替代）。
- `--key`：Document Intelligence key（可用环境变量替代）。
- `--model-id`：模型 ID（默认 `prebuilt-layout`）。

## 关键输出字段
- `quantity`：优先从同一文本行中的 `qty/quantity/count/x` 规则解析，缺失时默认 `1.0`。
- `instance_type`：当 profile=`aws_vm` 时，用于后续 `vm-aws-instance-to-config`。

## 执行规则
1. 后续流程只消费脚本输出，不要自行补猜缺失字段。
2. `extracted_rows=0` 时，明确告知“当前 PDF 未识别到可用实例型号”。
3. 若需提升准确率，优先升级抽取规则或替换为自定义 DI 模型，不要在后续 skill 做隐式修正。
4. 保持输出为 CSV + JSON 摘要，便于链式调用与自动化编排。

## 输出示例
```json
{
  "status": "ok",
  "input_pdf": "input/sample_input.pdf",
  "output_csv": "output/extracted_inputs_from_pdf.csv",
  "profile": "aws_vm",
  "engine": "azure_document_intelligence",
  "filters": {
    "provider": null,
    "resource_type": null,
    "include_review": false
  },
  "total_rows": 20,
  "eligible_rows": 16,
  "extracted_rows": 16,
  "required_for_next_skill": ["instance_type"],
  "recommended_columns": ["provider", "resource_type", "instance_name", "quantity", "vcpu", "memory_gb", "os", "region_input", "workload"]
}
```

````
