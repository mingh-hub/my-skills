# xh-log-lookup Hold Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an independent Hold-order reference that covers the complete production lifecycle and routes Hold queries away from the generic loan module.

**Architecture:** Keep the main `SKILL.md` focused on intent routing and place detailed Hold query guidance in `references/modules/hold.md`. Model the new reference after `order.md`: define boundaries, orderId-first queries, lifecycle anchors, failure diagnosis, health checks, and module ownership. Use a static unittest to protect the production anchors and prevent the retired `order-batch` consumer from returning as an active path.

**Tech Stack:** Markdown skill references, Python `unittest`, Java source anchor validation.

---

### Task 1: Lock The Hold Module Contract

**Files:**
- Create: `xh-smart/xh-log-lookup/tests/test_hold_module.py`

- [x] **Step 1: Write the failing test**

```python
class HoldModuleTest(unittest.TestCase):
    def test_hold_module_covers_active_lifecycle(self):
        text = self.read_hold()
        for value in ("ReleaseHoldOrderJob", "ReleaseHoldSendToLokiJob", "ResetOrderInfoHandler"):
            self.assertIn(value, text)
```

- [x] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest xh-smart/xh-log-lookup/tests/test_hold_module.py -v`

Expected: FAIL because `references/modules/hold.md` and its routing do not exist.

### Task 2: Implement Hold Routing And Lifecycle Reference

**Files:**
- Create: `xh-smart/xh-log-lookup/references/modules/hold.md`
- Modify: `xh-smart/xh-log-lookup/SKILL.md`
- Modify: `xh-smart/xh-log-lookup/references/modules/loan.md`
- Test: `xh-smart/xh-log-lookup/tests/test_hold_module.py`

- [x] **Step 1: Add the Hold module**

Write an orderId-first reference with these sections: service and intent boundaries, first-query strategy, condition-pushdown examples, complete lifecycle table, focused diagnosis paths, failure rules, health checks, legacy-flow note, and cross-module references. Use only source-backed active anchors such as `[新解H]job开始`, `[新解H推送]job开始`, `LokiResultRequest OrderDataDTO is:`, and `[新解H]放款失败，查询订单解h状态：`.

- [x] **Step 2: Route Hold intentions to the new module**

Add Hold terms to the skill description and flow-tracking intent, add a Hold routing row before generic order/loan rows, and add the new reference to the navigation list. Preserve plain `拒就赔` routing while giving `拒就赔解H` and other explicit Hold actions precedence.

- [x] **Step 3: Remove duplicate loan ownership**

Remove `ReleaseHoldOrderServiceImpl` from `loan.md`, delete the `解H` lifecycle row, and add a short boundary link to `hold.md`.

- [x] **Step 4: Run the focused test**

Run: `python3 -m unittest xh-smart/xh-log-lookup/tests/test_hold_module.py -v`

Expected: PASS.

### Task 3: Verify The Skill

**Files:**
- Verify: `xh-smart/xh-log-lookup/references/modules/hold.md`
- Verify: `xh-smart/xh-log-lookup/SKILL.md`
- Verify: `xh-smart/xh-log-lookup/references/modules/loan.md`

- [x] **Step 1: Run all Python tests**

Run: `python3 -m unittest discover -s xh-smart/xh-log-lookup/tests -p 'test_*.py' -v`

Expected: all tests PASS.

- [x] **Step 2: Validate source anchors**

Run: `python3 xh-smart/xh-log-lookup/scripts/validate_query_anchors.py --all --summary`

Expected: active Hold methods and anchors resolve against the local `order` source. Review dynamic-message or service-inference warnings manually.

- [ ] **Step 3: Validate skill structure and diff hygiene**

Blocked: `quick_validate.py` cannot import `yaml`; downloading `PyYAML` was rejected by the execution safety policy. `git diff --check` and the repository smoke test completed successfully.

Run:

```bash
python3 /Users/user/.codex/skills/.system/skill-creator/scripts/quick_validate.py xh-smart/xh-log-lookup
git diff --check
git status --short
```

Expected: validation succeeds, no whitespace errors, and only the planned files are changed.
