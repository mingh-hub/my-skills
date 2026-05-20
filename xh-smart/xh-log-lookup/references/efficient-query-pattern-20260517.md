# 高效查询工作流（当前版）

## 何时读取

当查询耗时过长、CLS 页面状态异常、或需要说明为什么必须使用工具脚本时读取。

## 当前快速路径

1. 用代码或业务子 Skill 确认日志关键词。
2. 用 `tools/cls_query.py` 一次性构造包含 `topic_id`、`time`、`queryBase64` 的完整 URL。
3. 让工具复用本地 Chrome 专用窗口，不操作用户当前标签页。
4. 让工具点击“加载更多”并保存完整 `document.body.innerText`。
5. 用输出 JSON 中的 `log_count`、`services`、`contracts` 和 `output_path` 做分析。

示例：

```bash
python3 /Users/user/.hermes/skills/xh-smart/xh-log-lookup/tools/cls_query.py \
  --env prod \
  --time 'now-30d,now' \
  --query 'traceId:"37426d42fdc699d1"' \
  --output /tmp/cls_output.txt
```

## 保留的经验结论

- Topic 和时间范围必须放在 URL 中，避免 UI 状态漂移。
- 测试环境默认查近 1 天，近 1 小时常返回 0。
- 页面默认只渲染部分结果；必须加载更多再提取全文。
- 中文不要进入 `queryBase64`；优先用 ASCII 标识符查询，再从全文中过滤中文。

## 历史慢路径（废弃）

历史上通过云端浏览器工具点 UI、注入编辑器、截 snapshot 的路径容易超时、截断、抢错会话。该路径已废弃；保留此结论仅用于解释为什么当前统一走本地 Chrome 专用窗口和 `cls_query.py`。
