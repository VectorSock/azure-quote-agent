# Family Mapping Policy

本技能按配置形态映射 Azure VM family：

- `gpu=true` → `N`
- `burstable=true` → `B`
- 其余按内存比（`memory_gb / vcpu`）
  - `>= 6.0` → `E`（内存型）
  - `<= 2.5` → `F`（计算型）
  - 其他 → `D`（通用型）

## 说明
- 这是迁移预估策略，不代表容量实时可用性。
- 最终实例选择应在目标 Region 再做可用性校验。
