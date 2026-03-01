# Fallback Priority Policy

当 primary SKU 不满足实际需求时，按以下策略生成 fallback：

1. 先尝试同 family，不同 feature suffix（`as -> s -> a -> ds -> d -> 空`）
2. 再尝试相邻 family（示例：`D -> E -> F -> B`）
3. 版本按 family 默认策略应用：
   - `D/E -> _v5`
   - `F -> _v2`
   - `N -> _v3`
   - `B -> 无版本后缀`

## 使用建议
- fallback 仅为候选队列，不代表最终可用。
- 进入落地部署前，应结合 Region 可用性和配额进行二次筛选。
