"""批量导出 时间线接口：返回作业时间序列结构。"""
from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.schemas import ActionPayload, ActionResult, EntryPayload
from app.services.batch_export import BatchExportService

router = APIRouter(prefix="/api/batch_export", tags=["批量导出"])
service = BatchExportService()
LIST_FIELDS = ["任务编号", "查询SQL", "导出格式", "字段映射", "分片策略", "压缩编码", "写入路径", "结果校验"]
STATUSES = ["草稿", "运行中", "已完成", "已失败"]


def csv_cell(value: Any) -> str:
    text = str(value) if value is not None else ""
    if text and text[0] in "=+-@":
        text = "'" + text
    return '"' + text.replace('"', '""') + '"'


@router.get("")
def list_entries() -> dict[str, Any]:
    items = service.get_timeline()
    return {"items": items}


@router.get("/export")
def export_entries() -> StreamingResponse:
    items = service.get_timeline()
    buf = io.StringIO(newline="")
    writer = csv.writer(buf)
    all_keys = ["id"]
    if items:
        all_keys = list(items[0].keys())
    writer.writerow(all_keys)
    for item in items:
        writer.writerow([csv_cell(item.get(k, "")) for k in all_keys])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=batch_export.csv"})


@router.get("/{entry_id}")
def get_entry(entry_id: int) -> dict:
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"导出任务 {entry_id} 不存在")
    return entry


@router.post("")
def create_entry(payload: EntryPayload) -> ActionResult:
    entry_or_none, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="导出任务已登记", entry=entry_or_none)


@router.post("/{entry_id}/actions")
def run_action(entry_id: int, payload: ActionPayload) -> ActionResult:
    entry_or_none, message = service.run_action(entry_id, payload.action)
    if entry_or_none is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry_or_none)


@router.get("/{entry_id}/shard-plan")
def get_shard_plan(entry_id: int) -> dict:
    """获取导出任务的分片计划。"""
    plan = service.get_shard_plan(entry_id)
    if not plan.get("ok"):
        raise HTTPException(status_code=400, detail=plan)
    return plan


@router.get("/{entry_id}/shard-sql")
def get_shard_sql(entry_id: int, shard_id: int) -> dict:
    """获取指定分片的执行SQL。"""
    result = service.get_shard_sql(entry_id, shard_id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result)
    return result


@router.get("/{entry_id}/validate-chain")
def validate_export_chain(entry_id: int) -> dict:
    """校验导出任务的跨模块链路完整性（导出→清洗→缓存→审计）。"""
    return service.validate_chain(entry_id)
