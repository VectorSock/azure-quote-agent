# Feature Suffix Policy

本技能将能力特征映射到 Azure SKU suffix：

- `a`：AMD 倾向（`cpu_vendor=amd`，或 `unknown + prefer_amd=true`）
- `p`：ARM 架构（`cpu_arch=arm64`）
- `d`：本地临时盘需求（`local_temp_disk=true`）
- `n`：网络增强需求（`network_optimized=true`）
- `s`：默认添加，表示 Premium Storage 能力偏好

## 规则说明
- burstable / gpu 场景通常不强制追加 `a`。
- suffix 最终会去重并保持稳定顺序。
