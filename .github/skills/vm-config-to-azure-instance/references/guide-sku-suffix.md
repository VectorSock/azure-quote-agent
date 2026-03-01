# Reference: SKU Suffix Construction

## Read When
- Need deterministic Azure SKU suffix from CPU/feature constraints.

## Inputs
- `cpu_vendor`, `cpu_arch`
- `local_temp_disk`, `network_optimized`
- `prefer_amd`, selected `family`

## Suffix Signals
- `a`: AMD preference (`cpu_vendor=amd`, or `unknown + prefer_amd=true`)
- `p`: ARM architecture (`cpu_arch=arm64`)
- `d`: local temporary disk required
- `n`: network optimization required
- `s`: premium storage preference (default for non-`B` family)

## Assembly Rules
- Use stable order: `a` → `p` → `d` → `n` → `s`.
- De-duplicate suffix chars.
- For `B` family, do not append `s` by default.

## Output Contract
- Return one deterministic suffix string.
- Keep suffix policy visible via assumptions in output payload.
