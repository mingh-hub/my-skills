# Data-Inquiry / FundDecisionInfoService Tracing Patterns

Tracing `FundDecisionInfoService#queryFundDecisionInfo` issues through CLS logs.

## Overview

`FundDecisionInfoService` is in **data-inquiry** project（路径见映射表`仓库路径`列）, Dubbo provider `com.xhqb.datainquiry.common.service.api.FundDecisionInfoService`.

## Key Code Locations

| File | Purpose |
|------|---------|
| `FundDecisionInfoServiceImpl.java` | Entry: `queryFundDecisionInfo()`, iterates handlers |
| `CustomerOrderQueryHandler.java` | `buildFundInfo()` — per-fund: FrozenDays, loans, rejects |
| `QueryMsxjCurrentAmountImpl.java` | Current-amount impl, `fundSource()` returns `"MSHXJ"` |

## FrozenDays Logic

`fundSourceTag = fundSourceBean.getFundSourceId()` — exact match against `t_loan_refusefreeze_record.fund_source`.

If `freezeRecord == null` or `unfreezeDate == null` → FrozenDays = null.

**Critical**: `fundSourceBean.getFundSourceId()` uses `t_fund_source.fund_source_id` (e.g. `MSHXJ_RS`). Do NOT confuse with `QueryMsxjCurrentAmountImpl.fundSource()` which returns `"MSHXJ"`.

## CLS Query Patterns

| Purpose | Query |
|---------|-------|
| All datainquiry logs for a trace | `message:"<traceId>" and serviceName:"datainquiry"` |
| Per-fund handler logs | `message:"<traceId>" and message:"<fundRouteCode>" and serviceName:"datainquiry"` |
| Customer enabled fund list | `message:"<traceId>" and message:"enabledFundList" and serviceName:"datainquiry"` |

## Failure Modes

| Symptom | Likely Cause |
|---------|-------------|
| FrozenDays=null | No freeze record or fund_source mismatch |
| Fund missing from fundInfoList | Fund plan OBSOLETE/disabled |