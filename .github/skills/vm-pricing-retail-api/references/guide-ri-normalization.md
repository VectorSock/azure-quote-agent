# Reference: RI Hourly Normalization

## Read When
- Need comparable hourly RI prices across cloud providers.

## Azure RI Rule
- Retail API reservation `retailPrice` is term total.
- Normalize to hourly:
  - `1Y = total / (24*365*1)`
  - `3Y = total / (24*365*3)`

## AWS RI Rule
- Use `Reserved` terms with:
  - `PurchaseOption = No Upfront`
  - `OfferingClass = standard`
  - lease `1yr` or `3yr`
- Normalize:
  - `total = upfront + hourly * term_hours`
  - `normalized_hourly = total / term_hours`

## Output Contract
- Always return normalized hourly values in USD when available.
- Keep `not_found` when RI term cannot be matched.

## Caveats
- Normalized RI hourly is a comparison metric, not full invoice total.
- Taxes, negotiated discounts, FX conversion, and support plans are out of scope.
