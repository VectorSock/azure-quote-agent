# SAP 可行性启发式（sap_possible）

`sap_possible=true` 需要同时满足：

1. `profile` 属于 `general` 或 `memory`
2. 非 GPU（`is_gpu_accelerated=false`）
3. 非 ARM（`cpu_arch != arm64`）
4. `vcpu >= 16`
5. `memory_gb >= 64`

## 使用约束
- `sap_possible` 仅表示“按规则看可能可行”。
- 不代表 SAP 官方认证、也不代表最终可生产部署。
- 对外回答时应明确这是预筛选信号。
