"""关键链路整体测试：验证10组跨模块数据链的端到端正确性。"""
from __future__ import annotations

import sys
import os

# 确保 backend 目录在路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.store import store
from app.engine.chain_orchestrator import ChainOrchestrator
from app.engine.metric_calculator import MetricCalculator
from app.engine.sql_binder import SqlTemplateBinder
from app.engine.query_optimizer import QueryOptimizer
from app.engine.export_sharder import ExportSharder


def reset_store():
    """重新加载seed数据。"""
    store._tables = {}
    from app.seed import SEED_ROWS
    store._tables = {name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()}


def test_metric_compute_chain():
    """链路1: 指标计算链（数据源连接→指标域→派生指标→数据聚合）。"""
    orch = ChainOrchestrator()
    result = orch.run_metric_compute_chain("METR-TRADE", "DERI-GMV", 1)
    assert result["ok"], f"指标计算链失败: {result}"
    assert len(result["steps"]) == 4
    assert result["steps"][0]["module"] == "datasource_connect"
    assert result["steps"][1]["module"] == "metric_domain"
    assert result["steps"][2]["module"] == "derived_metric"
    assert result["steps"][3]["module"] == "data_aggregate"
    assert "compute_plan" in result
    print("  [PASS] 链路1: 指标计算链")


def test_query_service_chain():
    """链路2: 查询服务链（API服务→SQL模板→查询优化→数据预览）。"""
    orch = ChainOrchestrator()
    result = orch.run_query_service_chain(1, 1, {"start_date": "2026-11-01", "end_date": "2026-11-15", "shop_list": ["101", "102"]})
    assert result["ok"], f"查询服务链失败: {result}"
    assert len(result["steps"]) == 4
    assert result["steps"][0]["module"] == "api_service"
    assert result["steps"][1]["module"] == "sql_template"
    assert result["steps"][2]["module"] == "query_optimize"
    assert "bound_sql" in result
    assert "$" in result["bound_sql"]  # 参数已绑定为占位符
    print("  [PASS] 链路2: 查询服务链")


def test_consume_governance_chain():
    """链路3: 消费治理链（接口订阅→调用凭证→调用追踪→访问看板）。"""
    orch = ChainOrchestrator()
    result = orch.run_consume_governance_chain(1)
    assert result["ok"], f"消费治理链失败: {result}"
    assert len(result["steps"]) == 4
    assert result["steps"][0]["module"] == "api_subscribe"
    assert result["steps"][1]["module"] == "call_credential"
    assert result["steps"][2]["module"] == "call_trace"
    assert result["steps"][3]["module"] == "access_dashboard"
    print("  [PASS] 链路3: 消费治理链")


def test_data_output_chain():
    """链路4: 数据输出链（批量导出→数据清洗→结果缓存→查询审计）。"""
    orch = ChainOrchestrator()
    result = orch.run_data_output_chain(1)
    assert result["ok"], f"数据输出链失败: {result}"
    assert len(result["steps"]) == 4
    assert result["steps"][0]["module"] == "batch_export"
    assert result["steps"][1]["module"] == "data_cleanse"
    assert result["steps"][2]["module"] == "result_cache"
    assert result["steps"][3]["module"] == "query_audit"
    assert "shard_plan" in result
    print("  [PASS] 链路4: 数据输出链")


def test_caliber_unify_chain():
    """链路5: 口径统一链（指标重名解析→口径注册）。"""
    orch = ChainOrchestrator()
    result = orch.run_caliber_unify_chain(1)
    assert result["ok"], f"口径统一链失败: {result}"
    assert len(result["steps"]) >= 2
    assert result["steps"][0]["module"] == "metric_homonym"
    assert result["steps"][1]["module"] == "metric_domain"
    print("  [PASS] 链路5: 口径统一链")


def test_version_manage_chain():
    """链路6: 版本管理链（接口版本→灰度发布）。"""
    orch = ChainOrchestrator()
    result = orch.run_version_manage_chain(1)
    assert result["ok"], f"版本管理链失败: {result}"
    assert len(result["steps"]) == 2
    assert result["steps"][0]["module"] == "api_version"
    assert result["steps"][1]["module"] == "api_service"
    print("  [PASS] 链路6: 版本管理链")


