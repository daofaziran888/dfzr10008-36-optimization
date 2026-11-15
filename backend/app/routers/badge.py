"""数据产品认证接口：维护认证记录，覆盖通过认证、驳回认证、延期认证等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.badge import VALIDITY_STATES
from app.services.badge import BadgeService

router = APIRouter(prefix="/api/badge", tags=["数据产品认证"])

service = BadgeService()

LIST_FIELDS = ["认证编号", "产品名称", "认证类型", "认证标准", "认证机构", "有效期限", "认证结果", "认证状态"]
STATUSES = ["申请中", "已通过", "已驳回", "已过期", *VALIDITY_STATES]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按认证编号检索"),
    status: str | None = Query(default=None, description="工作流状态或有效期状态：申请中、已通过、已驳回、已过期、有效、未认证"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按认证编号与状态过滤数据产品认证列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/active")
def get_active_certification(
    product_name: str = Query(..., description="数据产品名称，只返回该产品唯一有效的认证"),
) -> dict[str, Any]:
    """产品发布准入读取的唯一有效认证；暂无有效认证时给出空态而不是报错。"""
    cert = service.active_certification(product_name)
    if cert is None:
        return {"product_name": product_name, "has_active": False, "certification": None,
                "message": "暂无有效认证，产品发布准入不通过"}
    return {"product_name": product_name, "has_active": True, "certification": cert}


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出数据产品认证清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "badge", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条认证记录明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"认证记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条认证记录，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="认证记录已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条认证记录执行通过认证、驳回认证；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/extend", response_model=ActionResult)
def extend_certification(entry_id: int, payload: EntryPayload) -> ActionResult:
    """延期认证：限于未过期认证；生成唯一有效期状态，并发冲突时较晚批准且覆盖原有效期者生效。

    提交字段：审批人、新有效期限（必填），审批时间（可选，缺省取当前时刻），
    request_id/幂等键（可选，重复提交直接返回原审核结果）。
    """
    entry, message = service.extend_certification(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
