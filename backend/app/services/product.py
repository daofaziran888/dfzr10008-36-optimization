"""数据产品定义业务规则：状态流转、字段校验、发布准入与认证口径都收在这里。

发布准入只读认证侧推导出来的唯一有效认证；没有有效认证（未认证/已过期/被未采纳的
延期结论）一律不允许发布，避免继续读旧的标准符合性结果。
"""
from __future__ import annotations

from typing import Any

from app.services.badge import BadgeService
from app.store import store

MODULE = "product"
REQUIRED_FIELDS = ["产品编号", "产品名称", "产品类型"]
STATUS_ORDER = ["草稿", "开发中", "已发布", "已下线"]
# 动作 -> (允许的来源状态, 目标状态)
ACTION_RULES = {
    "发布产品": ({"草稿", "开发中"}, "已发布"),
    "下线产品": ({"已发布"}, "已下线"),
    "删除产品": ({"已下线"}, "已下线"),
}
NEGATIVE_ACTIONS = ["下线产品"]


class ProductService:
    def __init__(self, badge_service: BadgeService | None = None) -> None:
        self.badge_service = badge_service or BadgeService()

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = [self._with_certification(row) for row in store.rows(MODULE)]
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("产品编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        return self._with_certification(entry)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"数据产品 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于数据产品定义可执行范围"
        allowed_sources, target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        if entry.get("status") not in allowed_sources:
            return (
                None,
                f"「{entry.get('status')}」状态的产品不能执行{action}，"
                f"仅 {'、'.join(sorted(allowed_sources))} 状态可执行",
            )
        if action == "发布产品":
            cert = self.badge_service.active_certification(str(entry.get("产品名称") or ""))
            if cert is None:
                return (
                    None,
                    f"发布准入不通过：产品「{entry.get('产品名称')}」暂无有效认证，"
                    "请先完成数据产品认证并确保认证在有效期内",
                )
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return self._with_certification(entry), f"数据产品已{action}"

    def _with_certification(self, entry: dict[str, Any]) -> dict[str, Any]:
        """产品只读取一个有效认证；空态时显式标注，不展示旧标准符合性结果。"""
        view = dict(entry)
        cert = self.badge_service.active_certification(str(entry.get("产品名称") or ""))
        view["有效认证"] = cert
        view["认证有效期状态"] = "有效" if cert else "暂无有效认证"
        return view
