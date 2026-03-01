---
name: vm-aws-input-from-excel
description: 从报价Excel中提取可用于AWS实例解析的输入参数（instance_type及上下文），用于衔接 vm-aws-instance-to-config。
---

# 技能：从 Excel 提取 AWS VM 输入参数

## 概述
当用户给你一个报价或资源清单 Excel，并希望后续调用 `vm-aws-instance-to-config` 时，先使用本技能提取干净的 AWS VM 输入参数。

本技能会：
- 读取 Excel 并标准化列名
- 识别 VM 行与 AWS 行
- 输出可直接用于实例解析的 `instance_type` 列

## 何时使用
- 用户上传了云资源清单，但字段名不统一。
- 你需要批量把 AWS 实例型号送入 `vm-aws-instance-to-config`。
- 你希望先过滤掉非 VM、非 AWS 或无实例名的行。

## 运行方式
所有路径默认基于当前工作目录。

### 提取为 CSV
`python skills/vm-aws-input-from-excel/scripts/extract_vm_aws_inputs.py --input-excel "input/sample_input.xlsx" --output "output/aws_vm_inputs.csv"`

### 保留 review 行（默认会过滤）
`python skills/vm-aws-input-from-excel/scripts/extract_vm_aws_inputs.py --input-excel "input/sample_input.xlsx" --output "output/aws_vm_inputs.csv" --include-review`

## 参数说明
- `--input-excel`：输入 Excel 路径（`.xlsx`）。
- `--output`：输出 CSV 路径（默认 `output/aws_vm_inputs.csv`）。
- `--config`：配置文件路径（默认 `config/defaults.yaml`）。
- `--regions`：地域映射文件（默认 `data/get_regions.xlsx`）。
- `--include-review`：是否保留 `status != ok` 的记录。

## 执行规则
1. 只根据脚本输出进行后续处理，不要自行猜测缺失实例名。
2. 如果结果为空，应明确告知用户“未提取到可用 AWS VM 行”。
3. 若要提升提取率，建议用户在 Excel 中补充 `provider`、`instance_name`、`resource_type`。

## 输出示例
```json
{
  "status": "ok",
  "input_excel": "input/sample_input.xlsx",
  "output_csv": "output/aws_vm_inputs.csv",
  "total_rows": 120,
  "extracted_rows": 34,
  "required_for_next_skill": ["instance_type"],
  "recommended_columns": ["provider", "resource_type", "instance_name", "vcpu", "memory_gb", "os", "region", "workload"]
}
```

## 给 vm-aws-instance-to-config 的关键参数
- 必需：`instance_type`（来自 Excel 的 `instance_name`）
- 推荐补充：`vcpu`、`memory_gb`、`os`、`region`、`workload`
