# SAP Routing Policy

## 目标
将 VM 选型从“仅看规格”扩展为“规格 + 业务上下文（system/env/workload_type/SAP_workload）”联合决策。

## 输入信号优先级
1. `SAP_workload`（显式布尔）
2. `system` / `workload_type` 文本特征
3. `workload` 兼容字段（历史输入）
4. 规格阈值（如 `memory_gb > 256`）

## 核心路由
- `db_hana`：SAP 核心 DB 或 SAP 大内存 DB，要求认证机型。
- `sap_app`：SAP 应用层，默认 D，大内存升 E。
- `app_db_prd_hana`：APP+DB 且 PRD，按 HANA 保守路径。
- `app_db_nonprd_app`：APP+DB 且 DEV/QAS，按应用层路径并给内存余量。
- `infra_general`：Zabbix/跳板机/同步代理，通用 D。
- `generic`：无法归类时的通用规则路径。

## SAP 认证机型策略
- 当 `sap_cert_required=true` 时输出 `sap_sku`。
- `memory_gb > 256` 或核心 DB 场景优先 M 系列；小规格可 E 系列。
- 若认证池不足，保留普通 `primary_sku/fallback_skus` 作为应急候选并提示复核。

## 注意
- 该策略用于报价与迁移预选型，不替代 SAP 官方最新认证清单。
- 涉及生产系统（尤其 PRD DB）应进行人工复核。