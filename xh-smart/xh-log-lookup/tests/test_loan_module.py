from pathlib import Path
import re
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]
LOAN_MODULE = SKILL_ROOT / "references" / "modules" / "loan.md"
SKILL_FILE = SKILL_ROOT / "SKILL.md"


class LoanModuleTest(unittest.TestCase):
    def read_loan(self):
        self.assertTrue(LOAN_MODULE.exists(), "references/modules/loan.md must exist")
        return LOAN_MODULE.read_text(encoding="utf-8")

    def test_skill_routes_loan_intentions_and_preserves_hold_priority(self):
        text = SKILL_FILE.read_text(encoding="utf-8")
        loan_route = next(
            line
            for line in text.splitlines()
            if "references/modules/loan.md" in line and line.startswith("|")
        )
        for keyword in ("放款日志", "放款失败", "资金路由", "loki放款", "换资方"):
            self.assertIn(keyword, loan_route)
        self.assertNotIn("拒就赔", loan_route)
        self.assertNotIn("提前结清", loan_route)

        repay_route = next(
            line
            for line in text.splitlines()
            if "references/modules/repay.md" in line and line.startswith("|")
        )
        self.assertIn("提前结清", repay_route)

        hold_route = next(
            line
            for line in text.splitlines()
            if "references/modules/hold.md" in line and line.startswith("|")
        )
        for keyword in ("Hold单", "H单", "HOLD_ON", "进H", "解H"):
            self.assertIn(keyword, hold_route)
        self.assertIn("Hold 明确优先于通用订单、放款", text)

    def test_loan_module_is_order_id_first_and_trace_id_explicit(self):
        text = self.read_loan()
        self.assertIn("orderId", text)
        self.assertIn("默认且主要", text)
        self.assertIn('serviceName:"order" AND message:"{orderId}"', text)
        self.assertIn("只有用户明确提供 `traceId`", text)

    def test_loan_module_covers_core_entry_anchors(self):
        text = self.read_loan()
        for value in (
            "ApplyLoanSendLokiQHandler#sendQToLoki",
            "LoanRequestMessageConsumer#consume",
            "DisposeLoanResultMessageProducer#send",
            "LokiResultRecvConsumer#handleMessage",
            "LokiLoanResultServiceImpl",
            "BaseLoanEntity",
        ):
            self.assertIn(value, text)
        for value in ("状态", "放款中", "放款成功", "放款失败"):
            self.assertIn(value, text)

        flow = "order → loki-webapp → order-batch → order"
        self.assertIn(flow, text)
        entry_order = (
            "ApplyLoanSendLokiQHandler#sendQToLoki",
            "LoanRequestMessageConsumer#consume",
            "DisposeLoanResultMessageProducer#send",
            "LokiResultRecvConsumer#handleMessage",
        )
        positions = [text.index(entry) for entry in entry_order]
        self.assertEqual(positions, sorted(positions))

        service_entry_pairs = (
            ("order", "ApplyLoanSendLokiQHandler#sendQToLoki"),
            ("loki-webapp", "LoanRequestMessageConsumer#consume"),
            ("loki-webapp", "DisposeLoanResultMessageProducer#send"),
            ("order-batch", "LokiResultRecvConsumer#handleMessage"),
            ("loki-webapp", "BaseLoanEntity"),
        )
        for service, entry in service_entry_pairs:
            self.assertTrue(
                any(service in line and entry in line for line in text.splitlines()),
                f"missing service binding: {service} -> {entry}",
            )
        for anchor in ("[推送]", "当前状态为"):
            self.assertIn(anchor, text)
        self.assertNotIn('serviceName:"order" AND message:"当前状态为"', text)
        self.assertIn("BaseLoanEntity 是 Loki 资金渠道状态步进", text)
        self.assertIn("不是 order 订单落库", text)

    def test_loan_module_documents_result_branches(self):
        text = self.read_loan()
        for value in (
            "CREDIT_APPLY_FAIL",
            "USE_CREDIT_ING",
            "USE_CREDIT_FAIL",
            "USE_CREDIT_SUCCESS",
            "REPAYING",
            "SINGFAIL",
            "FAIL",
        ):
            self.assertIn(value, text)

    def test_loan_module_explains_result_branch_semantics(self):
        text = self.read_loan()
        self.assertNotIn("REPAYING 是放款成功终态", text)
        self.assertFalse(
            re.search(r"REPAYING.{0,20}终态|终态.{0,20}REPAYING", text),
            "REPAYING must not be hard-coded as a terminal status",
        )
        for value in ("REPAYING", "正常还款中", "成功侧状态", "非结清", "用信无资方 FAIL"):
            self.assertIn(value, text)
        self.assertTrue(
            "授信无可用资方" in text or "授信失败收敛" in text,
            "SINGFAIL needs a credit-side no-fund semantic",
        )
        qualifiers = ("该分支", "该实现", "不是通用状态")
        self.assertGreaterEqual(sum(qualifier in text for qualifier in qualifiers), 2)

    def test_loan_module_references_terminal_status_glossary(self):
        text = self.read_loan()
        self.assertIn("references/modules/order/order-status-glossary.md", text)
        for status in (
            "REPAYING",
            "LOAN_SUCESS_PRE_WP",
            "SINGFAIL",
            "FAIL",
            "REPAYED",
            "SETTLED",
        ):
            self.assertIn(status, text)
        self.assertIn("成功终态", text)
        self.assertIn("失败终态", text)

    def test_loan_module_sets_evidence_boundaries(self):
        text = self.read_loan()
        for value in (
            "MQ receipt 不等于放款完成",
            "重新分配不等于新资方推送",
            "Loki 失败不等于 Hold",
            "成功通知不等于 REPAYING",
        ):
            self.assertIn(value, text)

    def test_loan_module_delegates_hold_lifecycle(self):
        text = self.read_loan()
        self.assertIn("references/modules/hold.md", text)
        self.assertTrue(
            any(
                phrase in text
                for phrase in (
                    "loan.md 不展开 Hold 生命周期",
                    "详细生命周期见 hold.md",
                    "只保留结果边界",
                )
            )
        )
        self.assertNotIn("| 解H |", text)
        self.assertNotIn("ReleaseHoldOrderServiceImpl#releaseHoldOrder", text)
        for lifecycle_anchor in (
            "ReleaseHoldOrderJob",
            "ReleaseHoldSendToLokiJob",
            "CancelHoldOrdersJob",
        ):
            self.assertNotIn(lifecycle_anchor, text)
            self.assertNotIn(f"{lifecycle_anchor}.process.start", text)
        self.assertNotIn("## Hold 生命周期", text)
        self.assertNotIn("### 解 H", text)

    def test_loan_module_covers_outcome_and_health_query_anchors(self):
        text = self.read_loan()
        for value in (
            "LokiResultRequest OrderDataDTO is:",
            "不同 fundPlan",
            "推给loki:",
            "[放款成功]协议共享协议号订单:",
            "按 `order/order-batch/loki-webapp` 分服务健康检查",
        ):
            self.assertIn(value, text)

    def test_loan_module_covers_outcomes_and_special_entries(self):
        text = self.read_loan()
        for value in (
            "放款失败",
            "换资方",
            "放款成功",
            "健康检查",
            "特项额度",
        ):
            self.assertIn(value, text)

    def test_skill_routes_buffer_intentions_to_loan_module(self):
        text = SKILL_FILE.read_text(encoding="utf-8")
        loan_route = next(
            line
            for line in text.splitlines()
            if "references/modules/loan.md" in line and line.startswith("|")
        )
        for keyword in ("缓冲池", "再分发", "缓冲池出池"):
            self.assertIn(keyword, loan_route)
        self.assertNotIn("拒就赔", loan_route)
        self.assertNotIn("提前结清", loan_route)

    def test_loan_module_covers_buffer_pool_lifecycle(self):
        text = self.read_loan()
        for value in (
            "ApplyLoanSendLokiQHandler#sendQToLoki",
            "isBufferBlocked",
            "缓冲池内存在停止路由或暂停路由的控制记录，不进行推送",
            "LokiLoanResultServiceImpl#creditApplyFail",
            "LokiLoanResultServiceImpl#useCreditFail",
            "exitPoolWhenLoanFailed",
            "LoanStageEnum.APPLY",
            "LoanStageEnum.USE",
            "systemCode = fund-center",
            "RedistributionHandler#inbound",
            "HandleRedistributeBufferJob#process",
            "handleBufferStatus",
            "handleRedistribution",
            "RedistributionHandler#redistribute",
            "renewRoute",
            "再分发规则匹配开始,请求参数:{}",
            "再分发规则入池成功",
            "再分发缓冲记录处理开始",
            "待再分发处理缓冲记录数:{}",
            "开始再分发",
            "再分发结束",
        ):
            self.assertIn(value, text)

    def test_loan_module_explains_buffer_result_semantics(self):
        text = self.read_loan()
        for value in (
            "inboundedNeedRedistribute",
            "needRedistribute",
            "isHoldOn",
            "redistributeStatus != NONE",
            "bufferStatus",
            "routeStatus",
            "redistributeRequired",
            "fundsFailStage",
            "缓冲池出池成功不是放款成功或最终失败证据",
            "需要再分发不等于换资方",
            "缓冲池命中后暂时没有新的 `推给loki:`",
            "不能直接判定失败",
        ):
            self.assertIn(value, text)

    def test_loan_module_excludes_non_loan_flows(self):
        text = self.read_loan()
        self.assertIn("[特项额度]", text)
        self.assertNotIn("拒就赔", text)
        self.assertNotIn("提前结清", text)


if __name__ == "__main__":
    unittest.main()
