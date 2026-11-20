"""域源映射校验包测试：登记/启用校验、证据作废、同库名连接冲突与取数范围核对。

覆盖的验收点：
1. 登记和启用指标域时校验数据源表与连接配置，证据记录连接编号及校验状态。
2. 同库名的另一条连接不能替代证据；连接断开后旧证据不能再授权新的取数。
3. 指标计算链生成聚合计划时校验实际取数连接，证据失效说明受影响的数据源归属和输出表。
4. 冲突场景（校验通过后断开连接、又加同库名连接）：分别用重新校验和直接执行
   旧计划核对取数范围；未换连接的另一域仍可正常生成计划。
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.store import store
from app.engine.domain_source_validator import DomainSourceValidator
from app.engine.metric_calculator import MetricCalculator
from app.engine.chain_orchestrator import ChainOrchestrator
from app.services.metric_domain import MetricDomainService
from app.services.datasource_connect import DatasourceConnectService


def reset_store():
    """重新加载seed数据。"""
    from app.seed import SEED_ROWS
    store._tables = {name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()}


def _find(module: str, field: str, value: str) -> dict:
    row = next((r for r in store.rows(module) if r.get(field) == value), None)
    assert row is not None, f"{module} 中找不到 {field}={value}"
    return row


def test_register_records_evidence():
    """登记指标域时校验数据源表与连接配置，证据记录连接编号与校验状态。"""
    reset_store()
    svc = MetricDomainService()
    validator = DomainSourceValidator()

    # 数据源表有已连接连接（DS-USER / dwd_user_active_di）→ 证据有效并记录连接编号
    entry, missing = svc.create_entry({
        "域编号": "METR-REG1", "域名称": "登记校验域", "业务域描述": "登记时触发域源校验",
        "数据源表": "dwd_user_active_di",
    })
    assert not missing
    evidence = validator.current_evidence("METR-REG1")
    assert evidence is not None, "登记后应生成校验证据"
    assert evidence["校验状态"] == "有效"
    assert evidence["连接编号"] == "DS-USER", "证据必须记录数据源归属的连接编号"
    assert evidence["校验来源"] == "登记校验"

    # 数据源表没有任何连接 → 证据为无可用连接，连接编号留空
    entry2, missing2 = svc.create_entry({
        "域编号": "METR-REG2", "域名称": "无连接域", "业务域描述": "数据源表无连接配置",
        "数据源表": "dwd_nowhere_di",
    })
    assert not missing2
    evidence2 = validator.current_evidence("METR-REG2")
    assert evidence2["校验状态"] == "无可用连接"
    assert evidence2["连接编号"] == ""
    print("  [PASS] 登记校验：证据记录连接编号与校验状态")


def test_enable_requires_valid_connection():
    """启用指标域时重新校验，无有效取数连接的域不允许启用。"""
    reset_store()
    svc = MetricDomainService()
    ds_svc = DatasourceConnectService()
    validator = DomainSourceValidator()

    # METR-LOGIS（待校验）的数据源表 dwd_logis_delivery_di 没有任何连接 → 开启被拦截
    logis = _find("metric_domain", "域编号", "METR-LOGIS")
    entry, message = svc.run_action(logis["id"], "开启域")
    assert entry is None, f"无连接时不应允许开启域: {message}"
    assert "拦截" in message
    assert logis["status"] == "待校验"

    # 运维补上连接并标记连接后，开启成功且证据绑定该连接编号
    conn, missing = ds_svc.create_entry({
        "连接编号": "DS-LOGIS", "数据源类型": "MySQL",
        "连接地址": "mysql://10.0.1.50:3306", "数据库名": "dwd_logis_delivery_di",
    })
    assert not missing
    ds_svc.run_action(conn["id"], "标记连接")
    entry, message = svc.run_action(logis["id"], "开启域")
    assert entry is not None and entry["status"] == "已启用", message
    evidence = validator.current_evidence("METR-LOGIS")
    assert evidence["校验状态"] == "有效"
    assert evidence["连接编号"] == "DS-LOGIS"
    assert evidence["校验来源"] == "启用校验"
    print("  [PASS] 启用校验：无连接拦截，补连接后证据绑定新连接")


def test_disconnect_revokes_and_same_name_conn_cannot_substitute():
    """连接断开作废旧证据；同库名的另一条连接不能替代这条证据。"""
    reset_store()
    ds_svc = DatasourceConnectService()
    validator = DomainSourceValidator()
    calc = MetricCalculator()

    # 初始：METR-TRADE 证据有效，绑定 DS-TRADE
    auth = validator.check_fetch_authorization("METR-TRADE")
    assert auth["ok"] and auth["连接编号"] == "DS-TRADE"

    # 运维断开 DS-TRADE → 旧证据作废
    trade = _find("datasource_connect", "连接编号", "DS-TRADE")
    _, message = ds_svc.run_action(trade["id"], "标记断开")
    assert "作废" in message
    evidence = validator.current_evidence("METR-TRADE")
    assert evidence["校验状态"] == "已失效"
    assert evidence["失效原因"] == "连接断开"

    # 运维添加同库名的新连接 DS-TRADE-2 并标记连接
    conn, _ = ds_svc.create_entry({
        "连接编号": "DS-TRADE-2", "数据源类型": "ClickHouse",
        "连接地址": "clickhouse://10.0.1.11:9000", "数据库名": "dwd_trade_order_di",
    })
    ds_svc.run_action(conn["id"], "标记连接")

    # 同库名新连接不能替代旧证据：取数授权仍然失败
    auth2 = validator.check_fetch_authorization("METR-TRADE")
    assert not auth2["ok"], "同库名的另一条连接不能替代旧证据授权取数"

    # 聚合计划生成被拒，说明受影响的数据源归属和输出表
    plan = calc.build_compute_plan(1)
    assert not plan["ok"]
    assert plan["output_table"] == "ads_trade_gmv_daily"
    affected = plan["affected_sources"][0]
    assert affected["域编号"] == "METR-TRADE"
    assert affected["数据源表"] == "dwd_trade_order_di"
    assert affected["证据连接编号"] == "DS-TRADE"
    print("  [PASS] 断开作废：同库名连接不能替代旧证据")


def test_conflict_revalidate_vs_stale_plan():
    """冲突场景：校验通过后断开连接又加同库名连接，旧校验不能支持下一笔计算。

    分别用「重新校验」和「直接执行旧计划」核对取数范围，
    并确认未换连接的另一域（METR-USER）仍可正常生成计划。
    """
    reset_store()
    ds_svc = DatasourceConnectService()
    validator = DomainSourceValidator()
    calc = MetricCalculator()

    # 1) 校验通过，生成旧计划 P1（取数连接 DS-TRADE）
    v1 = validator.validate_domain("METR-TRADE", reason="重新校验")
    assert v1["ok"] and v1["evidence"]["连接编号"] == "DS-TRADE"
    plan_v1 = calc.build_compute_plan(1)
    assert plan_v1["ok"]
    load_v1 = next(s for s in plan_v1["steps"] if s["type"] == "load_domain")
    assert load_v1["connection_code"] == "DS-TRADE"

    # 2) 同一次聚合取数准备中发生冲突：运维断开 DS-TRADE，又加同库名连接 DS-TRADE-2
    trade = _find("datasource_connect", "连接编号", "DS-TRADE")
    ds_svc.run_action(trade["id"], "标记断开")
    conn, _ = ds_svc.create_entry({
        "连接编号": "DS-TRADE-2", "数据源类型": "ClickHouse",
        "连接地址": "clickhouse://10.0.1.11:9000", "数据库名": "dwd_trade_order_di",
    })
    ds_svc.run_action(conn["id"], "标记连接")

    # 3a) 直接执行旧计划：核对取数范围，旧校验不能支持下一笔计算
    stale = calc.execute_compute_plan(plan_v1)
    assert not stale["ok"], "旧计划的取数授权已失效，必须拒绝执行"
    assert stale["output_table"] == "ads_trade_gmv_daily"
    refused = stale["refused"][0]
    assert refused["域编号"] == "METR-TRADE"
    assert refused["计划取数连接"] == "DS-TRADE"

    # 3b) 重新校验：证据改绑 DS-TRADE-2，新计划取数范围切到新连接
    v2 = validator.validate_domain("METR-TRADE", reason="重新校验")
    assert v2["ok"] and v2["evidence"]["连接编号"] == "DS-TRADE-2"
    plan_v2 = calc.build_compute_plan(1)
    assert plan_v2["ok"]
    load_v2 = next(s for s in plan_v2["steps"] if s["type"] == "load_domain")
    assert load_v2["connection_code"] == "DS-TRADE-2"
    run = calc.execute_compute_plan(plan_v2)
    assert run["ok"]
    assert run["fetch_range"][0]["连接编号"] == "DS-TRADE-2"
    assert run["fetch_range"][0]["数据源表"] == "dwd_trade_order_di"

    # 3c) 重新校验后再执行旧计划 P1：计划取数连接与当前授权不一致，仍不能沿用
    stale2 = calc.execute_compute_plan(plan_v1)
    assert not stale2["ok"]
    assert stale2["refused"][0]["当前授权连接"] == "DS-TRADE-2"

    # 4) 未换连接的另一域（METR-USER / DS-USER）不受影响，仍可正常生成计划
    plan_user = calc.build_compute_plan(2)
    assert plan_user["ok"], f"未换连接的域应正常生成计划: {plan_user}"
    load_user = next(s for s in plan_user["steps"] if s["type"] == "load_domain")
    assert load_user["connection_code"] == "DS-USER"
    run_user = calc.execute_compute_plan(plan_user)
    assert run_user["ok"] and run_user["fetch_range"][0]["连接编号"] == "DS-USER"
    print("  [PASS] 冲突场景：重新校验改绑新连接，旧计划取数范围核对失效，另一域正常")


def test_metric_compute_chain_reports_affected_on_stale_evidence():
    """指标计算链生成聚合计划时校验实际取数连接，证据失效说明数据源归属和输出表。"""
    reset_store()
    orch = ChainOrchestrator()
    ds_svc = DatasourceConnectService()

    # 证据有效时链路正常
    ok_result = orch.run_metric_compute_chain("METR-TRADE", "DERI-GMV", 1)
    assert ok_result["ok"]
    assert "DS-TRADE" in ok_result["steps"][0]["detail"]

    # 断开 DS-TRADE 并加同库名连接后，链路在第 1 步拦截并说明影响面
    trade = _find("datasource_connect", "连接编号", "DS-TRADE")
    ds_svc.run_action(trade["id"], "标记断开")
    conn, _ = ds_svc.create_entry({
        "连接编号": "DS-TRADE-2", "数据源类型": "ClickHouse",
        "连接地址": "clickhouse://10.0.1.11:9000", "数据库名": "dwd_trade_order_di",
    })
    ds_svc.run_action(conn["id"], "标记连接")

    result = orch.run_metric_compute_chain("METR-TRADE", "DERI-GMV", 1)
    assert not result["ok"]
    assert result["steps"][0]["status"] == "error"
    affected = result["affected"]
    assert affected["数据源归属"][0]["域编号"] == "METR-TRADE"
    assert affected["数据源归属"][0]["证据连接编号"] == "DS-TRADE"
    assert affected["输出表"] == ["ads_trade_gmv_daily"]

    # 未换连接的 METR-USER 链路不受影响
    user_result = orch.run_metric_compute_chain("METR-USER", "DERI-DAU", 2)
    assert user_result["ok"], f"未换连接的域链路应正常: {user_result}"
    print("  [PASS] 指标计算链：证据失效说明受影响数据源归属与输出表")


def test_http_endpoints():
    """通过TestClient测试域源校验相关HTTP端点。"""
    reset_store()
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)

    # 证据列表
    r = client.get("/api/domain_source_validation")
    assert r.status_code == 200
    assert r.json()["total"] >= 4

    # 按校验状态过滤
    r = client.get("/api/domain_source_validation", params={"status": "有效"})
    assert r.status_code == 200
    assert all(item["校验状态"] == "有效" for item in r.json()["items"])

    # 取数授权检查
    r = client.get("/api/domain_source_validation/METR-TRADE/check")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["连接编号"] == "DS-TRADE"

    # 断开连接后授权失败，重新校验后恢复（绑定新连接）
    trade = _find("datasource_connect", "连接编号", "DS-TRADE")
    r = client.post(f"/api/datasource_connect/{trade['id']}/actions", json={"action": "标记断开"})
    assert r.status_code == 200 and r.json()["ok"] is True
    r = client.get("/api/domain_source_validation/METR-TRADE/check")
    assert r.json()["ok"] is False

    r = client.post("/api/datasource_connect", json={
        "连接编号": "DS-TRADE-2", "数据源类型": "ClickHouse",
        "连接地址": "clickhouse://10.0.1.11:9000", "数据库名": "dwd_trade_order_di",
    })
    assert r.status_code == 200 and r.json()["ok"] is True
    new_conn = _find("datasource_connect", "连接编号", "DS-TRADE-2")
    client.post(f"/api/datasource_connect/{new_conn['id']}/actions", json={"action": "标记连接"})

    # 旧证据仍不授权（同库名新连接不能替代）
    r = client.get("/api/domain_source_validation/METR-TRADE/check")
    assert r.json()["ok"] is False

    # 重新校验后授权恢复，证据绑定新连接编号
    r = client.post("/api/domain_source_validation/METR-TRADE/revalidate")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert r.json()["entry"]["连接编号"] == "DS-TRADE-2"
    r = client.get("/api/domain_source_validation/METR-TRADE/check")
    assert r.json()["ok"] is True and r.json()["连接编号"] == "DS-TRADE-2"

    # 计算计划与执行计划端点
    r = client.get("/api/chain/engine/compute-plan", params={"aggregate_id": 1})
    assert r.status_code == 200 and r.json()["ok"] is True
    plan = r.json()
    r = client.post("/api/chain/engine/execute-plan", json={"plan": plan})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert r.json()["fetch_range"][0]["连接编号"] == "DS-TRADE-2"

    # 未换连接的 METR-USER 计划正常
    r = client.get("/api/chain/engine/compute-plan", params={"aggregate_id": 2})
    assert r.status_code == 200 and r.json()["ok"] is True
    print("  [PASS] HTTP端点：证据查询、授权检查、重新校验、计划执行")


def run_all():
    print("\n=== 开始域源映射校验包测试 ===")
    tests = [
        test_register_records_evidence,
        test_enable_requires_valid_connection,
        test_disconnect_revokes_and_same_name_conn_cannot_substitute,
        test_conflict_revalidate_vs_stale_plan,
        test_metric_compute_chain_reports_affected_on_stale_evidence,
        test_http_endpoints,
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
    reset_store()
    print(f"\n=== 测试结果: {passed} 通过, {failed} 失败, 共 {len(tests)} 项 ===")
    return failed == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
