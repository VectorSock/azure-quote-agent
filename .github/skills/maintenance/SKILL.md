---
name: maintenance
description: 维护类触发脚本集合（可由 GitHub Action 定期触发），用于刷新跨 skill 资产与知识库更新任务。
---

# 技能：Maintenance 维护任务

## 概述
该 skill 用于集中放置“维护/触发类脚本”。

设计规则：
- 触发脚本统一放在 `maintenance/scripts/`。
- 业务资产必须写回对应 skill 的 `assets/` 目录，不落在 maintenance 下。

## 当前包含任务
- AWS EC2 Bulk Offer 刷新：
  - 脚本：`scripts/refresh_aws_ec2_bulk_offers.py`
  - 输出资产：`.github/skills/vm-pricing-retail-api/assets/aws_ec2_bulk_offers`

## 运行方式
`python .github/skills/maintenance/scripts/refresh_aws_ec2_bulk_offers.py`

可选参数示例：
`python .github/skills/maintenance/scripts/refresh_aws_ec2_bulk_offers.py --regions-excel .github/skills/region-mapping/assets/get_regions.xlsx --output-root .github/skills/vm-pricing-retail-api/assets/aws_ec2_bulk_offers`

## 未来扩展
- 可在 `maintenance/scripts/` 下新增 KB 更新触发脚本等维护任务。
- 若接入 GitHub Actions 定时触发，建议由 workflow 调用 maintenance 脚本，但产出仍归档到目标 skill 的 `assets/`。
