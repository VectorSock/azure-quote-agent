# Reference: Size → vCPU

## Read When
- Need `vcpu` from AWS instance name quickly.
- User accepts heuristic output for pre-screening.

## Inputs
- `size` token from instance type (`m6a.4xlarge` → `4xlarge`).

## Decision Rules
| Condition | vCPU |
| --- | --- |
| `nano` / `micro` / `small` | `1` |
| `medium` | `1` |
| `large` | `2` |
| `xlarge` | `4` |
| `Nxlarge` | `4 × N` |

## Failure Rules
- `metal` → return `status=unrecognized_format`.
- Empty/invalid token → return `status=unrecognized_format`.

## Output Contract
- Return derived `vcpu` and keep it labeled as heuristic.
- If unresolved, return failure explicitly; do not infer.

## Notes for LLM
- Use short wording: "heuristic estimate".
- Do not claim vendor-certified exact spec.
