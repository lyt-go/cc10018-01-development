"""接口版本接口：维护版本管理，覆盖开始灰度、全量发布、执行回滚等动作。"""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.schemas import ActionPayload, ActionResult, EntryPayload, PageResult
from app.services.api_version import ApiVersionService

router = APIRouter(prefix="/api/api_version", tags=["接口版本"])

service = ApiVersionService()

LIST_FIELDS = ["版本编号", "接口编号", "变更说明", "旧SQL摘要", "新SQL摘要", "兼容标记", "生效时间", "回滚版本"]
STATUSES = ["草稿", "灰度中", "已全量", "已回滚"]


def query_filters(request: Request) -> dict[str, str]:
    """只接受当前模块声明过的字段，忽略分页等保留参数。"""
    return {
        key: value.strip()
        for key, value in request.query_params.items()
        if key in LIST_FIELDS and value.strip()
    }


@router.get("", response_model=PageResult[dict])
def list_entries(
    request: Request,
    keyword: str | None = Query(default=None, description="按版本编号检索"),
    status: str | None = Query(default=None, description="草稿、灰度中、已全量、已回滚"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResult[dict]:
    """按页面字段、版本编号关键字与状态过滤接口版本列表。"""
    items, total = service.list_entries(
        filters=query_filters(request), keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries(
    request: Request,
    keyword: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> StreamingResponse:
    """下载当前筛选条件下的 UTF-8 CSV；必须声明在 /{entry_id} 之前。"""
    items, _ = service.list_entries(
        filters=query_filters(request), keyword=keyword, status=status, page=1, size=1000000)
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["id", *LIST_FIELDS, "status"])
    for item in items:
        row = []
        for value in [item.get("id"), *(item.get(field, "") for field in LIST_FIELDS), item.get("status", "")]:
            text = "" if value is None else str(value)
            row.append("'" + text if text.startswith(("=", "+", "-", "@")) else text)
        writer.writerow(row)
    return StreamingResponse(
        iter([output.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="api_version.csv"'})


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条版本管理明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"版本管理 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: dict[str, object]) -> ActionResult:
    """登记一条版本管理，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="版本管理已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: ActionPayload) -> ActionResult:
    """对单条版本管理执行开始灰度、全量发布、执行回滚；不允许的动作会被拦下并说明原因。"""
    entry, message = service.run_action(entry_id, payload.action.strip())
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/{entry_id}/version-chain")
def get_version_chain(entry_id: int) -> dict:
    """获取接口版本的版本管理链结果（版本→灰度→API服务）。"""
    from app.engine.chain_orchestrator import ChainOrchestrator
    orch = ChainOrchestrator()
    result = orch.run_version_manage_chain(entry_id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result)
    return result


@router.get("/{entry_id}/rollback-check")
def rollback_check(entry_id: int) -> dict:
    """检查版本回滚可行性：回滚目标版本是否存在、关联接口是否可用。"""
    entry = service.get_entry(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"版本 {entry_id} 不存在")

    rollback_ver = entry.get("回滚版本", "")
    from app.store import store
    target = next((r for r in store.rows("api_version") if r.get("版本编号") == rollback_ver), None)
    api = next((r for r in store.rows("api_service") if r.get("接口编号") == entry.get("接口编号", "")), None)

    return {
        "ok": target is not None and api is not None,
        "current_version": entry.get("版本编号"),
        "rollback_version": rollback_ver,
        "rollback_target_exists": target is not None,
        "api_exists": api is not None,
        "api_status": api.get("status") if api else None,
    }
