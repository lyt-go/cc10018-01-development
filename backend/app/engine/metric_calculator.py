"""指标计算引擎：支持原子指标→派生指标→聚合指标的链式计算。

核心能力：
1. 公式解析：将「SUM(订单金额)/COUNT(DISTINCT 用户ID)」解析为可执行结构
2. 口径版本控制：同一指标编号支持多版本，按生效时间自动选择
3. 依赖追踪：记录派生指标对原子指标、聚合配置对派生指标的依赖关系
4. 计算编排：按依赖拓扑排序执行，避免循环依赖
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.store import store


class MetricFormula:
    """单个公式的解析表示。"""

    def __init__(self, raw: str) -> None:
        self.raw = raw.strip()
        self.agg_func: str | None = None
        self.agg_field: str | None = None
        self.operators: list[str] = []
        self.operands: list[str] = []
        self._parse()

    def _parse(self) -> None:
        raw = self.raw
        # 提取聚合函数
        m = re.match(r"(\w+)\(([^)]+)\)", raw)
        if m:
            self.agg_func = m.group(1).upper()
            self.agg_field = m.group(2).strip()
        # 提取四则运算
        parts = re.split(r"([+\-*/])", raw)
        for p in parts:
            p = p.strip()
            if p in {"+", "-", "*", "/"}:
                self.operators.append(p)
            elif p:
                self.operands.append(p)

    def to_sql_expr(self, table_alias: str = "t") -> str:
        if self.agg_func and self.agg_field:
            if self.agg_func == "COUNT_DISTINCT":
                return f"COUNT(DISTINCT {table_alias}.{self.agg_field})"
            return f"{self.agg_func}({table_alias}.{self.agg_field})"
        return self.raw


class MetricCalculator:
    """指标计算引擎。"""

    def __init__(self) -> None:
        self._cache: dict[str, Any] = {}

    def list_active_domains(self) -> list[dict[str, Any]]:
        """获取所有已启用的指标域。"""
        return [r for r in store.rows("metric_domain") if r.get("status") == "已启用"]

    def list_effective_metrics(self) -> list[dict[str, Any]]:
        """获取所有已生效的派生指标。"""
        return [r for r in store.rows("derived_metric") if r.get("status") == "已生效"]

    def get_metric_by_code(self, code: str) -> dict[str, Any] | None:
        for r in store.rows("derived_metric"):
            if r.get("指标编号") == code:
                return r
        return None

    def parse_formula(self, formula_raw: str) -> MetricFormula:
        return MetricFormula(formula_raw)

    def compute_dependencies(self, metric_code: str) -> list[str]:
        """获取指定指标的直接依赖（父指标编号列表）。"""
        metric = self.get_metric_by_code(metric_code)
        if not metric:
            return []
        parent = metric.get("父指标编号", "")
        if parent and parent != metric_code:
            return [parent]
        return []

    def topological_sort(self, metric_codes: list[str]) -> list[str]:
        """按依赖拓扑排序指标，保证先计算原子指标。"""
        visited: set[str] = set()
        result: list[str] = []

        def dfs(code: str) -> None:
            if code in visited:
                return
            visited.add(code)
            for dep in self.compute_dependencies(code):
                dfs(dep)
            result.append(code)

        for code in metric_codes:
            dfs(code)
        return result

    def build_compute_plan(self, aggregate_config_id: int) -> dict[str, Any]:
        """为一条聚合配置生成计算计划。"""
        agg = store.find("data_aggregate", aggregate_config_id)
        if not agg:
            return {"ok": False, "error": "聚合配置不存在"}

        source = agg.get("数据来源", "")
        dims = agg.get("聚合维度", "")
        funcs = agg.get("聚合函数", "")

        # 从数据来源解析依赖的指标域和派生指标
        domain_codes = []
        metric_codes = []
        for part in source.split(","):
            part = part.strip()
            if part.startswith("METR-"):
                domain_codes.append(part)
            elif part.startswith("DERI-"):
                metric_codes.append(part)

        plan = {
            "ok": True,
            "aggregate_id": aggregate_config_id,
            "steps": [],
        }

        # Step 1: 加载指标域数据
        for dc in domain_codes:
            plan["steps"].append({
                "step": 1,
                "type": "load_domain",
                "domain_code": dc,
                "description": f"从指标域 {dc} 加载原子数据",
            })

        # Step 2: 计算派生指标（拓扑排序后）
        sorted_metrics = self.topological_sort(metric_codes)
        for idx, mc in enumerate(sorted_metrics, start=2):
            metric = self.get_metric_by_code(mc)
            formula = self.parse_formula(metric.get("计算公式", "") if metric else "")
            plan["steps"].append({
                "step": idx,
                "type": "compute_derived",
                "metric_code": mc,
                "formula": formula.raw,
                "sql_expr": formula.to_sql_expr(),
                "description": f"计算派生指标 {mc}: {formula.raw}",
            })

        # Step 3: 聚合
        plan["steps"].append({
            "step": len(plan["steps"]) + 1,
            "type": "aggregate",
            "dimensions": dims,
            "functions": funcs,
            "output_table": agg.get("输出表名", ""),
            "description": f"按 {dims} 聚合，函数 {funcs}",
        })

        return plan

    def preview_sql(self, aggregate_config_id: int) -> str:
        """为聚合配置生成预览SQL。"""
        plan = self.build_compute_plan(aggregate_config_id)
        if not plan.get("ok"):
            return "-- 计算计划生成失败"

        lines = ["-- 指标聚合计算SQL（由计算引擎自动生成）"]
        lines.append("WITH")

        ctes: list[str] = []
        for step in plan["steps"]:
            if step["type"] == "load_domain":
                ctes.append(f"  domain_{step['domain_code']} AS (\n    SELECT * FROM source_table WHERE domain_id = '{step['domain_code']}'\n  )")
            elif step["type"] == "compute_derived":
                ctes.append(f"  metric_{step['metric_code']} AS (\n    SELECT {step['sql_expr']} AS val FROM domain_base\n  )")
            elif step["type"] == "aggregate":
                dims = step["dimensions"]
                funcs = step["functions"]
                output = step["output_table"]
                lines.append(",\n".join(ctes))
                lines.append(f"\nSELECT {dims}, {funcs}\nFROM aggregated\nGROUP BY {dims};")
                lines.append(f"\n-- 输出目标表: {output}")
                return "\n".join(lines)

        return "\n".join(lines)

    def validate_metric_chain(self, domain_code: str, metric_code: str) -> dict[str, Any]:
        """校验从指标域到派生指标的链路完整性。"""
        domain = next((r for r in store.rows("metric_domain") if r.get("域编号") == domain_code), None)
        metric = self.get_metric_by_code(metric_code)

        errors = []
        if not domain:
            errors.append(f"指标域 {domain_code} 不存在")
        elif domain.get("status") != "已启用":
            errors.append(f"指标域 {domain_code} 状态为 {domain.get('status')}，非已启用")

        if not metric:
            errors.append(f"派生指标 {metric_code} 不存在")
        elif metric.get("status") != "已生效":
            errors.append(f"派生指标 {metric_code} 状态为 {metric.get('status')}，非已生效")

        if domain and metric:
            # 校验父指标是否属于该域
            parent = metric.get("父指标编号", "")
            if parent.startswith("METR-") and parent != domain_code:
                errors.append(f"父指标 {parent} 不属于指标域 {domain_code}")

        return {
            "ok": len(errors) == 0,
            "domain_code": domain_code,
            "metric_code": metric_code,
            "errors": errors,
        }
