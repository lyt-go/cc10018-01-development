"""批量导出分片引擎：将大数据导出任务拆分为并行子任务，支持分片策略解析与进度追踪。

分片策略语法：
- range:column:start:end:step  → 按数值范围分片
- hash:column:mod             → 按哈希取模分片
- time:column:unit            → 按时间单位分片（day/week/month）
- id:column:batch_size        → 按ID批次分片
"""
from __future__ import annotations

import re
from typing import Any

from app.store import store


class ShardPlan:
    """单个分片计划。"""

    def __init__(self, shard_id: int, strategy: str, condition: str, est_rows: int) -> None:
        self.shard_id = shard_id
        self.strategy = strategy
        self.condition = condition
        self.est_rows = est_rows
        self.status = "pending"
        self.result_path = ""


class ExportSharder:
    """批量导出分片引擎。"""

    def __init__(self) -> None:
        pass

    def parse_strategy(self, strategy_raw: str) -> dict[str, Any]:
        """解析分片策略字符串。"""
        parts = strategy_raw.split(":")
        if len(parts) < 2:
            return {"ok": False, "error": "分片策略格式错误，应为 type:param1:param2..."}

        stype = parts[0].lower()
        result = {"ok": True, "type": stype, "params": parts[1:]}

        if stype == "range":
            if len(parts) != 5:
                return {"ok": False, "error": "range分片需要5个参数: range:column:start:end:step"}
            result["column"] = parts[1]
            result["start"] = int(parts[2])
            result["end"] = int(parts[3])
            result["step"] = int(parts[4])
        elif stype == "hash":
            if len(parts) != 3:
                return {"ok": False, "error": "hash分片需要3个参数: hash:column:mod"}
            result["column"] = parts[1]
            result["mod"] = int(parts[2])
        elif stype == "time":
            if len(parts) != 3:
                return {"ok": False, "error": "time分片需要3个参数: time:column:unit"}
            result["column"] = parts[1]
            result["unit"] = parts[2]
        elif stype == "id":
            if len(parts) != 3:
                return {"ok": False, "error": "id分片需要3个参数: id:column:batch_size"}
            result["column"] = parts[1]
            result["batch_size"] = int(parts[2])
        else:
            return {"ok": False, "error": f"未知的分片类型: {stype}"}

        return result

    def generate_shards(self, export_task_id: int) -> dict[str, Any]:
        """为导出任务生成具体分片计划。"""
        task = store.find("batch_export", export_task_id)
        if not task:
            return {"ok": False, "error": f"导出任务 {export_task_id} 不存在"}

        strategy_raw = task.get("分片策略", "")
        parsed = self.parse_strategy(strategy_raw)
        if not parsed.get("ok"):
            return parsed

        shards: list[ShardPlan] = []
        stype = parsed["type"]

        if stype == "range":
            start, end, step = parsed["start"], parsed["end"], parsed["step"]
            column = parsed["column"]
            shard_id = 1
            for s in range(start, end, step):
                e = min(s + step - 1, end)
                condition = f"{column} BETWEEN {s} AND {e}"
                shards.append(ShardPlan(shard_id, stype, condition, step))
                shard_id += 1

        elif stype == "hash":
            column, mod = parsed["column"], parsed["mod"]
            for i in range(mod):
                condition = f"MOD({column}, {mod}) = {i}"
                shards.append(ShardPlan(i, stype, condition, 0))

        elif stype == "time":
            column, unit = parsed["column"], parsed["unit"]
            # 模拟生成最近12个时间单位的分片
            units = {"day": 1, "week": 7, "month": 30}
            days = units.get(unit, 1)
            from datetime import datetime, timedelta
            now = datetime.now()
            for i in range(12):
                d_start = now - timedelta(days=(i + 1) * days)
                d_end = now - timedelta(days=i * days)
                condition = f"{column} BETWEEN '{d_start.strftime('%Y-%m-%d')}' AND '{d_end.strftime('%Y-%m-%d')}'"
                shards.append(ShardPlan(i, stype, condition, 10000))

        elif stype == "id":
            column, batch = parsed["column"], parsed["batch_size"]
            # 模拟10个批次
            for i in range(10):
                s = i * batch
                e = (i + 1) * batch - 1
                condition = f"{column} BETWEEN {s} AND {e}"
                shards.append(ShardPlan(i, stype, condition, batch))

        # 保存分片计划到任务记录
        task["_shards"] = [
            {
                "shard_id": s.shard_id,
                "strategy": s.strategy,
                "condition": s.condition,
                "est_rows": s.est_rows,
                "status": s.status,
            }
            for s in shards
        ]

        return {
            "ok": True,
            "export_task_id": export_task_id,
            "shard_count": len(shards),
            "shards": task["_shards"],
        }

    def build_shard_sql(self, export_task_id: int, shard_id: int) -> dict[str, Any]:
        """为指定分片生成执行SQL。"""
        task = store.find("batch_export", export_task_id)
        if not task:
            return {"ok": False, "error": f"导出任务 {export_task_id} 不存在"}

        shards = task.get("_shards", [])
        shard = next((s for s in shards if s["shard_id"] == shard_id), None)
        if not shard:
            return {"ok": False, "error": f"分片 {shard_id} 不存在"}

        base_sql = task.get("查询SQL", "SELECT * FROM data")
        condition = shard["condition"]

        # 将分片条件注入SQL
        if "WHERE" in base_sql.upper():
            sql = re.sub(
                r"WHERE\s+", f"WHERE {condition} AND ", base_sql, count=1, flags=re.IGNORECASE)
        else:
            sql = f"{base_sql} WHERE {condition}"

        return {
            "ok": True,
            "export_task_id": export_task_id,
            "shard_id": shard_id,
            "sql": sql,
            "est_rows": shard["est_rows"],
        }

    def estimate_total_rows(self, export_task_id: int) -> int:
        """估算导出任务总行数。"""
        result = self.generate_shards(export_task_id)
        if not result.get("ok"):
            return 0
        return sum(s["est_rows"] for s in result.get("shards", []))

    def validate_export_chain(self, export_task_id: int) -> dict[str, Any]:
        """校验批量导出链的完整性（任务→清洗→缓存→审计）。"""
        task = store.find("batch_export", export_task_id)
        errors = []

        if not task:
            errors.append(f"导出任务 {export_task_id} 不存在")
            return {"ok": False, "errors": errors}

        # 检查是否有配套的清洗配置
        cleanse = next((r for r in store.rows("data_cleanse") if r.get("数据来源") == task.get("任务编号")), None)
        if not cleanse:
            errors.append("未找到关联的数据清洗配置")

        # 检查是否有配套的缓存配置
        cache = next((r for r in store.rows("result_cache") if task.get("任务编号") in str(r.get("缓存键", ""))), None)
        if not cache:
            errors.append("未找到关联的结果缓存配置")

        # 检查是否有审计记录
        audit = next((r for r in store.rows("query_audit") if task.get("任务编号") in str(r.get("请求参数", ""))), None)
        if not audit:
            errors.append("未找到关联的查询审计记录")

        return {
            "ok": len(errors) == 0,
            "export_task_id": export_task_id,
            "errors": errors,
            "cleanse_config": cleanse.get("配置编号") if cleanse else None,
            "cache_config": cache.get("配置编号") if cache else None,
            "audit_log": audit.get("日志编号") if audit else None,
        }
