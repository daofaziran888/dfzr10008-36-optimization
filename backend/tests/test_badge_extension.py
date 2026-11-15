"""认证延期边界与并发裁决的验收测试。

口径固定在业务当前日期 2026-11-13：
- BADGE-0002 原有效期 2026-10-31，已过期，不能续期；
- BADGE-0003 原有效期 2027-06-30，未过期，可延期至 2028-06-30；
- 周宁、陈然并发延期时，只保留批准较晚且覆盖原有效期的唯一有效期状态。
"""
from __future__ import annotations

import unittest
from datetime import date

from app.services.badge import (
    CONCLUSION_ACTIVE,
    CONCLUSION_SUPERSEDED,
    STATE_EXPIRED,
    STATE_NONE,
    STATE_VALID,
    BadgeService,
)
from app.services.product import ProductService
from app.store import store

TODAY = date(2026, 11, 13)
BADGE_0002 = 2
BADGE_0003 = 3


class BadgeExtensionTestCase(unittest.TestCase):
    def setUp(self) -> None:
        store.reset()
        # 显式恢复产品工作流初始状态，避免用例间按字母序执行时的状态污染
        store.find("product", 1)["status"] = "草稿"
        store.find("product", 2)["status"] = "开发中"
        store.find("product", 3)["status"] = "开发中"
        self.service = BadgeService()
        self.product_service = ProductService(self.service)

    def _extend(self, entry_id: int, **overrides):
        values = {
            "审批人": "周宁",
            "新有效期限": "2028-06-30",
            "审批时间": "2026-11-13 09:00:00",
        }
        values.update(overrides)
        return self.service.extend_certification(entry_id, values, today=TODAY)

    # ------------------------------------------------------------ 边界场景
    def test_expired_cert_cannot_be_renewed(self):
        """BADGE-0002 在 2026-11-13 已过期（2026-10-31），延期必须被拒并说明原因。"""
        entry = self.service.get_entry(BADGE_0002, today=TODAY)
        self.assertEqual(entry["有效期状态"], STATE_EXPIRED)
        self.assertIsNone(entry["生效认证"])

        result, message = self._extend(BADGE_0002)
        self.assertIsNone(result)
        self.assertIn("已过期", message)
        self.assertIn("2026-10-31", message)
        self.assertIn("不能续期", message)

        # 被拒后不允许留下任何延期记录
        self.assertEqual(store.find("badge", BADGE_0002)["extension_history"], [])

    def test_valid_cert_can_extend_to_2028(self):
        """BADGE-0003 未过期，延期至 2028-06-30 成功，且生成唯一有效期状态。"""
        entry = self.service.get_entry(BADGE_0003, today=TODAY)
        self.assertEqual(entry["有效期状态"], STATE_VALID)
        self.assertEqual(entry["有效期限"], "2027-06-30")

        result, message = self._extend(BADGE_0003)
        self.assertIsNotNone(result, message)
        self.assertEqual(result["有效期限"], "2028-06-30")
        self.assertEqual(result["有效期状态"], STATE_VALID)
        self.assertEqual(result["延期次数"], 1)

        cert = result["生效认证"]
        self.assertEqual(cert["来源记录"], "延期#1")
        self.assertEqual(cert["有效期限"], "2028-06-30")
        self.assertEqual(cert["审批人"], "周宁")

    def test_expiry_boundary_day_is_still_valid(self):
        """到期当日不算过期：严格晚于有效期限才进入已过期。"""
        boundary = date(2026, 10, 31)
        entry = self.service.get_entry(BADGE_0002, today=boundary)
        self.assertEqual(entry["有效期状态"], STATE_VALID)

    def test_new_until_must_be_later_than_original(self):
        """新期限不晚于原期限时拒绝，并明确非法有效期限原因。"""
        result, message = self._extend(BADGE_0003, 新有效期限="2027-06-30")
        self.assertIsNone(result)
        self.assertIn("必须晚于原有效期限", message)

        result, message = self._extend(BADGE_0003, 新有效期限="2027-01-01")
        self.assertIsNone(result)
        self.assertIn("必须晚于原有效期限", message)

    def test_malformed_new_until_is_rejected_with_reason(self):
        result, message = self._extend(BADGE_0003, 新有效期限="2028/06/30")
        self.assertIsNone(result)
        self.assertIn("新有效期限", message)
        self.assertIn("非法", message)

    def test_missing_approver_is_rejected(self):
        result, message = self._extend(BADGE_0003, 审批人="")
        self.assertIsNone(result)
        self.assertIn("审批人", message)

    # ------------------------------------------------------------ 并发裁决
    def test_concurrent_extensions_keep_only_later_approved_winner(self):
        """周宁与陈然同时延期 BADGE-0003：较晚批准且覆盖原有效期者唯一生效。"""
        first, msg1 = self._extend(
            BADGE_0003, 审批人="周宁", 审批时间="2026-11-13 09:00:00",
            原有效期限="2027-06-30", request_id="req-zhou",
        )
        second, msg2 = self._extend(
            BADGE_0003, 审批人="陈然", 审批时间="2026-11-13 10:30:00",
            原有效期限="2027-06-30", request_id="req-chen",
        )
        self.assertIsNotNone(first, msg1)
        self.assertIsNotNone(second, msg2)

        entry = self.service.get_entry(BADGE_0003, today=TODAY)
        history = entry["延期记录"]
        self.assertEqual(len(history), 2)

        conclusions = {record["审批人"]: record["结论"] for record in history}
        self.assertEqual(conclusions["陈然"], CONCLUSION_ACTIVE)
        self.assertEqual(conclusions["周宁"], CONCLUSION_SUPERSEDED)

        # 唯一有效认证是较晚批准的陈然版本，覆盖原有效期
        self.assertEqual(entry["effective_extension_id"], history[1]["id"])
        self.assertEqual(entry["生效认证"]["审批人"], "陈然")
        self.assertEqual(entry["生效认证"]["有效期限"], "2028-06-30")
        self.assertEqual(entry["有效期限"], "2028-06-30")
        self.assertEqual(entry["有效期状态"], STATE_VALID)

        superseded = next(record for record in history if record["审批人"] == "周宁")
        self.assertIsNotNone(superseded["未采纳原因"])
        self.assertIn("更晚", superseded["未采纳原因"])

    def test_arrival_order_does_not_change_winner(self):
        """请求到达顺序颠倒也不影响：始终按批准时间裁决。"""
        self._extend(BADGE_0003, 审批人="陈然", 审批时间="2026-11-13 10:30:00",
                     原有效期限="2027-06-30")
        self._extend(BADGE_0003, 审批人="周宁", 审批时间="2026-11-13 09:00:00",
                     原有效期限="2027-06-30")

        entry = self.service.get_entry(BADGE_0003, today=TODAY)
        self.assertEqual(entry["生效认证"]["审批人"], "陈然")
        active = [r for r in entry["延期记录"] if r["结论"] == CONCLUSION_ACTIVE]
        self.assertEqual(len(active), 1)

    def test_duplicate_extension_returns_original_result(self):
        """重复延期（同幂等键）返回原审核结果，不新增记录。"""
        first, _ = self._extend(BADGE_0003, request_id="idem-1", 审批时间="2026-11-13 09:00:00")
        again, message = self._extend(
            BADGE_0003, request_id="idem-1", 审批时间="2026-11-13 15:00:00",
        )
        self.assertIn("重复延期", message)
        self.assertEqual(again["延期次数"], 1)
        self.assertEqual(first["生效认证"]["审批时间"], again["生效认证"]["审批时间"])

    def test_retry_after_failure_keeps_state_and_then_succeeds(self):
        """失败重试：先因过期被拒（状态不变），修正参数后成功。"""
        failed, fail_msg = self._extend(BADGE_0002)
        self.assertIsNone(failed)
        self.assertEqual(store.find("badge", BADGE_0002)["extension_history"], [])

        # 同一失败请求重试，结论一致且仍不落数据
        retry, retry_msg = self._extend(BADGE_0002)
        self.assertIsNone(retry)
        self.assertEqual(fail_msg, retry_msg)

        ok, _ = self._extend(BADGE_0003)
        self.assertIsNotNone(ok)
        self.assertEqual(ok["延期次数"], 1)

    def test_rollback_restores_previous_certification_on_interruption(self):
        """延期写入中断时恢复上一份认证，不残留半成品记录。"""
        original = self.service._reconcile

        def broken_reconcile(entry, current):
            raise RuntimeError("模拟审批落库中断")

        self.service._reconcile = broken_reconcile
        try:
            result, message = self._extend(BADGE_0003)
        finally:
            self.service._reconcile = original
        self.assertIsNone(result)
        self.assertIn("中断", message)

        entry = store.find("badge", BADGE_0003)
        self.assertEqual(entry["extension_history"], [])
        self.assertIsNone(entry["effective_extension_id"])
        self.assertEqual(entry["有效期限"], "2027-06-30")
        self.assertIn("标准符合性", entry["认证结果"])

    # ------------------------------------------------------------ 产品侧口径
    def test_product_reads_single_active_certification(self):
        """数据产品定义只读一个有效认证；并发延期后取唯一赢家，旧结果不再显示。"""
        self._extend(BADGE_0003, 审批人="周宁", 审批时间="2026-11-13 09:00:00",
                     原有效期限="2027-06-30")
        self._extend(BADGE_0003, 审批人="陈然", 审批时间="2026-11-13 10:30:00",
                     原有效期限="2027-06-30")

        cert = self.service.active_certification("数据产品定义样例3")
        self.assertIsNotNone(cert)
        self.assertEqual(cert["审批人"], "陈然")
        self.assertEqual(cert["有效期限"], "2028-06-30")

        product = self.product_service.get_entry(3)
        self.assertEqual(product["认证有效期状态"], "有效")
        self.assertEqual(product["有效认证"]["审批人"], "陈然")

    def test_product_without_active_cert_gets_empty_state(self):
        """暂无有效认证时给出空态：未认证申请与已过期认证都不产生有效认证。"""
        self.assertIsNone(self.service.active_certification("数据产品定义样例1"))
        self.assertIsNone(self.service.active_certification("数据产品定义样例2"))

        product2 = self.product_service.get_entry(2)
        self.assertEqual(product2["认证有效期状态"], "暂无有效认证")
        self.assertIsNone(product2["有效认证"])

    def test_publish_gate_blocks_without_active_cert(self):
        """发布准入：无有效认证的产品不允许发布。"""
        # 产品2 关联的 BADGE-0002 已过期
        result, message = self.product_service.run_action(2, "发布产品")
        self.assertIsNone(result)
        self.assertIn("发布准入不通过", message)
        self.assertEqual(store.find("product", 2)["status"], "开发中")

        # 产品3 持有有效 BADGE-0003，可发布
        ok, msg = self.product_service.run_action(3, "发布产品")
        self.assertIsNotNone(ok, msg)
        self.assertEqual(ok["status"], "已发布")

    def test_filter_by_validity_state(self):
        """列表可按唯一有效期状态过滤。"""
        valid_rows, valid_total = self.service.list_entries(status=STATE_VALID, today=TODAY)
        expired_rows, expired_total = self.service.list_entries(status=STATE_EXPIRED, today=TODAY)
        none_rows, none_total = self.service.list_entries(status=STATE_NONE, today=TODAY)
        self.assertEqual({row["认证编号"] for row in valid_rows}, {"BADGE-0003"})
        self.assertEqual({row["认证编号"] for row in expired_rows}, {"BADGE-0002"})
        self.assertEqual({row["认证编号"] for row in none_rows}, {"BADGE-0001"})
        self.assertEqual(valid_total + expired_total + none_total, 3)

    def test_sequential_extensions_each_cover_previous_period(self):
        """连续两次正常延期：第二次基于第一次的新期限，始终只保留一个生效结论。"""
        first, _ = self._extend(BADGE_0003, 新有效期限="2028-06-30",
                                审批时间="2026-11-13 09:00:00")
        self.assertEqual(first["有效期限"], "2028-06-30")

        second, message = self.service.extend_certification(
            BADGE_0003,
            {"审批人": "周宁", "新有效期限": "2029-06-30",
             "审批时间": "2027-01-10 14:00:00"},
            today=date(2027, 1, 10),
        )
        self.assertIsNotNone(second, message)
        self.assertEqual(second["有效期限"], "2029-06-30")
        self.assertEqual(second["延期次数"], 2)
        active = [r for r in second["延期记录"] if r["结论"] == CONCLUSION_ACTIVE]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["新有效期限"], "2029-06-30")


if __name__ == "__main__":
    unittest.main()
