# Reference: TCO Levers (Non-Hardcoded)

## Read When
- 用户不只想看技术匹配，还希望理解“为什么这个 Azure 方案在成本上更划算”。
- 需要给迁移评估补充商业价值说明（但不输出死板报价结论）。

## How to Explain (Example-friendly Style)
- **AHB (Azure Hybrid Benefit)**：
    - 这是 Azure 独有的商务核武器。如果客户持有 Windows Server/SQL Server 现有许可，迁移上云可**免除云端 License 费用**
	- VM RI 定价逻辑本身比 AWS 便宜 10%，AHB 配合 RI（预留实例），综合计算成本可比 AWS 低 40% 以上（以实时价格计算器与合同条款为准）
	- **痛点场景**：企业的云上资源中，往往 30%-40% 是开发测试环境，并非生产环境
	- **TCO 价值**：对于签署 EA（企业协议）的客户，Azure 允许开启专门的 Dev/Test 订阅。在这个订阅里：Windows VM 按照 Linux 价格计费；SQL Server 等 PaaS 服务享有特殊折扣

- **ESU (Extended Security Updates)**
	- **痛点场景**：客户还在用 Windows Server 2012/R2 或 SQL Server 2012 等已停止官方支持（EOS）的老旧版本，不敢升级（怕业务崩），但又有合规安全需求
    - **Extended Security Updates (ESU)**：在本地机房或 AWS/阿里云上，如果想继续获得微软的安全补丁，必须支付极其昂贵的 ESU 费用（通常是 License 费用的 75%-100%/年）
    - **TCO 价值**：只要迁移到 Azure VM 上，ESU 完全免费。这给了客户 3 年时间窗口去重构应用，仅这一项节省的费用，往往就超过了云资源的计算成本。这是友商无法提供的第一方优势（需按当前微软政策与产品版本核验）

- **单实例 SLA**
	- **单实例 SLA**：Azure 是极少数对**单台 VM**（配合 Premium SSD）提供 **99.9% SLA** 的厂商
	- **TCO 价值**：对于非核心业务，友商（尤其是国内云）通常要求“双机热备+跨可用区”才能承诺 SLA，导致客户被迫购买 2 台机器。对非核心业务，Azure 在合规前提下经常可以用 1 台先达标，**硬件成本直接减半**
	- **基础设施标准**：国内由世纪互联运营，严格遵循 T4 机房标准（全冗余），且在北上主干网节点拥有极佳的 BGP 带宽质量（每台服务器高带宽突发能力），网络抖动低于普通 BGP 线路。你可以把这一段当作“风险说明”而不是“营销承诺”：网络质量、带宽突发和抖动表现，需要按客户区域与业务时段做验证。

## Output Contract
- 输出时拆分为两层：
  - `technical_candidate`：基于规格策略选出的 SKU
  - `cost_confidence`：`low` / `medium` / `high`（取决于是否有真实价格、合同、许可证清单）
- 缺少商业输入时，必须明确：成本结论仅为“方向性判断”。

## Do Not Hardcode
- 不要硬编码固定折扣比例（如“永远便宜 10%/40%”）。
- 不要硬编码合同专属条款（EA、MCA、企业特批）。
- 不要硬编码会随时间和区域变化的价格数字。

## Notes for LLM
- 用“业务听得懂”的语气解释价值，但保留合规免责声明。
- 优先使用“通常/常见/需核验”这类表述，避免绝对化承诺。
