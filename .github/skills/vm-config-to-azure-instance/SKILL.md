---
name: vm-config-to-azure-instance
description: 将结构化 VM 配置（vCPU、内存、架构与业务上下文）映射为 Azure VM 候选，并在需要时给出 SAP/HANA 认证机型。
---

# 技能：VM 配置到 Azure 实例映射

## 概述
输入结构化规格（vcpu、memory_gb）与业务上下文，输出 Azure 候选：
- primary_sku（同时输出 canonical 列 azure_sku）
- fallback_sku / fallback_skus
- sap_sku（仅规则要求时）
- support gate 与 ranking 明细

脚本主入口（canonical）：
python .github/skills/vm-config-to-azure-instance/scripts/vm_config_to_azure_instance.py

## Quick Start
单条映射：

python .github/skills/vm-config-to-azure-instance/scripts/vm_config_to_azure_instance.py --vcpu 16 --memory-gb 64 --cpu-vendor amd

SAP 场景：

python .github/skills/vm-config-to-azure-instance/scripts/vm_config_to_azure_instance.py --vcpu 32 --memory-gb 256 --system S4 --env PRD --workload-type DB --sap-workload true

批量映射：

python .github/skills/vm-config-to-azure-instance/scripts/vm_config_to_azure_instance.py --input-file input/vm_specs.csv --output output/azure_vm_candidates.csv

## Advanced Options
- --app-db-policy: strict | balanced | cost-first
- --catalog-file: 外置 SAP SKU 目录
- --azure-region / --os-name / --pam-supported: support gate 信号
- --required-iops / --required-network-mbps / --required-disk-throughput-mbps: ranking 性能信号
- --prefer-amd / --fallback-count: 候选扩展策略

批量最低输入：
- vcpu 或 parsed_vcpu
- memory_gb 或 parsed_memory_gb

推荐输入：
- system, env, workload_type, SAP_workload
- mapped_azure_region 或 azure_region（canonical 推荐 mapped_azure_region）

## 决策流程
1. support gate：PAM / SAP Note / 区域 / OS 约束校验
2. ranking：按 policy 对 fit + perf + cost 综合排序

## 列名规范
统一列名请参考：
.github/skills/references/column-schema.md
