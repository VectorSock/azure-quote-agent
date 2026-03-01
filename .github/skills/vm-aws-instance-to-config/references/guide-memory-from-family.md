# Reference: Family → Memory Estimate

## Read When
- Need `memory_gb` from instance type without official spec lookup.
- Running migration sizing or early Azure benchmark mapping.

## Inputs
- `family` prefix (`r/m/c/t/...`)
- `vcpu`

## Formula
$$
memory\_gb = vcpu \times ratio
$$

## Decision Rules
| Family Prefix | Ratio |
| --- | --- |
| `r` / `x` / `u` / `z` | `8.0` |
| `m` / `i` / `d` | `4.0` |
| `c` / `t` | `2.0` |
| `p` / `g` | `8.0` |
| other | `4.0` |

## Caveats
- `t` small sizes and very large memory families can deviate.
- For SAP/DB/high-IO workloads, mark as "needs validation".

## Output Contract
- Return `memory_gb` as heuristic only.
- Keep distinction clear:
  - inferred: `vcpu`, `memory_gb`
  - must-collect: IOPS, throughput, latency, NUMA

## Notes for LLM
- Prefer wording: "estimated by naming rules".
- Never present this as SLA-grade or procurement-final data.
