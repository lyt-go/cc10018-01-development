"""查询优化建议生成引擎：分析慢查询、生成索引建议、评估优化收益。

核心能力：
1. 执行计划模拟：基于SQL结构模拟执行代价
2. 索引建议生成：识别WHERE/JOIN/ORDER BY字段
3. 分区裁剪建议：识别时间范围查询并建议分区键
4. 收益评估：量化优化前后的预估性能提升
"""
from __future__ import annotations

import re
from typing import Any

from app.store import store


class QueryOptimizer:
    """查询优化建议生成引擎。"""

    COST_WEIGHTS = {
        "full_table_scan": 1000,
        "index_scan": 50,
        "sort": 200,
        "join_nested_loop": 300,
        "join_hash": 80,
    }

    def __init__(self) -> None:
        pass

    def analyze_slow_query(self, api_id: int) -> dict[str, Any]:
        """分析指定API接口的查询SQL，生成优化建议。"""
        api = store.find("api_service", api_id)
        if not api:
            return {"ok": False, "error": f"接口 {api_id} 不存在"}

        sql_text = api.get("查询SQL", "")
        return self.analyze_sql(sql_text, api_id=api_id)

    def analyze_sql(self, sql_text: str, *, api_id: int | None = None) -> dict[str, Any]:
        """分析SQL文本并生成完整的优化报告。"""
        report: dict[str, Any] = {
            "ok": True,
            "api_id": api_id,
            "sql_length": len(sql_text),
            "estimated_cost": 0,
            "execution_plan": {},
            "index_suggestions": [],
            "partition_suggestions": [],
            "rewrite_suggestions": [],
            "estimated_improvement": "",
        }

        sql_upper = sql_text.upper()

        # 1. 执行计划模拟
        plan_nodes = []
        cost = 0

        if "SELECT *" in sql_upper:
            cost += self.COST_WEIGHTS["full_table_scan"] * 0.5
            plan_nodes.append({"type": "Seq Scan", "detail": "全字段扫描", "cost": cost})

        table_count = sql_upper.count("FROM") + sql_upper.count("JOIN")
        if table_count > 1:
            join_cost = self.COST_WEIGHTS["join_nested_loop"] * (table_count - 1)
            cost += join_cost
            plan_nodes.append({"type": "Nested Loop Join", "detail": f"{table_count - 1} 次嵌套循环", "cost": join_cost})

        if "ORDER BY" in sql_upper:
            sort_cost = self.COST_WEIGHTS["sort"]
            cost += sort_cost
            plan_nodes.append({"type": "Sort", "detail": "外部排序", "cost": sort_cost})

        if "WHERE" not in sql_upper:
            cost += self.COST_WEIGHTS["full_table_scan"]
            plan_nodes.append({"type": "Seq Scan", "detail": "无WHERE条件，全表扫描", "cost": self.COST_WEIGHTS["full_table_scan"]})

        report["estimated_cost"] = int(cost)
        report["execution_plan"]["nodes"] = plan_nodes

        # 2. 索引建议
        where_fields = self._extract_where_fields(sql_text)
        for field in where_fields:
            report["index_suggestions"].append({
                "field": field,
                "type": "btree",
                "reason": f"WHERE 条件高频字段 {field}",
                "estimated_reduction": "60-80%",
            })

        join_fields = self._extract_join_fields(sql_text)
        for field in join_fields:
            report["index_suggestions"].append({
                "field": field,
                "type": "btree",
                "reason": f"JOIN 关联字段 {field}",
                "estimated_reduction": "50-70%",
            })

        # 3. 分区裁剪建议
        time_fields = self._extract_time_range_fields(sql_text)
        for field in time_fields:
            report["partition_suggestions"].append({
                "field": field,
                "strategy": "range",
                "granularity": "按月",
                "reason": f"检测到时间范围过滤 {field}",
            })

        # 4. 重写建议
        if re.search(r"\bOR\b", sql_upper):
            report["rewrite_suggestions"].append({
                "type": "union_rewrite",
                "message": "复杂OR条件建议拆分为UNION ALL以利用索引",
            })

        if sql_upper.count("SUBQUERY") + sql_upper.count("SELECT") > 2:
            report["rewrite_suggestions"].append({
                "type": "cte_rewrite",
                "message": "多层嵌套子查询建议改写为CTE提高可读性和优化器效率",
            })

        # 5. 收益评估
        if report["index_suggestions"]:
            report["estimated_improvement"] = f"创建索引后预估成本从 {cost} 降至 {cost * 0.2:.0f}（降低80%）"
        elif report["rewrite_suggestions"]:
            report["estimated_improvement"] = f"SQL重写后预估成本从 {cost} 降至 {cost * 0.5:.0f}（降低50%）"
        else:
            report["estimated_improvement"] = "当前SQL已较为优化"

        return report

    def create_optimize_entry(self, api_id: int) -> dict[str, Any] | None:
        """为指定API创建一条查询优化记录。"""
        report = self.analyze_slow_query(api_id)
        if not report.get("ok"):
            return None

        api = store.find("api_service", api_id)
        rows = store.rows("query_optimize")
        entry_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1

        idx_suggest = "; ".join(
            f"{s['field']}({s['type']})" for s in report["index_suggestions"]
        ) or "暂无"
        partition_suggest = "; ".join(
            f"{s['field']}({s['strategy']})" for s in report["partition_suggestions"]
        ) or "暂无"

        entry = {
            "id": entry_id,
            "status": "草稿",
            "pending": True,
            "abnormal": report["estimated_cost"] > 2000,
            "建议编号": f"QUER-{entry_id:04d}",
            "关联接口": api.get("接口编号", "") if api else "",
            "慢查询摘要": api.get("查询SQL", "")[:80] + "..." if api else "",
            "执行计划": json.dumps(report["execution_plan"], ensure_ascii=False),
            "索引建议": idx_suggest,
            "分区裁剪": partition_suggest,
            "预期提升": report["estimated_improvement"],
            "优化状态": "待分析",
        }
        rows.append(entry)
        return entry

    def _extract_where_fields(self, sql: str) -> list[str]:
        fields = []
        # 简单提取 WHERE field = 或 WHERE field BETWEEN
        m = re.search(r"WHERE\s+(.+?)(?:ORDER|GROUP|LIMIT|$)", sql, re.IGNORECASE | re.DOTALL)
        if m:
            clause = m.group(1)
            for fm in re.finditer(r"(\w+)\s*(?:=|>|<|BETWEEN|IN|LIKE)", clause, re.IGNORECASE):
                fields.append(fm.group(1))
        return list(dict.fromkeys(fields))

    def _extract_join_fields(self, sql: str) -> list[str]:
        fields = []
        for m in re.finditer(r"JOIN\s+\w+\s+ON\s+[^=]+=\s*(\w+)\.(\w+)", sql, re.IGNORECASE):
            fields.append(f"{m.group(1)}.{m.group(2)}")
        return list(dict.fromkeys(fields))

    def _extract_time_range_fields(self, sql: str) -> list[str]:
        fields = []
        for m in re.finditer(r"(\w+)\s*BETWEEN\s*['\d]", sql, re.IGNORECASE):
            fields.append(m.group(1))
        for m in re.finditer(r"(\w+)\s*[>=<]\s*['\d]{4}-", sql, re.IGNORECASE):
            fields.append(m.group(1))
        return list(dict.fromkeys(fields))


import json  # noqa: E402
