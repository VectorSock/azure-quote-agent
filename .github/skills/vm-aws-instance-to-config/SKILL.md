---
name: vm-aws-instance-to-config
description: 将 AWS 实例型号（如 m6a.4xlarge）解析为标准 VM 配置指标（vCPU、内存、架构、画像、SAP 可行性），用于迁移评估与报价前置分析。
---

# 技能：AWS 实例名到 VM 配置指标

## 概述
当用户提供 AWS 实例型号（例如 `m6a.4xlarge`）并希望得到结构化配置信息时，使用此技能。

此技能会输出可直接用于后续流程的标准化指标，包括：
- 计算规格：`vcpu`、`memory_gb`
- 估算元信息：`memory_ratio`、`size_rule_confidence`、`memory_rule_confidence`
- CPU 信息：`cpu_arch`、`cpu_vendor`、`requires_intel`
- 工作负载画像：`profile`、`is_gpu_accelerated`、`is_burstable`
- 附加判断：`has_local_temp_disk`、`is_ebs_optimized`、`is_network_optimized`、`sap_possible`

## 何时使用
- 用户询问“这个 AWS 实例是什么配置”。
- 需要先把实例型号变成结构化规格，再做 Azure 映射或价格对比。
- 需要做 SAP 可行性初筛（仅规则级判断，不代表官方认证）。

## 运行方式
所有路径默认基于当前工作目录。

### 单条解析
`python .github/skills/vm-aws-instance-to-config/scripts/aws_instance_indicators.py --instance-type "m6a.4xlarge"`

### 批量解析（CSV）
`python .github/skills/vm-aws-instance-to-config/scripts/aws_instance_indicators.py --input-file "input/aws_types.csv" --column "instance_type" --output "output/aws_indicators.csv"`

## 参数说明
- `--instance-type`：单条 AWS 实例型号。
- `--input-file`：批量输入 CSV。
- `--column`：批量输入中实例型号列名（默认 `instance_type`）。
- `--output`：批量输出路径（默认 `output/aws_instance_indicators.csv`）。

## 执行规则
1. 仅依据脚本输出回答，不要自行编造指标值。
2. 若脚本返回 `status=unrecognized_format`，应明确告知用户实例名不符合可解析格式。
3. `sap_possible=true` 仅表示“启发式可行”，不是 SAP 官方支持结论。
4. 批量模式会保留输入 CSV 的全部原始列；解析结果以新增列 append，若同名会写入 `parsed_*` 列避免覆盖。

## 输出示例
```json
{
  "input_instance_type": "m6a.4xlarge",
  "status": "ok",
  "series": "m",
  "generation": 6,
  "options": "a",
  "size": "4xlarge",
  "vcpu": 16,
  "memory_gb": 64.0,
  "memory_ratio": 4.0,
  "cpu_arch": "x86_64",
  "cpu_vendor": "amd",
  "requires_intel": false,
  "has_local_temp_disk": false,
  "is_ebs_optimized": false,
  "is_gpu_accelerated": false,
  "is_network_optimized": false,
  "is_burstable": false,
  "profile": "general",
  "sap_possible": true,
  "size_rule_confidence": "high",
  "memory_rule_confidence": "high",
  "matched_by": "aws_naming_rules"
}
```

## 参考材料
- `references/guide-size-to-vcpu.md`
- `references/guide-memory-from-family.md`
- `references/guide-sap-prescreen.md`
- `references/guide-hidden-signals.md`
