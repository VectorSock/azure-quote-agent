# AWS EC2 SKU Match Rules

本技能基于 AWS EC2 Offer 文件匹配 SKU：

## 严格匹配（strict）
- `instanceType` 精确相等
- `operatingSystem` 精确相等
- `preInstalledSw = NA`
- `tenancy = Shared`
- `capacitystatus = Used`
- `operation = RunInstances`

## 宽松匹配（relaxed）
若 strict 未命中，允许同 `instanceType + operatingSystem` 的首个 SKU。

## 返回字段
- `sku`
- `sku_match_mode`: `strict | relaxed | none`

## 说明
- 若 `sku_match_mode=none`，表示该实例/系统在当前 region 公开定价数据中未命中。
