"""批量导出业务规则：时间线服务、分片计划生成与跨模块链路校验。"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.store import store
from app.engine.export_sharder import ExportSharder

MODULE = "batch_export"
REQUIRED_FIELDS = ["任务编号", "查询SQL", "导出格式"]
STATUS_ORDER = ["草稿", "运行中", "已完成", "已失败"]
ACTION_RULES = {"启动导出": "运行中", "确认完成": "已完成", "标记失败": "已失败"}
NEGATIVE_ACTIONS = []


class BatchExportService:
    def get_timeline(self) -> list[dict[str, Any]]:
        rows = store.rows(MODULE)
        today = date.today()
        items: list[dict] = []
        for i, row in enumerate(rows):
            start = (today - timedelta(days=7 - i * 2)).isoformat()
            end = (today + timedelta(days=3 - i)).isoformat()
            shard_info = ""
            shards = row.get("_shards")
            if shards:
                shard_info = f"，已生成 {len(shards)} 个分片"
            items.append({
                "id": int(row.get("id", i + 1)),
                "name": str(row.get("任务编号", "")),
                "start": start,
                "end": end,
                "status": str(row.get("status", STATUS_ORDER[i % len(STATUS_ORDER)])),
                "logs": f"[{start}] 作业启动{shard_info}\n[{start}] 正在处理...\n[{end}] 任务{'完成' if row.get('status') == '已完成' else '进行中'}",
            })
        return items

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry:
            sharder = ExportSharder()
            entry["_shard_plan"] = sharder.generate_shards(entry_id)
            entry["_validate"] = sharder.validate_export_chain(entry_id)
        return entry

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [f for f in REQUIRED_FIELDS if not str(values.get(f) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(r.get("id", 0)) for r in rows), default=0) + 1}
        entry.update({f: values.get(f) for f in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"导出任务 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于批量导出可执行范围"
        target = ACTION_RULES[action]
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS

        # 启动导出时自动生成 shards
        if action == "启动导出":
            sharder = ExportSharder()
            sharder.generate_shards(entry_id)

        return entry, f"导出任务已{action}"

    def get_shard_plan(self, entry_id: int) -> dict[str, Any]:
        sharder = ExportSharder()
        return sharder.generate_shards(entry_id)

    def get_shard_sql(self, entry_id: int, shard_id: int) -> dict[str, Any]:
        sharder = ExportSharder()
        return sharder.build_shard_sql(entry_id, shard_id)

    def validate_chain(self, entry_id: int) -> dict[str, Any]:
        sharder = ExportSharder()
        return sharder.validate_export_chain(entry_id)
