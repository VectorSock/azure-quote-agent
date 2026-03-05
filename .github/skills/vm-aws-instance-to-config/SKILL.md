---
name: vm-aws-instance-to-config
description: 将 AWS 实例型号解析为标准 VM 配置指标（vCPU、内存、架构、画像、SAP 可行性）。
---

# 技能：AWS 实例名到 VM 配置指标

## 概述
输入 AWS 实例型号（如 m6a.4xlarge），输出结构化指标供后续 Azure 映射与定价使用。

## 运行方式
单条：

python .github/skills/vm-aws-instance-to-config/scripts/aws_instance_indicators.py --instance-type m6a.4xlarge

批量：

python .github/skills/vm-aws-instance-to-config/scripts/aws_instance_indicators.py --input-file input/aws_types.csv --column instance_type --output output/aws_indicators.csv

## 执行规则
1. 仅依据脚本输出回答，不编造指标。
2. status=unrecognized_format 时需明确提示实例名不可解析。
3. sap_possible 仅为启发式可行性，不代表官方认证。

## 列名规范
统一列名请参考：
.github/skills/references/column-schema.md
