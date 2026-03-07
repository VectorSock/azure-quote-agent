---
name: global-region-mapping
description: 标准化模糊位置并映射到 AWS/Azure/GCP 官方 Region ID。
---

# 技能：云区域标准化映射

## 概述
将城市名、历史区域名或非标准地域文本映射为标准云区域，支持单条和批量模式。

## 运行方式
单条：

python .github/skills/global-region-mapping/scripts/region_mapping.py --location Singapore

批量：

python .github/skills/global-region-mapping/scripts/region_mapping.py --input-file input/locations.csv --column region --output output/mapped_results.csv

## 输出列
- mapped_city
- mapped_aws_region
- mapped_azure_region
- mapped_gcp_region
- mapped_by

## 执行规则
1. 以脚本输出为准，不臆测 Region ID。
2. matched_by=fallback 时需提示结果低可靠。

## 列名规范
统一列名请参考：
.github/skills/references/column-schema.md
