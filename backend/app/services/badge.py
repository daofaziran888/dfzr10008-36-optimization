"""数据产品认证业务规则：状态流转、有效期状态推导与延期并发裁决都收在这里。

核心口径：
1. 延期限于「未过期且已通过」的认证；过期认证不能续期。
2. 每次延期生成一条带审批时间的有效期状态记录，同一认证只保留一个生效结论：
   冲突时以批准时间较晚、且新期限覆盖原有效期的记录为准，其余标记为未采纳。
3. 重复延期（相同幂等键，或同审批人/同原期限/同新期限）直接返回原审核结果，不新增记录。
4. 有效期状态（未认证/有效/已过期）按参考日期动态推导，产品发布准入只读这一份结论。
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from typing import Any

from app.clock import is_expired, parse_date, parse_datetime, reference_date
from app.store import store

MODULE = "badge"
REQUIRED_FIELDS = ["认证编号", "产品名称", "认证类型"]
STATUS_ORDER = ["申请中", "已通过", "已驳回", "已过期"]

# 有效期状态（对外唯一口径，产品发布准入也读它）
STATE_NONE = "未认证"
STATE_VALID = "有效"
STATE_EXPIRED = "已过期"
VALIDITY_STATES = [STATE_NONE, STATE_VALID, STATE_EXPIRED]

# 延期记录裁决结论
CONCLUSION_ACTIVE = "生效中"
CONCLUSION_SUPERSEDED = "未采纳"

SUPERSEDED_REASON = "存在批准时间更晚且覆盖原有效期的延期结论"


class BadgeService:
    # ------------------------------------------------------------------ 查询
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
        today: date | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        current = today or reference_date()
        rows = [self.project_entry(row, current) for row in store.rows(MODULE)]
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("认证编号", ""))]
        if status:
            # 既能按工作流状态过滤，也能按唯一有效期状态过滤
            rows = [
                row
                for row in rows
                if row.get("status") == status or row.get("有效期状态") == status
            ]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int, *, today: date | None = None) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        return self.project_entry(entry, today or reference_date())

    # ------------------------------------------------------------------ 登记
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        # 其余业务字段允许登记时一并带上
        for field in ("认证标准", "认证机构", "有效期限", "认证结果", "认证状态"):
            if values.get(field) is not None:
                entry[field] = values.get(field)
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["extension_history"] = []
        entry["effective_extension_id"] = None
        rows.append(entry)
        return entry, []

    # ---------------------------------------------------------- 通用审批动作
    def run_action(
        self, entry_id: int, action: str, *, today: date | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"认证记录 {entry_id} 不存在或已归档"
        if action == "延期认证":
            return None, "延期认证请调用专用延期接口，提交审批人、新有效期限与审批时间"
        if action == "通过认证":
            if entry.get("status") != "申请中":
                return None, f"仅「申请中」的认证可通过，当前状态为「{entry.get('status')}」"
            entry["status"] = "已通过"
            entry["pending"] = False
            entry["abnormal"] = False
            if not entry.get("认证结果"):
                entry["认证结果"] = "标准符合性审核通过"
            return self.project_entry(entry, today or reference_date()), "认证记录已通过认证"
        if action == "驳回认证":
            if entry.get("status") != "申请中":
                return None, f"仅「申请中」的认证可驳回，当前状态为「{entry.get('status')}」"
            entry["status"] = "已驳回"
            entry["pending"] = False
            entry["abnormal"] = True
            return self.project_entry(entry, today or reference_date()), "认证记录已驳回认证"
        return None, f"动作「{action}」不属于数据产品认证可执行范围"

    # ------------------------------------------------------------------ 延期
    def extend_certification(
        self,
        entry_id: int,
        values: dict[str, Any],
        *,
        today: date | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        """对一条认证执行延期；所有写入前校验失败都返回原因且不落任何数据。"""
        current = today or reference_date()
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"认证记录 {entry_id} 不存在或已归档"

        approver = str(values.get("审批人") or "").strip()
        if not approver:
            return None, "延期失败：缺少审批人，无法生成认证有效期状态"

        new_until = parse_date(values.get("新有效期限"))
        if new_until is None:
            return (
                None,
                f"延期失败：新有效期限「{values.get('新有效期限')}」非法，"
                "应为 YYYY-MM-DD 格式的日期",
            )

        approved_at = parse_datetime(values.get("审批时间"))
        if approved_at is None:
            # 未显式给审批时间时，落在参考日期上并带当前时刻，保证并发可比较先后
            approved_at = datetime.combine(current, datetime.now().time())

        request_id = str(values.get("request_id") or values.get("幂等键") or "").strip()
        history: list[dict[str, Any]] = entry.setdefault("extension_history", [])

        # 幂等：相同幂等键直接返回原审核结果（失败重试也走这里）
        if request_id:
            for record in history:
                if record.get("request_id") == request_id:
                    return (
                        self.project_entry(entry, current),
                        "重复延期请求，返回原认证审核结果",
                    )

        # 先取当前生效口径，再做边界校验；任何失败都在写入前返回
        effective = self._effective_cert(entry, current)
        if effective is None:
            return None, "延期失败：该认证尚未通过审核，没有可续期的有效认证"
        current_end = parse_date(effective["有效期限"])
        if current_end is None:
            return None, "延期失败：原认证有效期限缺失或格式非法，无法判定过期边界"

        # 并发延期时各请求都针对同一个原有效期发起，因此允许请求显式声明原有效期限；
        # 未声明则对应当前生效期限，即串行延期（在上一次延期结果上再延期）的场景。
        declared_original = parse_date(values.get("原有效期限"))
        if declared_original is not None:
            known = {current_end, *(parse_date(item.get("原有效期限")) for item in history)}
            if declared_original not in known:
                return (
                    None,
                    f"延期失败：声明的原有效期限 {declared_original} "
                    "与该认证的有效期记录不一致",
                )
            base_end = declared_original
        else:
            base_end = current_end

        if is_expired(base_end, today=current):
            return (
                None,
                f"延期失败：认证已过期（原有效期限 {base_end}，当前日期 {current}），"
                "过期认证不能续期",
            )
        if new_until <= base_end:
            return (
                None,
                f"延期失败：新有效期限 {new_until} 必须晚于原有效期限 {base_end}",
            )

        # 重复延期：同审批人、同原期限、同新期限视为同一笔，返回原结果不新增记录
        for record in history:
            if (
                record.get("审批人") == approver
                and parse_date(record.get("原有效期限")) == base_end
                and parse_date(record.get("新有效期限")) == new_until
            ):
                return (
                    self.project_entry(entry, current),
                    "重复延期请求，返回原认证审核结果",
                )

        snapshot = deepcopy(
            {
                "extension_history": entry.get("extension_history", []),
                "effective_extension_id": entry.get("effective_extension_id"),
                "有效期限": entry.get("有效期限"),
                "认证结果": entry.get("认证结果"),
            }
        )
        try:
            record = {
                "id": max((int(item.get("id", 0)) for item in history), default=0) + 1,
                "request_id": request_id or None,
                "审批人": approver,
                "审批时间": approved_at.strftime("%Y-%m-%d %H:%M:%S"),
                "原有效期限": base_end.strftime("%Y-%m-%d"),
                "新有效期限": new_until.strftime("%Y-%m-%d"),
                "认证审核结果": str(values.get("认证审核结果") or "延期审核通过，标准符合性持续有效"),
                "结论": CONCLUSION_SUPERSEDED,
                "未采纳原因": None,
            }
            history.append(record)
            self._reconcile(entry, current)
        except Exception:  # 中断后恢复上一份认证，避免留下半成品有效期状态
            entry["extension_history"] = snapshot["extension_history"]
            entry["effective_extension_id"] = snapshot["effective_extension_id"]
            entry["有效期限"] = snapshot["有效期限"]
            entry["认证结果"] = snapshot["认证结果"]
            return None, "延期处理中断，已恢复上一份认证，请重试"

        return self.project_entry(entry, current), "认证延期已批准，唯一有效认证有效期状态已更新"

    # ---------------------------------------------------------- 对外唯一口径
    def project_entry(self, entry: dict[str, Any], current: date) -> dict[str, Any]:
        """生成对外视图：推导唯一有效期状态与生效认证，不污染仓库原始字段。"""
        view = dict(entry)
        history = list(entry.get("extension_history", []))
        view["延期记录"] = history
        view["延期次数"] = len(history)
        effective = self._effective_cert(entry, current)
        if effective is None:
            view["有效期状态"] = STATE_NONE
            view["生效认证"] = None
            return view
        if is_expired(effective["有效期限"], today=current):
            # 已过期认证不再是「生效认证」：产品侧只能读到空，旧标准符合性结果停止展示
            view["有效期状态"] = STATE_EXPIRED
            view["生效认证"] = None
            return view
        view["生效认证"] = effective
        view["有效期状态"] = STATE_VALID
        return view

    def active_certification(
        self, product_name: str, *, today: date | None = None
    ) -> dict[str, Any] | None:
        """产品侧只读一个有效认证：取该产品名下唯一处于「有效」状态的认证结论。"""
        current = today or reference_date()
        for row in store.rows(MODULE):
            if str(row.get("产品名称") or "") != product_name:
                continue
            view = self.project_entry(row, current)
            if view.get("有效期状态") == STATE_VALID:
                return view.get("生效认证")
        return None

    # ------------------------------------------------------------------ 内部
    def _effective_cert(self, entry: dict[str, Any], current: date) -> dict[str, Any] | None:
        """当前唯一生效认证：延期裁决的赢家优先，否则回退到原认证（需已通过）。"""
        winner_id = entry.get("effective_extension_id")
        if winner_id is not None:
            for record in entry.get("extension_history", []):
                if int(record.get("id", 0)) == int(winner_id):
                    return {
                        "来源记录": f"延期#{record['id']}",
                        "认证编号": entry.get("认证编号"),
                        "审批人": record.get("审批人"),
                        "审批时间": record.get("审批时间"),
                        "有效期限": record.get("新有效期限"),
                        "认证结果": record.get("认证审核结果"),
                    }
        if entry.get("status") == "已通过":
            return {
                "来源记录": "原认证",
                "认证编号": entry.get("认证编号"),
                "审批人": entry.get("认证机构"),
                "审批时间": None,
                "有效期限": entry.get("有效期限"),
                "认证结果": entry.get("认证结果"),
            }
        return None

    def _reconcile(self, entry: dict[str, Any], current: date) -> None:
        """并发裁决：在所有覆盖原有效期的延期记录里，取批准时间最晚者为唯一生效结论。"""
        history: list[dict[str, Any]] = entry.setdefault("extension_history", [])
        eligible = [
            record
            for record in history
            if (parse_date(record.get("新有效期限")) and parse_date(record.get("原有效期限")))
            and parse_date(record["新有效期限"]) > parse_date(record["原有效期限"])
        ]
        for record in history:
            record["结论"] = CONCLUSION_SUPERSEDED
            record["未采纳原因"] = SUPERSEDED_REASON
        if not eligible:
            entry["effective_extension_id"] = None
            return
        winner = max(
            eligible,
            key=lambda item: (parse_datetime(item.get("审批时间")) or datetime.min, int(item["id"])),
        )
        winner["结论"] = CONCLUSION_ACTIVE
        winner["未采纳原因"] = None
        entry["effective_extension_id"] = winner["id"]
        # 工作流字段与唯一口径对齐：产品侧旧的标准符合性结果不再继续展示
        entry["有效期限"] = winner["新有效期限"]
        entry["认证结果"] = winner["认证审核结果"]
        entry["status"] = "已通过"
        entry["pending"] = False
        entry["abnormal"] = False
