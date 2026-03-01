# Reference: Family Selection

## Read When
- Need to choose Azure VM family from normalized shape (`vcpu`, `memory_gb`) and intent flags.

## Inputs
- `vcpu`, `memory_gb`
- `gpu`, `burstable`

## Decision Rules
1. `gpu=true` → `N`
2. `burstable=true` → `B`
3. Else compute ratio: $ratio = memory\_gb / vcpu$
   - `ratio >= 6.0` → `E`
   - `ratio <= 2.5` → `F`
   - otherwise → `D`

## Caveats (Need External Data)
- Family choice does not guarantee region capacity or quota.
- Large in-memory workloads may require `M`-series fallback despite `E` primary.

## Output Contract
- Return one `primary_family` decision and mark it as policy-based mapping.
- If input invalid (`vcpu<=0` or `memory_gb<=0`), return explicit error.