def test_api_lifecycle_chain():
    """链路7: API生命周期链。"""
    orch = ChainOrchestrator()
    result = orch.run_api_lifecycle_chain("API-TRADE-001")
    assert result["ok"], f"API生命周期链失败: {result}"
    assert len(result["steps"]) == 6
    modules = [s["module"] for s in result["steps"]]
    assert "api_service" in modules
    assert "api_subscribe" in modules
    assert "call_credential" in modules
    assert "call_trace" in modules
    assert "query_audit" in modules
    assert "access_dashboard" in modules
    print("  [PASS] 链路7: API生命周期链")


def test_cache_warmup_chain():
    """链路8: 缓存预热链。"""
    orch = ChainOrchestrator()
    result = orch.run_cache_warmup_chain(1)
    assert result["ok"], f"缓存预热链失败: {result}"
    assert len(result["steps"]) == 4
    modules = [s["module"] for s in result["steps"]]
    assert "api_service" in modules
    assert "sql_template" in modules
    assert "result_cache" in modules
    assert "data_preview" in modules
    print("  [PASS] 链路8: 缓存预热链")


def test_audit_trail_chain():
    """链路9: 审计追踪链。"""
    orch = ChainOrchestrator()
    result = orch.run_audit_trail_chain(1)
    assert result["ok"], f"审计追踪链失败: {result}"
    assert len(result["steps"]) == 2
    assert result["steps"][0]["module"] == "call_trace"
    assert result["steps"][1]["module"] == "query_audit"
    assert "audit_conclusion" in result
    print("  [PASS] 链路9: 审计追踪链")


def test_template_reuse_chain():
    """链路10: 模板复用链。"""
    orch = ChainOrchestrator()
    result = orch.run_template_reuse_chain(1)
    assert result["ok"], f"模板复用链失败: {result}"
    assert len(result["steps"]) >= 3
    modules = [s["module"] for s in result["steps"]]
    assert "sql_template" in modules
    assert "api_service" in modules
    assert "query_optimize" in modules
    assert "api_version" in modules
    print("  [PASS] 链路10: 模板复用链")


def test_metric_calculator():
    """测试指标计算引擎核心功能。"""
    calc = MetricCalculator()

    # 测试公式解析
    formula = calc.parse_formula("SUM(订单金额)/COUNT(DISTINCT 用户ID)")
    assert formula.agg_func == "SUM"
    assert formula.agg_field == "订单金额"
    assert "/" in formula.operators

    # 测试依赖计算
    deps = calc.compute_dependencies("DERI-ARPU")
    assert "DERI-GMV" in deps

    # 测试拓扑排序
    sorted_codes = calc.topological_sort(["DERI-ARPU", "DERI-GMV"])
    assert sorted_codes.index("DERI-GMV") < sorted_codes.index("DERI-ARPU")

    # 测试计算计划
    plan = calc.build_compute_plan(1)
    assert plan["ok"]
    assert len(plan["steps"]) >= 3

    # 测试校验
    validation = calc.validate_metric_chain("METR-TRADE", "DERI-GMV")
    assert validation["ok"]

    print("  [PASS] 指标计算引擎")


def test_sql_binder():
    """测试SQL模板参数绑定引擎。"""
    binder = SqlTemplateBinder()

    # 测试参数解析
    sql = "SELECT * FROM t WHERE dt BETWEEN {{start_date:date}} AND {{end_date:date}} AND id IN {{shop_list:list}}"
    params = binder.parse_params(sql)
    assert len(params) == 3
    assert any(p["name"] == "shop_list" and p["type"] == "list" for p in params)

    # 测试参数绑定
    result = binder.bind(sql, {"start_date": "2026-11-01", "end_date": "2026-11-15", "shop_list": ["101", "102"]})
    assert result["ok"]
    assert "$1" in result["sql"]
    assert len(result["params"]) == 4  # 2 dates + 2 list items

    # 测试优化建议
    suggestions = binder.suggest_optimization("SELECT * FROM t WHERE name LIKE '%test%'")
    assert any(s["type"] == "column_prune" for s in suggestions)
    assert any(s["type"] == "index_unfriendly" for s in suggestions)

    print("  [PASS] SQL模板绑定引擎")


