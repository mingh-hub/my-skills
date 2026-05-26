# 高效查询工作流（当前版）

## 何时读取

当查询耗时过长、CLS 页面状态异常、或需要说明为什么必须使用工具脚本时读取。

## 当前快速路径

1. 用代码或业务子 Skill 确认日志关键词。
2. 构造包含 `topic_id`、`time`、`queryBase64` 的完整 CLS URL。
3. 优先用 Hermes 内置浏览器直接打开 CLS URL，避免依赖 UI 默认状态。
4. 在页面中点击“加载更多”直到满足完整性要求，再提取完整页面文本。
5. 当 Hermes 页面操作失败、登录态不可用、或需要批量自动提取时，改用 `tools/cls_query.py` 作为本地 Chrome 备用路径。

示例：

```bash
python3 /Users/user/.hermes/skills/xh-smart/xh-log-lookup/tools/cls_query.py \
  --env prod \
  --time 'now-30d,now' \
  --query 'traceId:"37426d42fdc699d1"' \
  --no-browser
```

## 保留的经验结论

- Topic 和时间范围必须放在 URL 中，避免 UI 状态漂移。
- 测试环境默认查近 1 天，近 1 小时常返回 0。
- 页面默认只渲染部分结果；必须加载更多再提取全文。
- 中文不要进入 `queryBase64`；优先用 ASCII 标识符查询，再从全文中过滤中文。

## 备用路径

`tools/cls_query.py` 默认只构造 URL。只有显式加 `--use-local-chrome` 时，才会复用本地 Chrome 备用窗口、自动点击“加载更多”并保存完整 `document.body.innerText`。只有切换到本地 Chrome 备用路径执行/提取时，统计模式才必须使用 `--require-complete --use-local-chrome` 并按工具返回的拆分建议处理不完整数据。
