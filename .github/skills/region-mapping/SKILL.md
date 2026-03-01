---
name: region-mapping
description: 标准化模糊位置并映射到 AWS/Azure/GCP 官方 Region ID；在云报价、迁移或多云比对前优先使用。
---

# 技能：云区域标准化映射

## 概述
当用户提供城市名、历史区域名或非标准地域文本时，使用此技能将输入标准化为 AWS / Azure / GCP 的 Region ID。

此技能支持：
- 单条查询（快速确认地域）
- 批量文件处理（CSV / XLSX）

## 何时使用
- 用户提到地域词但表达不规范：如“新加坡”“US East”“Southeast Asia”。
- 用户上传包含地域列的数据文件，要求统一映射。
- 在执行云资源报价或多云对比前，需要先把地域标准化。

## 运行方式
所有路径默认基于当前工作目录。
支持项目根目录下的相对路径（如 `input/...`、`output/...`），也支持绝对路径。

### 单条查询
`python .github/skills/region-mapping/scripts/region_mapping.py --location "Singapore"`

### 批量映射
`python .github/skills/region-mapping/scripts/region_mapping.py --input-file "input/locations.csv" --column "region" --output "output/mapped_results.csv"`

## 参数说明
- `--location`：单条输入（城市 / region / long name）。
- `--input-file`：批量输入文件（`.csv` / `.xlsx` / `.xls`）。
- `--column`：批量模式的位置列名；不传则自动探测：`region`、`location`、`city`、`site`（含常见中文列名）。
- `--output`：批量输出路径（默认 `output/region_mapping_results.csv`）。
- `--mapping-file`：映射表路径；未传时优先使用 `.github/skills/region-mapping/assets/get_regions.xlsx`，其次 `data/get_regions.xlsx`。
- `--default-azure-region`：回退 Azure Region（默认 `eastasia`）。

## 执行规则
1. 优先直接运行脚本并读取脚本输出，不要自行臆测 Region ID。
2. 若某云结果为 `null` 或 `matched_by=fallback`，需要明确告知用户该位置未被可靠识别。
3. 如果输入无法识别（例如虚构地点），应直接说明“无法识别”，严禁编造映射结果。
4. 批量模式路径建议统一以项目根目录为基准，便于与其它 skill 链式调用。

## 输出示例
单条模式输出 JSON：

```json
{
  "input_value": "Singapore",
  "city": "Singapore",
  "aws_region": "ap-southeast-1",
  "azure_region": "southeastasia",
  "gcp_region": null,
  "matched_by": "city_name"
}
```

## 输出字段
- `input_value`：原始输入
- `city`：识别出的城市
- `aws_region`：AWS Region
- `azure_region`：Azure Region
- `gcp_region`：GCP Region
- `matched_by`：匹配方式（`city_name` / `region_id` / `region_long_name` / `city_geo` / `fallback`）

## 批量模式输出列
批量模式会保留输入文件所有原列，并追加以下列：
- `mapped_city`
- `mapped_aws_region`
- `mapped_azure_region`
- `mapped_gcp_region`
- `mapped_by`