def test_query_optimizer():
    """测试查询优化引擎。"""
    optimizer = QueryOptimizer()

    report = optimizer.analyze_sql("SELECT * FROM orders WHERE dt = '2026-11-15' ORDER BY amount")
    assert report["ok"]
    assert report["estimated_cost"] > 0
    assert len(report["index_suggestions"]) > 0
    assert "estimated_improvement" in report

    print("  [PASS] 查询优化引擎")


def test_export_sharder():
    """测试批量导出分片引擎。"""
    sharder = ExportSharder()

    # 测试策略解析
    parsed = sharder.parse_strategy("range:user_id:0:1000000:100000")
    assert parsed["ok"]
    assert parsed["type"] == "range"

    # 测试分片生成
    result = sharder.generate_shards(1)
    assert result["ok"]
    assert result["shard_count"] > 0

    # 测试分片SQL
    sql_result = sharder.build_shard_sql(1, 0)
    assert sql_result["ok"]
    assert "WHERE" in sql_result["sql"]

    # 测试链路校验
    chain_result = sharder.validate_export_chain(1)
    assert chain_result["ok"] or len(chain_result["errors"]) > 0

    print("  [PASS] 批量导出分片引擎")


def test_api_endpoints():
    """通过TestClient测试HTTP端点。"""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)

    # 健康检查
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # 概览
    r = client.get("/api/overview")
    assert r.status_code == 200

    # 指标域列表
    r = client.get("/api/metric_domain")
    assert r.status_code == 200
    assert r.json()["total"] >= 4

    # 数据聚合详情（含计算计划）
    r = client.get("/api/data_aggregate/1")
    assert r.status_code == 200
    assert "_compute_plan" in r.json()

    # 计算计划接口
    r = client.get("/api/data_aggregate/1/compute-plan")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # 预览SQL接口
    r = client.get("/api/data_aggregate/1/preview-sql")
    assert r.status_code == 200
    assert "sql" in r.json()

    # 批量导出分片
    r = client.get("/api/batch_export/1/shard-plan")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # 引擎级计算计划
    r = client.get("/api/chain/engine/compute-plan?aggregate_id=1")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # 引擎级SQL绑定
    r = client.post("/api/chain/engine/bind-sql", json={
        "sql": "SELECT * FROM t WHERE dt BETWEEN {{start_date:date}} AND {{end_date:date}}",
        "values": {"start_date": "2026-11-01", "end_date": "2026-11-15"}
    })
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # 引擎级SQL优化
    r = client.post("/api/chain/engine/optimize-sql", json={
        "sql": "SELECT * FROM orders WHERE dt = '2026-11-15' ORDER BY amount",
        "api_id": 1
    })
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # 链路测试：指标计算链
    r = client.get("/api/chain/metric-compute?domain_code=METR-TRADE&metric_code=DERI-GMV&aggregate_id=1")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # 链路测试：查询服务链
    r = client.post("/api/chain/query-service", json={
        "api_id": 1, "template_id": 1,
        "params": {"start_date": "2026-11-01", "end_date": "2026-11-15", "shop_list": ["101", "102"]}
    })
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # 链路测试：消费治理链
    r = client.get("/api/chain/consume-governance?subscribe_id=1")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # 链路测试：数据输出链
    r = client.get("/api/chain/data-output?export_id=1")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # 链路测试：口径统一链
    r = client.get("/api/chain/caliber-unify?homonym_id=1")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # 链路测试：版本管理链
    r = client.get("/api/chain/version-manage?version_id=1")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # 链路测试：API生命周期链
    r = client.get("/api/chain/api-lifecycle?api_code=API-TRADE-001")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    print("  [PASS] HTTP API端点")


def run_all():
    reset_store()
    print("\n=== 开始关键链路整体测试 ===")

    tests = [
        test_metric_compute_chain,
        test_query_service_chain,
        test_consume_governance_chain,
        test_data_output_chain,
        test_caliber_unify_chain,
        test_version_manage_chain,
        test_api_lifecycle_chain,
        test_cache_warmup_chain,
        test_audit_trail_chain,
        test_template_reuse_chain,
        test_metric_calculator,
        test_sql_binder,
        test_query_optimizer,
        test_export_sharder,
        test_api_endpoints,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {t.__name__}: {e}")
            failed += 1

    print(f"\n=== 测试结果: {passed} 通过, {failed} 失败, 共 {len(tests)} 项 ===")
    return failed == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
