---
name: vm-pricing-retail-api
description: 查询 AWS/Azure 官方零售价格并返回 VM 的 PayGo、1Y RI、3Y RI 小时单价。
---

# 技能：VM 官方零售定价查询

## 概述
用于 AWS 与 Azure VM 小时价查询与对比，输出 PayGo、1Y RI、3Y RI。

## 运行方式
标准查询：

python .github/skills/vm-pricing-retail-api/scripts/fetch_vm_prices.py --aws-instance-type m6a.4xlarge --aws-region ap-southeast-1 --azure-sku Standard_D16as_v5 --azure-region southeastasia --os linux

批量查询：

python .github/skills/vm-pricing-retail-api/scripts/fetch_vm_prices.py --input-file input/vm_pricing_input.csv --output output/vm_pricing_results.csv

## 输入列（批量）
- AWS: aws_instance_type, aws_region
- Azure: azure_sku（canonical，兼容 primary_sku）, azure_region
- OS: os

## 执行规则
1. 价格结果仅以脚本返回为准。
2. AWS 侧优先 GetProducts；若 boto3 不可用或 GetProducts 失败，自动回退 offer file 模式。
3. RI 小时折算口径：hourly = total_term_price / (term_years * 12 * 730)。

## AWS EC2 Offer 数据维护
- 本地刷新脚本：
python scripts/maintenance/refresh_aws_ec2_bulk_offers.py
- 可选参数示例：
python scripts/maintenance/refresh_aws_ec2_bulk_offers.py --regions-excel .github/skills/global-region-mapping/assets/get_regions.xlsx --output-root .github/skills/vm-pricing-retail-api/assets/aws_ec2_bulk_offers
- GitHub Actions：
.github/workflows/refresh-aws-ec2-bulk-offers.yml

## 列名规范
统一列名请参考：
.github/skills/references/column-schema.md
