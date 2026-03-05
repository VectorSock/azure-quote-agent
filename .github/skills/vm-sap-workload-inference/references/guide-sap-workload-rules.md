# SAP Workload 规则说明

## 设计目标
- 优先稳健（robust）而非死板匹配。
- 使用 `system + env + workload_type` 多字段联合判断。
- 对负样本（如监控/跳板机/同步代理）设置反向信号，降低误判。

## 规则优先级（高到低）
1. **非 SAP 明确信号**：`zabbix`、`jumpbox/bastion/跳板机`、`efs sync agent`。
2. **SAP 核心套件**：`S/4`、`BW`、`PO`。
3. **SAP 应用层**：`Fiori`、`Solman`、`BO`、`G4`、`OA`。
4. **SAP 周边生态**：`Opentext/OTCS`、`WB`、`Soterien`。
5. **通用 SAP 提示词**：`sap`、`netweaver`、`abap`、`hana`。

## role 与 env 参与方式
- `role`（从文本中识别 `APP/DB/APP+DB`）用于给分类结果加权。
- `env` 统一归一为 `dev/qas/prd/unknown`，主要用于解释与审计，不直接强行改判。

## 置信度建议
- `high`：核心套件命中，或明确非 SAP 基础设施命中。
- `medium`：SAP 应用层/周边生态命中。
- `low`：仅弱提示词、或证据不足。

## 注意
- 该规则用于报价与迁移预分类，不等同 SAP 官方认证结论。
- 对 `OA/WB` 这类缩写，若缺少 SAP 语境可能出现歧义，建议结合人工复核。