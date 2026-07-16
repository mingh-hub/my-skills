from pathlib import Path
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEBT_MODULE = SKILL_ROOT / "references" / "modules" / "debt.md"
SKILL_FILE = SKILL_ROOT / "SKILL.md"


class DebtModuleTest(unittest.TestCase):
    def read_debt(self):
        self.assertTrue(DEBT_MODULE.exists(), "references/modules/debt.md must exist")
        return DEBT_MODULE.read_text(encoding="utf-8")

    def test_skill_routes_debt_transfer_to_debt_module(self):
        text = SKILL_FILE.read_text(encoding="utf-8")
        self.assertIn("references/modules/debt.md", text)
        for keyword in (
            "债转",
            "债权转让",
            "合同债转",
            "期供代偿",
            "债转回购",
        ):
            self.assertIn(keyword, text)

        repay_route = next(
            line
            for line in text.splitlines()
            if "references/modules/repay.md" in line and line.startswith("|")
        )
        self.assertNotIn("债转", repay_route)

    def test_debt_module_is_contract_no_first(self):
        text = self.read_debt()
        self.assertIn("contractNo", text)
        self.assertIn("默认且主要", text)
        self.assertIn(
            'serviceName:"order-batch" AND message:"AccountDebtTransferConsumer推进来的消息ID及消息内容:" AND message:"{contractNo}"',
            text,
        )
        self.assertIn("只有用户明确提供 `traceId`", text)

    def test_debt_query_resolves_order_to_contract_then_trace(self):
        text = self.read_debt()
        order_step = "如果只提供 `orderId`，先根据订单号查询并提取 `contractNo`"
        contract_step = "用 `contractNo` 定位债转短信入口"
        trace_step = "从入口日志提取 `traceId`，再查询整个链路日志"

        self.assertIn(order_step, text)
        self.assertIn('serviceName:"order" AND message:"{orderId}"', text)
        self.assertIn(contract_step, text)
        self.assertIn(trace_step, text)
        self.assertIn('traceId:"{value}"', text)
        self.assertLess(text.index(order_step), text.index(contract_step))
        self.assertLess(text.index(contract_step), text.index(trace_step))

    def test_debt_module_documents_production_mq_fields(self):
        text = self.read_debt()
        for value in (
            "一次债转时，`contractNo` 与 `originalAccountId` 相同",
            "`currentAccountId` 以 `ZC` 开头表示一次债转",
            "以 `ZZC` 开头表示二次债转",
            "债转前渠道编码",
            "债转后（当前）渠道编码",
            "债转前资金计划编码",
            "债转后（当前）资金计划编码",
            "`billNo`",
            "借据号",
            "`PERIOD`-期供代偿",
            "`CONTRACT`-合同债转回购",
            "`ORIGINAL`-现状分配",
            "`REPO`-回购",
            '"contractNo":"CK202511090008653"',
            '"currentAccountId":"ZCK202511090008653"',
            '"billNo":"DU2511090066796266"',
            "#### 一次债转报文",
            "#### 二次债转报文",
            '"contractNo":"CK202508110000003"',
            '"originalAccountId":"ZCK202508110000003"',
            '"currentAccountId":"ZZCK202508110000003"',
            '"billNo":"10401000093855083"',
            "因此属于二次债转",
        ):
            self.assertIn(value, text)

        self.assertNotIn("`originalAccountId` / `currentAccountId`", text)
        self.assertNotIn("债转前后账户号", text)
        self.assertNotIn("原账户、原计划", text)
        self.assertNotIn("以 `ZCK` 开头表示一次债转", text)
        self.assertNotIn("以 `ZZCK` 开头表示二次债转", text)

    def test_debt_module_covers_order_batch_to_order_flow(self):
        text = self.read_debt()
        for value in (
            "com.xhqb.order.batch.service.AccountDebtTransferConsumer#consume",
            "account-credit-transfer",
            "AccountDebtTransferConsumer推进来的消息ID及消息内容:",
            "RepayOrderServiceImpl#syncRepaySingleOrder",
            "同步单个订单还款状态,查询中腾信账务信息,ztxAccountInfo:",
            "RepayOrderServiceImpl syncClaimsAccountInfo outBizCode is",
            "sendSmsIfDebtTransfer invoked start",
            "更新订单信息,",
        ):
            self.assertIn(value, text)

    def test_debt_module_explains_claim_type_branches(self):
        text = self.read_debt()
        for value in (
            "productClass",
            "sunflower",
            "claimType=PERIOD",
            "claimType=CONTRACT",
            "最后一期代偿",
            "普通期供代偿",
            "originalChannel=dcrd",
            "currentChannel=ctcf/zyx",
            "PERIOD 分支会提前 `return`",
        ):
            self.assertIn(value, text)

    def test_debt_module_distinguishes_receipt_from_completion(self):
        text = self.read_debt()
        self.assertIn("收到 MQ 不等于 order 侧处理完成", text)
        self.assertIn("协议事件日志不等于订单数据已同步", text)
        self.assertIn("AccountDebtTransferConsumer consume error.", text)
        self.assertIn("合同债转sms日志落库失败", text)
        self.assertIn("[syncRepaySingleOrder]出现并发请求:", text)


if __name__ == "__main__":
    unittest.main()
