# Failure Handling and Review Policy

## 目标
本策略用于 `vm-quote-pipeline-runner`，保证每一步都有证据、失败可定位、流程可续跑。

## 执行与证据
- 编排器严格按固定顺序执行 7 个步骤。
- 每一步都会产出一份 JSON 证据文件：`output/<input_stem>/step_xxx.json`。
- 证据文件最少包含：`step_id`、`status`、`command`、`exit_code`、`artifacts`、`stdout_last_json`、`error`。

## 失败判定
满足任一条件即判定步骤失败：
- 子进程退出码非 `0`。
- 子进程未输出可解析的 JSON 摘要，且目标产物不存在。
- 子进程 JSON 摘要包含 `status=error`。

编排器失败时返回顶层 JSON：
- `status=failed`
- `failed_step=<step_id>`
- `run_dir=<output/...>`
- `step_reports=<all step json path>`

## 续跑策略
- 支持 `--resume-from <step_id>` 从指定步骤继续执行。
- 续跑时默认复用已存在中间产物，不覆盖历史证据。
- 推荐失败后先检查对应 `step_xxx.json`，修复后再续跑。

## Review 规则
- 本流水线默认 `include_review=false`，即抽取阶段只处理 `status=ok` 的记录。
- 若存在 `review` 记录，编排器不自动补猜；需要人工确认后再重跑。
- Region 映射必须以 `get_regions.xlsx` 为准；任何 `fallback` 结果应标记复核。

## 人工复核建议
优先复核以下信号：
- 区域映射 `mapped_by=fallback`。
- 实例解析 `status=unrecognized_format`。
- SKU 映射 `status=invalid_input` 或 `mapping_confidence` 偏低。
- 定价阶段 `pricing_status!=ok`、`aws_status!=ok` 或 `azure_status!=ok`。
