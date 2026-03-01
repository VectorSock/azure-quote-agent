# AWS Size → vCPU 规则

本技能使用启发式规则解析 AWS size token：

- `nano` / `micro` / `small` / `medium` → `1 vCPU`
- `large` → `2 vCPU`
- `xlarge` → `4 vCPU`
- `Nxlarge`（例如 `2xlarge`, `4xlarge`）→ `4 * N vCPU`

## 不支持
- `metal` 系列不在本技能默认解析范围内，返回 `unrecognized_format`。

## 说明
- 该规则用于快速标准化，不替代厂商官方规格表。
