# Reference: AWS SKU Matching

## Read When
- Need to map `instanceType + operatingSystem` to a billable AWS pricing SKU.

## Strict Match (Preferred)
All conditions must hold:
- `instanceType == <aws_instance_type>`
- `operatingSystem == <os>`
- `preInstalledSw = NA`
- `tenancy = Shared`
- `capacitystatus = Used`
- `operation = RunInstances`

## Relaxed Match (Fallback)
- If strict match fails, use first SKU that matches `instanceType + operatingSystem`.

## Output Contract
- `sku`
- `sku_match_mode`: `strict | relaxed | none`
- If `none`, return `status=not_found`.

## Notes for LLM
- `relaxed` means lower certainty; mention this explicitly.
- Do not fabricate SKU when no match exists.
