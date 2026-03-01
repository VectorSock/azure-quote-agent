# RI 计算口径规则

本技能统一输出 RI 小时价，便于横向对比。

## Azure RI
- API 返回 `retailPrice`（整期总价）
- 归一公式：
  - `1Y hourly = retailPrice / (24*365*1)`
  - `3Y hourly = retailPrice / (24*365*3)`

## AWS RI
- 目标条目：`No Upfront + standard + (1yr|3yr)`
- 若条目含小时项与一次性项：
  - `total = upfront + hourly * term_hours`
  - `normalized_hourly = total / term_hours`

## 注意
- RI 小时价是标准化比较口径，不等于账单中的所有实际费用。
- 税费、企业协议折扣、币种转换不在本技能范围。
