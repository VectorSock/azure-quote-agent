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

### 标准查询（AWS + Azure）
`python skills/vm-pricing-retail-api/scripts/fetch_vm_prices.py --aws-instance-type "m6a.4xlarge" --aws-region "ap-southeast-1" --azure-sku "Standard_D16as_v5" --azure-region "southeastasia" --os linux`

### 仅查询 Azure
`python skills/vm-pricing-retail-api/scripts/fetch_vm_prices.py --azure-sku "Standard_D16as_v5" --azure-region "southeastasia" --os linux --skip-aws`

### 仅查询 AWS
`python skills/vm-pricing-retail-api/scripts/fetch_vm_prices.py --aws-instance-type "m6a.4xlarge" --aws-region "ap-southeast-1" --os linux --skip-azure`

## 参数说明
- `--aws-instance-type`：AWS 实例型号（如 `m6a.4xlarge`）。
- `--aws-region`：AWS Region（如 `ap-southeast-1`）。
- `--azure-sku`：Azure VM SKU（如 `Standard_D16as_v5`）。
- `--azure-region`：Azure Region（如 `southeastasia`）。
- `--os`：`linux` 或 `windows`（默认 `linux`）。
- `--timeout`：HTTP 超时时间秒数（默认 `30`）。
- `--skip-aws`：跳过 AWS 查询。
- `--skip-azure`：跳过 Azure 查询。

## 执行规则
1. 只能依据脚本输出回答价格，不要自行猜测单价。
2. 若某侧返回 `status=not_found` 或 `status=error`，应明确告知用户该价格未命中。
3. RI 小时价为标准化估算值；对外说明时需标注其计算口径。

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
- `references/azure-vm-meter-selection.md`
- `references/aws-ec2-sku-match-rules.md`
- `references/ri-calculation-rules.md`
