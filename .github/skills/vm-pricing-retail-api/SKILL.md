---
name: vm-pricing-retail-api
description: 查询 AWS/Azure 官方零售价格并返回 VM 的 PayGo、1Y RI、3Y RI 小时单价，适用于跨云报价与成本对比。
---

# 技能：VM 官方零售定价查询

## 概述
当用户需要比较 AWS 与 Azure 的虚拟机价格时，使用此技能直接调用官方 Retail API 获取定价。

技能输出包含：
- Azure：PayGo / 1Y RI / 3Y RI（小时价）
- AWS：PayGo / 1Y RI / 3Y RI（小时价）
- 来源 URL、生效时间、命中策略与错误信息

## 何时使用
- 用户要求“同配置 AWS vs Azure 价格对比”。
- 报价流程中需要用官方公开零售价做快速估算。
- 需要验证某个 SKU 在指定 Region 的价格基线。

## 运行方式
所有路径默认基于当前工作目录。

### 维护任务（AWS EC2 Bulk Offer 刷新）
触发脚本位于 maintenance skill：

`python .github/skills/global-maintenance/scripts/refresh_aws_ec2_bulk_offers.py`

该任务的产出资产固定写入：

`.github/skills/vm-pricing-retail-api/assets/aws_ec2_bulk_offers`

### 标准查询（AWS + Azure）
`python .github/skills/vm-pricing-retail-api/scripts/fetch_vm_prices.py --aws-instance-type "m6a.4xlarge" --aws-region "ap-southeast-1" --azure-sku "Standard_D16as_v5" --azure-region "southeastasia" --os linux`

### 仅查询 Azure
`python .github/skills/vm-pricing-retail-api/scripts/fetch_vm_prices.py --azure-sku "Standard_D16as_v5" --azure-region "southeastasia" --os linux --skip-aws`

### 仅查询 AWS
`python .github/skills/vm-pricing-retail-api/scripts/fetch_vm_prices.py --aws-instance-type "m6a.4xlarge" --aws-region "ap-southeast-1" --os linux --skip-azure`

### 批量查询（CSV）
`python .github/skills/vm-pricing-retail-api/scripts/fetch_vm_prices.py --input-file "input/vm_pricing_input.csv" --output "output/vm_pricing_results.csv"`

## 参数说明
- `--aws-instance-type`：AWS 实例型号（如 `m6a.4xlarge`）。
- `--aws-region`：AWS Region（如 `ap-southeast-1`）。
- `--azure-sku`：Azure VM SKU（如 `Standard_D16as_v5`）。
- `--azure-region`：Azure Region（如 `southeastasia`）。
- `--os`：`linux` 或 `windows`（默认 `linux`）。
- `--timeout`：HTTP 超时时间秒数（默认 `30`）。
- `--skip-aws`：跳过 AWS 查询。
- `--skip-azure`：跳过 Azure 查询。
- `--input-file`：批量输入 CSV；支持列名：
  - AWS：`aws_instance_type`（或 `instance_type`）、`aws_region`（或 `mapped_aws_region` / `region_aws`）
  - Azure：`azure_sku`（或 `primary_sku`）、`azure_region`（或 `mapped_azure_region` / `region_azure`）
  - OS：`os`（可选，默认 `linux`）
- `--output`：批量输出 CSV（默认 `output/vm_pricing_results.csv`）。

## 凭证要求
- Azure 零售价格接口为公开 API，无需额外凭证。
- AWS 查询基于 AWS Pricing API（`GetProducts`），需要有效 AWS 凭证（例如环境变量、IAM Role 或 `~/.aws/credentials`）。
- 若当前环境未配置 AWS 凭证，请使用 `--skip-aws`，否则可能返回 `Unable to locate credentials`。

## 执行规则
1. 只能依据脚本输出回答价格，不要自行猜测单价。
2. 若某侧返回 `status=not_found` 或 `status=error`，应明确告知用户该价格未命中。
3. RI 小时价为标准化估算值；对外说明时需标注其计算口径。
4. AWS 侧使用 AWS Pricing API（query-based / GetProducts），不再下载整区全量 offer JSON。
5. RI 小时折算统一口径：`year_hours = 12 * 730`；`hourly = total_term_price / (term_years * 12 * 730)`。
6. 批量模式下若某行缺少某云的必需字段，该云会被标记为 `skipped`；两云都缺失则该行标记 `invalid_input`。

## 输出示例
```json
{
  "status": "ok",
  "input": {
    "aws_instance_type": "m6a.4xlarge",
    "aws_region": "ap-southeast-1",
    "azure_sku": "Standard_D16as_v5",
    "azure_region": "southeastasia",
    "os": "linux"
  },
  "azure": {
    "status": "ok",
    "paygo_hourly_usd": 0.97,
    "ri_1y_hourly_usd": 0.62,
    "ri_3y_hourly_usd": 0.45
  },
  "aws": {
    "status": "ok",
    "paygo_hourly_usd": 0.92,
    "ri_1y_hourly_usd": 0.59,
    "ri_3y_hourly_usd": 0.42
  }
}
```

## 参考材料
- `references/guide-azure-meter-selection.md`
- `references/guide-aws-sku-matching.md`
- `references/guide-ri-normalization.md`
