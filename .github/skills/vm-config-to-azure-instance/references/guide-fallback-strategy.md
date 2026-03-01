# Reference: Fallback Strategy

## Read When
- Need fallback SKU queue when primary SKU is unavailable.

## Step 1: Same-Family Suffix Fallback
For non-`B` family, use priority:
`as` → `s` → `a` → `ds` → `d` → empty suffix.

For `B` family, use:
empty suffix → `a`.

## Step 2: Cross-Family Fallback
- `D` primary: try `E`, then `F`
- `E` primary: try `M`, then `D`
- `F` primary: try `D`, then `E`
- `N` primary: try `E`, then `D`
- `B` primary: try `D`, then `F`

## Step 3: Size Escalation
- If same size candidates are insufficient, try next larger size (`vcpu × 2`) in target family.
- Example: `Standard_D4s_v5` unavailable → try `Standard_D8s_v5`.

## Caveats
- Fallback queue is policy-based candidate list, not real-time availability proof.
- Region/SKU availability and quota must be checked externally.

## Output Contract
- Return ordered `fallback_skus` list.
- Keep first items closest to primary capability profile.
