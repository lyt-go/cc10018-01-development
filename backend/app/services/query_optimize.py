"""查询优化业务规则：状态流转、字段校验、SQL分析与优化建议自动生成。"""
from __future__ import annotations

from typing import Any

from app.store import store
from app.engine.query_optimizer import QueryOptimizer

MODULE = "query_optimize"
LIST_FIELDS = ["建议编号", "关联接口", "慢查询摘要", "执行计划", "索引建议", "分区裁剪", "预期提升", "优化状态"]
REQUIRED_FIELDS = ["建议编号", "关联接口", "慢查询摘要"]
STATUS_ORDER = ["草稿", "分析中", "优化中", "已完成"]
ACTION_RULES = {"开始分析": "分析中", "开始优化": "优化中", "确认完成": "已完成"}
NEGATIVE_ACTIONS = []


class QueryOptimizeService:
    def list_entries(
        self,
        *,
        filters: dict[str, str] | None = None,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        for field, expected in (filters or {}).items():
            rows = [row for row in rows if expected.casefold() in str(row.get(field, "")).casefold()]
        if keyword:
            rows = [row for row in rows if keyword.casefold() in str(row.get("建议编号", "")).casefold()]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in LIST_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"优化建议 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于查询优化可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"优化建议已{action}"

    def auto_analyze(self, api_id: int) -> dict[str, Any] | None:
        """自动分析指定API的SQL并创建优化记录。"""
        optimizer = QueryOptimizer()
        return optimizer.create_optimize_entry(api_id)

    def analyze_by_id(self, entry_id: int) -> dict[str, Any]:
        """对已有的优化记录重新分析其关联接口的SQL。"""
        entry = store.find(MODULE, entry_id)
        if not entry:
            return {"ok": False, "error": f"记录 {entry_id} 不存在"}

        api_code = entry.get("关联接口", "")
        api = next((r for r in store.rows("api_service") if r.get("接口编号") == api_code), None)
        if not api:
            return {"ok": False, "error": f"关联接口 {api_code} 不存在"}

        optimizer = QueryOptimizer()
        report = optimizer.analyze_sql(api.get("查询SQL", ""), api_id=api.get("id"))
        entry["执行计划"] = report.get("execution_plan", {})
        entry["索引建议"] = "; ".join(f"{s['field']}({s['type']})" for s in report.get("index_suggestions", [])) or "暂无"
        entry["分区裁剪"] = "; ".join(f"{s['field']}({s['strategy']})" for s in report.get("partition_suggestions", [])) or "暂无"
        entry["预期提升"] = report.get("estimated_improvement", "")
        return {"ok": True, "entry": entry, "report": report}
