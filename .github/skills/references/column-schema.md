# Column Schema (Canonical)

本文件定义跨 skill 的 canonical 列名，减少别名歧义。

## 核心输入列
- provider
- resource_type
- instance_name
- instance_type
- quantity
- vcpu
- memory_gb
- os
- region_input

## Region Mapping 输出
- mapped_city
- mapped_aws_region
- mapped_azure_region
- mapped_gcp_region
- mapped_by

说明：后续 skill 推荐优先读取 mapped_azure_region，而不是通用 region。

## Azure 映射输出
- primary_sku
- azure_sku（canonical，等于 primary_sku）
- fallback_sku（单值，第一回退）
- fallback_skus（多值，| 分隔）
- sap_sku

## 定价输入约定
- AWS: aws_instance_type, aws_region
- Azure: azure_sku, azure_region
- OS: os

兼容别名（仅向后兼容，不建议新增依赖）：
- aws_instance_type <- instance_type
- aws_region <- mapped_aws_region, region_aws
- azure_sku <- primary_sku
- azure_region <- mapped_azure_region, region_azure

## 报价输出约定
- 价格列：AWS_paygo, AWS_1YRI, AWS_3YRI, Azure_paygo, Azure_1YRI, Azure_3YRI
- SAP 价格列：Azure_SAP_paygo, Azure_SAP_1YRI, Azure_SAP_3YRI
