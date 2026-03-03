---
name: input-excel-extraction
description: 从原始 Excel 中做第一步结构化抽取，输出标准化中间数据供后续各类云资源 skill 复用。
---

# 技能：Excel 原始数据第一步抽取

## 概述
当用户提供原始报价单或资源清单 Excel 时，先用本技能做“第一步抽取”，把杂乱列名和半结构化信息转成可复用的标准中间数据。

本技能会：
- 读取 Excel 并标准化列名
- 生成统一记录（provider、resource_type、instance_name、quantity、region、status 等）
- 按 `profile` 输出针对后续 skill 的最小输入集

## 何时使用
- 任何“从 Excel 开始”的流程都先用它做入口抽取。
- 你需要把同一份原始数据复用于多个后续 skill（VM、数据库、存储、网络等）。
- 你希望先统一质量门槛（`status` / `status_reason`），再做后续映射与定价。

## 运行方式
所有路径默认基于当前工作目录。

### 标准抽取（默认 profile: `aws_vm`）
`python .github/skills/input-excel-extraction/scripts/extract_excel_inputs.py --input-excel "input/sample_input.xlsx" --output "output/extracted_inputs.csv"`

### 通用抽取（保留所有资源类型）
`python .github/skills/input-excel-extraction/scripts/extract_excel_inputs.py --input-excel "input/sample_input.xlsx" --profile all_resources --output "output/extracted_all_resources.csv"`

### 过滤抽取（按 provider / resource_type）
`python .github/skills/input-excel-extraction/scripts/extract_excel_inputs.py --input-excel "input/sample_input.xlsx" --profile all_resources --provider aws --resource-type vm --output "output/aws_vm_rows.csv"`

## 参数说明
- `--input-excel`：输入 Excel 路径（`.xlsx` / `.xls`）。
- `--output`：输出 CSV 路径（默认 `output/extracted_inputs.csv`）。
- `--profile`：抽取配置（当前支持 `aws_vm`、`all_resources`）。
- `--include-review`：是否保留 `status != ok` 的记录。
- `--provider`：可选 provider 过滤（如 `aws` / `azure` / `gcp`）。
- `--resource-type`：可选资源类型过滤（如 `vm` / `storage` / `db`）。

## 关键输出字段
- `quantity`：实例数量，若输入存在 `quantity/qty/count/数量/instances` 等列会自动识别并透传。

## 执行规则
1. 后续流程只消费脚本输出，不要自行补猜缺失字段。
2. `extracted_rows=0` 时，明确告知“当前 profile 未命中可用记录”。
3. 需要新增资源抽取能力时，优先在脚本中新增 profile extractor，而不是改写现有 profile 规则。
4. 若配置单 Excel 中写"EC2/ECS/Compute Engine"等云厂商产品名，均应归一化为 `vm`。
5. `os` 会做内置归一化：`suse`→`linux`、`centos`→`linux`、`windows with sql*`→`windows`。

## 输出示例
```json
{
  "status": "ok",
  "input_excel": "input/sample_input.xlsx",
  "output_csv": "output/extracted_inputs.csv",
  "profile": "aws_vm",
  "filters": {
    "provider": null,
    "resource_type": null,
    "include_review": false
  },
  "total_rows": 120,
  "eligible_rows": 52,
  "extracted_rows": 34,
  "required_for_next_skill": ["instance_type"],
  "recommended_columns": ["provider", "resource_type", "instance_name", "quantity", "vcpu", "memory_gb", "os", "region_input", "workload"]
}
```

## 扩展约定（给未来模块）
- 新增资源抽取时，采用 profile 注册方式扩展（例如 `aws_rds`、`azure_disk`）。
- 共享字段优先复用基础列：`provider`、`resource_type`、`region_*`、`status*`。
- 保持输出为 CSV + JSON 摘要，便于链式调用与自动化编排。
