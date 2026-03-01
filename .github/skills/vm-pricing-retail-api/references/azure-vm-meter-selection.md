# Azure VM Meter Selection

本技能在 Azure Retail API 中使用以下过滤条件：

- `serviceName == Virtual Machines`
- `armRegionName == <azure_region>`
- `armSkuName == <azure_sku>`

## 选择逻辑
1. 先按 `type=Consumption` 提取 PayGo 候选。
2. 再按 `type=Reservation` 提取 RI 候选。
3. 过滤明显非基线条目（Spot、Promotion、Dedicated Host 等）。
4. 按 OS 匹配：
   - Linux：排除包含 `windows` 的条目
   - Windows：优先包含 `windows` 的条目

## 输出
- `paygo_hourly_usd`
- `ri_1y_hourly_usd`
- `ri_3y_hourly_usd`
