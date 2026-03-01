---
name: vm-config-to-azure-instance
description: 将结构化 VM 配置（vCPU、内存、架构与能力特征）映射为 Azure VM 实例候选（primary + fallback），用于迁移评估与报价前置。
---

# 技能：VM 配置到 Azure 实例映射

## 概述
当用户已经有结构化 VM 规格（例如 `vcpu=16`、`memory_gb=64`）并希望快速得到 Azure 实例候选时，使用此技能。

技能输出包括：
- `primary_sku`：首选 Azure VM SKU
- `fallback_skus`：回退候选（按优先级）
- `mapping_confidence`：映射置信度（启发式）
- `assumptions`：本次映射采用的默认假设

## 何时使用
- 在跨云迁移评估中，需要把源端 VM 规格映射到 Azure 实例。
- 在报价前，需要先将用户输入配置标准化到 Azure SKU。
- 当用户未提供明确 Azure 型号，但给了 CPU/内存/能力特征。

## 运行方式
所有路径默认基于当前工作目录。

### 单条映射
`python skills/vm-config-to-azure-instance/scripts/vm-config-to-azure-instance.py --vcpu 16 --memory-gb 64 --cpu-vendor amd`

### 单条映射（包含能力特征）
`python skills/vm-config-to-azure-instance/scripts/vm-config-to-azure-instance.py --vcpu 8 --memory-gb 16 --burstable --network-optimized`

### 批量映射（CSV）
`python skills/vm-config-to-azure-instance/scripts/vm-config-to-azure-instance.py --input-file "input/vm_specs.csv" --output "output/azure_vm_candidates.csv"`

## 参数说明
- `--vcpu`：vCPU 数（必填，单条模式）。
- `--memory-gb`：内存（GB，必填，单条模式）。
- `--cpu-vendor`：`amd` / `intel` / `arm` / `unknown`（默认 `unknown`）。
- `--cpu-arch`：`x86_64` / `arm64`（默认 `x86_64`）。
- `--burstable`：是否突发型。
- `--gpu`：是否 GPU 型。
- `--local-temp-disk`：是否需要本地临时盘。
- `--network-optimized`：是否网络增强。
- `--prefer-amd`：倾向使用 AMD（默认启用）。
- `--fallback-count`：回退候选数量（默认 `3`）。
- `--input-file`：批量输入 CSV。
- `--output`：批量输出 CSV（默认 `output/azure_instance_mapping.csv`）。

## 执行规则
1. 必须以脚本实际输出为准，不要自行构造 SKU。
2. 若输出 `status=invalid_input`，应提示用户补齐或修正配置。
3. 若 `mapping_confidence` 偏低，应提示用户人工复核。

## 输出示例
```json
{
  "status": "ok",
  "input": {
    "vcpu": 16,
    "memory_gb": 64.0,
    "cpu_vendor": "amd",
    "cpu_arch": "x86_64",
    "burstable": false,
    "gpu": false,
    "local_temp_disk": false,
    "network_optimized": false
  },
  "primary_sku": "Standard_E16as_v5",
  "fallback_skus": [
    "Standard_D16as_v5",
    "Standard_E16s_v5",
    "Standard_F16s_v2"
  ],
  "mapping_confidence": 0.84,
  "matched_by": "shape_and_feature_policy",
  "assumptions": [
    "version_policy_applied",
    "premium_storage_suffix_default=s"
  ]
}
```

## 参考材料
- `references/family-mapping-policy.md`
- `references/feature-suffix-policy.md`
- `references/fallback-priority-policy.md`
