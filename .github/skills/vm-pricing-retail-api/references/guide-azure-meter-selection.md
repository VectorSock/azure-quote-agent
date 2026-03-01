# Reference: Azure Meter Selection

## Read When
- Need Azure VM PayGo / RI prices from Retail API for a specific `armSkuName` + region.

## Query Scope
- `serviceName == 'Virtual Machines'`
- `armRegionName == <azure_region>`
- `armSkuName == <azure_sku>`

## Selection Rules
1. Read all pages (`NextPageLink`) before choosing a price.
2. Separate by `type`:
   - `Consumption` for PayGo
   - `Reservation` for RI
3. Exclude non-baseline lines (Spot, Promotion, Dedicated Host, Dev/Test, etc.).
4. Apply OS filter:
   - `linux`: exclude records containing `windows`
   - `windows`: keep records containing `windows`
5. If multiple valid records remain, pick the lowest applicable price.

## Output Contract
- `paygo_hourly_usd`
- `ri_1y_hourly_usd`
- `ri_3y_hourly_usd`
- Include source URL and meter metadata for traceability.

## Notes for LLM
- If no valid meter found, return `status=not_found` (do not estimate).
- Explain that Retail API coverage can vary by SKU/region/time.
