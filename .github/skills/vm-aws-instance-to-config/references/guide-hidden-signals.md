# Reference: Hidden Signals for AWS→Azure Mapping

## Read When
- User asks for AWS-to-Azure mapping using only instance names.
- Need to prevent false equivalence based on vCPU/memory only.

## Must-Collect Dimensions
1. Storage limits: throughput, IOPS, write-latency requirement
2. Network limits: peak bandwidth, ENA dependency, jitter tolerance
3. CPU topology: SMT/HT policy, NUMA layout, affinity sensitivity
4. CPU generation: IPC/cache/memory-bandwidth differences by generation

## Minimal Action Flow
1. Output inferred fields first (`vcpu`, `memory_gb`, `profile`).
2. Explicitly list non-inferable fields as "requires data collection".
3. Compare Azure candidates against those constraints.
4. Recommend benchmark validation before final decision.

## Default Guidance (Data Missing)
- Start with `Premium SSD v2` or `Premium SSD LRS`.
- For strict write latency, evaluate `Ultra Disk` / `Write Accelerator` path.
- If no Intel lock-in, evaluate AMD options for better price/perf.

## Output Contract
- Separate clearly between:
  - inferred by naming rules
  - confirmed by measured/documented data

## Notes for LLM
- Never claim "risk-free equivalent migration" from vCPU/memory alone.
- Always include a short validation disclaimer for DB/SAP/core systems.
