# 跨 Skill 列名对接契约（VM 报价流水线）

本文档定义 VM 报价流水线中各 skill 的关键输入/输出列契约，避免“上游有值、下游读不到”的问题。

## 流水线顺序
1. `input-excel-extraction`
2. `global-region-mapping`
3. `vm-aws-instance-to-config`
4. `vm-config-to-azure-instance`
5. `vm-pricing-retail-api`
6. `global-quote-writer`

## Step 1: input-excel-extraction

### 关键输出列
- `nrm_id`
- `provider`
- `resource_type`
- `instance_name`
- `instance_type`（`aws_vm` profile）
- `quantity`
- `vcpu`
- `memory_gb`
- `os`
- `region_input`
- `status`
- `status_reason`

### 下游依赖
- `global-region-mapping` 依赖：`region_input`
- `vm-aws-instance-to-config` 依赖：`instance_type`

## Step 2: global-region-mapping

### 追加输出列
- `mapped_city`
- `mapped_aws_region`
- `mapped_azure_region`
- `mapped_gcp_region`
- `mapped_by`

### 下游依赖
- `vm-pricing-retail-api` 依赖：`mapped_aws_region`、`mapped_azure_region`

## Step 3: vm-aws-instance-to-config

### 原生新增列
- `parsed_status`
- `parsed_vcpu`
- `parsed_memory_gb`
- `cpu_arch`
- `cpu_vendor`
- `is_burstable`
- `is_gpu_accelerated`
- `has_local_temp_disk`
- `is_network_optimized`
- `profile`

### 对接约定
- `vm-config-to-azure-instance` 会优先读取：`vcpu` / `memory_gb`
- 若为空，会自动回退读取：`parsed_vcpu` / `parsed_memory_gb`

## Step 4: vm-config-to-azure-instance

### 输入列（支持别名）
- 规格：`vcpu` 或 `parsed_vcpu`；`memory_gb` 或 `parsed_memory_gb`
- 能力：
  - `cpu_vendor` 或 `parsed_cpu_vendor`
  - `cpu_arch` 或 `parsed_cpu_arch`
  - `burstable` 或 `is_burstable`
  - `gpu` 或 `is_gpu_accelerated`
  - `local_temp_disk` 或 `has_local_temp_disk`
  - `network_optimized` 或 `is_network_optimized`

### 输出列
- `primary_sku`
- `fallback_skus`
- `mapping_confidence`
- `matched_by`
- `assumptions`
- `error`

## Step 5: vm-pricing-retail-api

### 单条模式参数
- AWS：`aws_instance_type` + `aws_region`
- Azure：`azure_sku` + `azure_region`
- 公共：`os`

### 批量模式输入列（CSV）
- AWS：`aws_instance_type`（或 `instance_type`），`aws_region`（或 `mapped_aws_region` / `region_aws`）
- Azure：`azure_sku`（或 `primary_sku`），`azure_region`（或 `mapped_azure_region` / `region_azure`）
- OS：`os`（可选，默认 `linux`）

### 批量模式输出追加列
- `pricing_status`
- `azure_status`、`azure_paygo_hourly_usd`、`azure_ri_1y_hourly_usd`、`azure_ri_3y_hourly_usd`
- `aws_status`、`aws_paygo_hourly_usd`、`aws_ri_1y_hourly_usd`、`aws_ri_3y_hourly_usd`
- `pricing_error`
- `pricing_result_json`

## Step 6: global-quote-writer

### 关键输入对象
- 顶层：`summary`、`line_items`
- 建议补充：`assumptions`、`evidence`

### line_items 关键字段
- 资源信息：`item_id`、`provider`、`resource_type`、`quantity`、`sku/os`、`region`、`region_azure`、`primary_sku`
- 单价：`unit_price_AWS_paygo`、`unit_price_Azure_paygo`
- 月成本：`line_total_AWS_paygo`、`line_total_Azure_paygo`、`line_total_AWS_1YRI`、`line_total_AWS_3YRI`、`line_total_Azure_1YRI`、`line_total_Azure_3YRI`
- 复核：`review_flag`、`review_reason`、`evidence_id`

## 维护建议
- 新增字段时优先“新增别名，不破坏旧列名”。
- 每次修改任一步列名后，必须同步更新：
  1) 上游 skill 的 SKILL.md
  2) 下游 skill 的 SKILL.md
  3) 本契约文档
