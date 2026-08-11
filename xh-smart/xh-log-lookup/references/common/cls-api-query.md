# CLS HTTP API Query

## When To Use

Use `scripts/cls_log_query.py --method auto` for normal CLS lookups. It tries the internal HTTP API first and only falls back to browser paths when the API is unavailable or cannot prove completeness.

## Endpoint

```text
https://datasight-1300455117.internal.clsconsole.tencent-cloud.com/api/cls?i=cls/SearchLog&uin=100034610027
```

This is the internal CLS console proxy. `secret_id` and `secret_key` are intentionally not required and must not be treated as prerequisites.

## Payload Shape

```json
{
  "service": "cls",
  "region": "ap-beijing",
  "action": "SearchLog",
  "version": "2020-10-16",
  "data": {
    "Query": "serviceName:\"order\" AND message:\"签约\"",
    "SamplingRate": 1,
    "From": 1779897600000,
    "To": 1779984000000,
    "QueryOptimize": 0,
    "SyntaxRule": 1,
    "Limit": 100,
    "Sort": "desc",
    "HighLight": true,
    "TopicId": "f6748b3a-8ab8-4191-b848-cb90b1598901",
    "UseNewAnalysis": true
  }
}
```

`Query` carries the raw query string and can contain Chinese. Browser fallback URLs still need ASCII `queryBase64`.

## Response Handling

Parse `Response.Results[*]`:

- `Time`: millisecond timestamp.
- `LogJson`: JSON string or object. Prefer `log.message`, then `message`, then `fields.message`, then the raw JSON.
- `HighLights`: optional highlight fragments.
- `TopicName` and `Source`: copied to output metadata.

If the response has a total count field, compare it with loaded results. If no total count exists, treat `len(results) < Limit` as complete and `len(results) >= Limit` as incomplete.

## Fallback Rules

- `source=api` and `is_complete=true`: analyze API results directly.
- `source=api` and `is_complete=false`: non-statistical analysis may use the sample with a yellow completeness warning; statistical analysis must fall back.
- `source=api_failed`: use the returned `cls_url` in the host agent browser. The historical `fallback_method: "workbuddy"` value remains for compatibility.
- Local Chrome is only the final fallback: `--method local-chrome --use-local-chrome`.
