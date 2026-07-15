from pathlib import Path
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]
HOLD_MODULE = SKILL_ROOT / "references" / "modules" / "hold.md"
LOAN_MODULE = SKILL_ROOT / "references" / "modules" / "loan.md"
SKILL_FILE = SKILL_ROOT / "SKILL.md"


class HoldModuleTest(unittest.TestCase):
    def read_hold(self):
        self.assertTrue(HOLD_MODULE.exists(), "references/modules/hold.md must exist")
        return HOLD_MODULE.read_text(encoding="utf-8")

    def test_skill_routes_hold_intentions_to_hold_module(self):
        text = SKILL_FILE.read_text(encoding="utf-8")
        self.assertIn("references/modules/hold.md", text)
        for keyword in (
            "Hold单",
            "H单",
            "HOLD_ON",
            "进H",
            "解H",
            "继续hold",
            "解H推送",
            "取消Hold",
            "Hold超时",
            "超时转单",
            "CRM催促解H",
        ):
            self.assertIn(keyword, text)

    def test_hold_module_is_order_id_first(self):
        text = self.read_hold()
        self.assertIn("orderId", text)
        self.assertIn("默认且主要", text)
        self.assertIn('serviceName:"order" AND message:"{orderId}"', text)
        self.assertIn("只有用户明确提供 `traceId`", text)

    def test_hold_module_covers_active_lifecycle(self):
        text = self.read_hold()
        for value in (
            "ReleaseHoldOrderJob",
            "ReleaseHoldSendToLokiJob",
            "ResetOrderInfoHandler",
            "OrderLoanFailHoldHandler",
            "CancelHoldOrdersJob",
            "CancelSpecialChannelHoldOrdersJob",
            "HandleOrderHoldRouteJob",
            "HandleHoldOrdersMonitorJob",
            "[新解H]job开始",
            "[新解H推送]job开始",
            "[新解H]放款失败，查询订单解h状态：",
            "LokiResultRequest OrderDataDTO is:",
        ):
            self.assertIn(value, text)

    def test_hold_module_explains_conditional_return_to_hold(self):
        text = self.read_hold()
        self.assertIn("releaseHoldStatus=Y", text)
        self.assertIn("order.loanfail.hold.info", text)
        self.assertIn("重路由结果明确要求 Hold", text)
        self.assertIn("Loki 返回失败不等于一定再次进入 H 单", text)

    def test_legacy_consumer_is_not_an_active_anchor(self):
        text = self.read_hold()
        self.assertNotIn("HandleHoldOrderConsumer推进来的消息ID", text)
        self.assertIn("遗留链路", text)
        self.assertIn("生产主链", text)

    def test_loan_module_delegates_hold_lifecycle(self):
        text = LOAN_MODULE.read_text(encoding="utf-8")
        self.assertNotIn("| 解H |", text)
        self.assertNotIn("ReleaseHoldOrderServiceImpl#releaseHoldOrder", text)
        self.assertNotIn("order (OrderRouteService, LoanOrderServiceImpl, ReleaseHoldOrderServiceImpl)", text)
        self.assertIn("references/modules/hold.md", text)


if __name__ == "__main__":
    unittest.main()
