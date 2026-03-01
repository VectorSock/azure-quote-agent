# 输入 Schema（summary / line_items / assumptions / evidence）

本文件定义 `write_quote_excel.py --input-json` 的结构化输入。

## 顶层结构

```json
{
  "summary": {},
  "line_items": [],
  "assumptions": [],
  "evidence": []
}
```

- `summary`：必填，对象。用于总体金额、币种、周期、备注等。
- `line_items`：必填，数组。每个元素为一条可计费明细。
- `assumptions`：可选，数组或对象。用于口径、默认值、边界说明。
- `evidence`：可选，数组。用于来源链接、API 返回片段、规则文件引用。

## line_items 推荐字段

### 通用字段
- `item_id`
- `provider`（aws/azure/gcp）
- `resource_type`（或 `service`）
- `quantity`
- `sku/os`（或 `sku_os` / `os` / `sku`）
- `region`
- `region_azure`
- `primary_sku`（Azure 映射主 SKU）
- `fallback_skus`
- `sap_sku`
- `billing_unit`（或 `unit`）

### 单价字段（小时）
- `unit_price_AWS_paygo`
- `unit_price_Azure_paygo`（兼容 `unit_price_hourly`）

### 月度总价字段
- `line_total_AWS_paygo`（兼容 `monthly_cost_AWS_paygo` / `monthly_cost`）
- `line_total_Azure_paygo`（兼容 `monthly_cost_Azure_paygo`）
- `line_total_AWS_1YRI`（兼容 `monthly_cost_AWS_1YRI`）
- `line_total_AWS_3YRI`（兼容 `monthly_cost_AWS_3YRI`）
- `line_total_Azure_1YRI`（兼容 `monthly_cost_Azure_1YRI`）
- `line_total_Azure_3YRI`（兼容 `monthly_cost_Azure_3YRI`）

### 复核与证据字段
- `review_flag`
- `review_reason`（兼容 `notes`）
- `evidence_id`

## assumptions 示例

```json
[
  {"key":"monthly_hours","value":730,"source":"pricing-policy","notes":"统一口径"},
  {"key":"exchange_rate","value":"not_applied","source":"scope","notes":"币种转换不在本技能范围"}
]
```

## evidence 示例

```json
[
  {"evidence_type":"api","ref":"azure-retail-api","detail":"meterName=..."},
  {"evidence_type":"rule","ref":"ri-calculation-rules.md","detail":"3Y hourly = retailPrice/(24*365*3)"}
]
```

## 校验原则

- 缺失 `summary` 或 `line_items`：视为无效输入。
- 不识别字段可保留，不会阻断写入。
- 严禁在缺失关键价格字段时推断并填充虚构值。
