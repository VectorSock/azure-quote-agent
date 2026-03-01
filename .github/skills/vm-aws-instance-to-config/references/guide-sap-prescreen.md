# Reference: SAP Pre-Screen

## Read When
- User asks "is this instance potentially SAP-suitable?"
- Need fast rule-based signal before formal certification checks.

## Base Rule (`sap_possible=true`)
All must be true:
1. `profile` in `general` or `memory`
2. `is_gpu_accelerated=false`
3. `cpu_arch != arm64`
4. `vcpu >= 16`
5. `memory_gb >= 64`

If any check fails, return `sap_possible=false`.

## Optional Strict Mode
Use only when user asks for conservative gate:
- `is_ebs_optimized=true`
- `generation >= 5`
- Azure candidate has validated low write-latency capability

## Output Contract
- `sap_possible` is heuristic pre-screen signal only.
- Always add disclaimer: not SAP certification, not production approval.

## Notes for LLM
- Keep message brief and explicit about limitations.
- Do not replace SAP Notes / official certified instance lists.
