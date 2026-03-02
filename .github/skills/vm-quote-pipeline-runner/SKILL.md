---
name: vm-quote-pipeline-runner
description: 将多个独立 skill 按固定顺序串成可执行 VM 报价流水线，支持逐步落盘、失败停止与从失败步骤续跑。
---

# 技能：VM 报价流水线编排器

## 概述
本技能将以下独立 skill 串联为一条固定顺序流水线：
1. `excel-input-extraction`
2. `region-mapping`
3. `vm-aws-instance-to-config`
4. `vm-config-to-azure-instance`
5. `vm-pricing-retail-api`
6. `excel-quote-writer`（`build_vm_quote_payload.py` + `write_quote_excel.py`）

核心目标：
- 可替换：单步可独立升级。
- 可观测：每步生成 JSON 证据。
- 可重跑：支持从失败步骤继续。
- 可测试：每个脚本可单测，编排器可集测。

## 目录结构
```text
.github/skills/vm-quote-pipeline-runner/
├── SKILL.md
├── scripts/
│   └── vm_quote_pipeline.py
├── references/
│   └── failure-handling-and-review-policy.md
└── assets/
    └── defaults.yaml
```

## 运行方式
所有路径默认相对项目根目录。

### 1) 全量执行
`python .github/skills/vm-quote-pipeline-runner/scripts/vm_quote_pipeline.py --input-excel "input/sample_input.xlsx"`

### 2) 指定输出根目录
`python .github/skills/vm-quote-pipeline-runner/scripts/vm_quote_pipeline.py --input-excel "input/sample_input.xlsx" --output-root "output"`

### 3) 从失败步骤续跑
`python .github/skills/vm-quote-pipeline-runner/scripts/vm_quote_pipeline.py --input-excel "input/sample_input.xlsx" --resume-from step_05_pricing`

### 4) 跳过某云定价
`python .github/skills/vm-quote-pipeline-runner/scripts/vm_quote_pipeline.py --input-excel "input/sample_input.xlsx" --skip-aws`

## 参数说明
- `--input-excel`：输入原始配置单（必填）。
- `--output-root`：输出根目录（默认 `output`）。
- `--resume-from`：从指定步骤继续执行。
- `--include-review`：抽取时保留 `status!=ok` 行。
- `--skip-aws` / `--skip-azure`：定价阶段按需跳过。
- `--customer-project` / `--region`：写入报价 Summary。
- `--config`：默认值配置（默认 `assets/defaults.yaml`）。
- `--template`：报价 Excel 模板路径。

## 固定顺序与产物
编排器会在 `output/<input_excel_stem>/` 下产出：
- `step_01_extracted.csv`
- `step_02_region_mapped.csv`
- `step_03_aws_indicators.csv`
- `step_04_azure_mapping.csv`
- `step_05_pricing.csv`
- `step_06_quote_payload.json`
- `quote_result.xlsx`

同时每一步都会产出证据 JSON：
- `step_01_extract.json` ... `step_07_write_quote_excel.json`

## 失败输出
任一步失败立即停止，并输出：
```json
{
  "status": "failed",
  "failed_step": "step_xxx",
  "run_dir": "output/<name>",
  "step_reports": ["..."]
}
```

## 约束与规则
- Region 映射必须来源于 `get_regions.xlsx`，不做臆测。
- 失败后先检查对应 `step_xxx.json`，修复后用 `--resume-from` 续跑。
- 详细策略见 `references/failure-handling-and-review-policy.md`。
