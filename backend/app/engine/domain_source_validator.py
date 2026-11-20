"""域源映射校验包：给计算端提供「指标域→数据源表→取数连接」的校验与授权证据。

核心规则：
1. 登记与启用指标域时校验数据源表与连接配置，校验结果落成证据记录，
   证据必须写明数据源归属的连接编号与校验状态。
2. 证据绑定具体连接编号：同库名的另一条连接不能替代这条证据。
3. 连接断开后旧证据立即作废，不能再授权新的取数；必须重新校验生成新证据。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "domain_source_validation"

EVIDENCE_VALID = "有效"
EVIDENCE_NO_CONNECTION = "无可用连接"
EVIDENCE_INVALID = "已失效"
EVIDENCE_FAILED = "校验失败"


class DomainSourceValidator:
    """域源映射校验包：登记/启用校验、取数授权检查、连接断开作废。"""

    # ───────────────────────────────────────────────
    # 证据记录
    # ───────────────────────────────────────────────
    def list_records(self, domain_code: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows(MODULE)
        if domain_code:
            rows = [row for row in rows if row.get("域编号") == domain_code]
        return rows

    def current_evidence(self, domain_code: str) -> dict[str, Any] | None:
        """某指标域最新的一条校验证据。"""
        records = self.list_records(domain_code)
        return records[-1] if records else None

    def _record(
        self,
        domain_code: str,
        ds_table: str,
        conn_code: str,
        status: str,
        invalid_reason: str,
        source: str,
    ) -> dict[str, Any]:
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry["校验编号"] = f"DSV-{entry['id']:04d}"
        entry["域编号"] = domain_code
        entry["数据源表"] = ds_table
        entry["连接编号"] = conn_code
        entry["校验状态"] = status
        entry["失效原因"] = invalid_reason
        entry["校验时间"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry["校验来源"] = source
        entry["status"] = status
        entry["pending"] = status == EVIDENCE_NO_CONNECTION
        entry["abnormal"] = status in (EVIDENCE_INVALID, EVIDENCE_FAILED)
        rows.append(entry)
        return entry

    # ───────────────────────────────────────────────
    # 登记/启用/重新校验：生成新证据
    # ───────────────────────────────────────────────
    def validate_domain(self, domain_code: str, *, reason: str = "重新校验") -> dict[str, Any]:
        """校验指标域的数据源表与连接配置，并把结果落成证据。

        证据记录数据源归属的连接编号与校验状态；找不到已连接的连接配置时，
        证据状态为「无可用连接」，连接编号留空。
        """
        domain = next((r for r in store.rows("metric_domain") if r.get("域编号") == domain_code), None)
        if not domain:
            evidence = self._record(domain_code, "", "", EVIDENCE_FAILED, "指标域不存在", reason)
            return {"ok": False, "evidence": evidence,
                    "message": f"指标域 {domain_code} 不存在，无法校验域源映射"}

        ds_table = str(domain.get("数据源表") or "").strip()
        if not ds_table:
            evidence = self._record(domain_code, "", "", EVIDENCE_FAILED, "数据源表未填写", reason)
            return {"ok": False, "evidence": evidence,
                    "message": f"指标域 {domain_code} 未填写数据源表，无法校验域源映射"}

        candidates = [
            row for row in store.rows("datasource_connect")
            if row.get("数据库名") == ds_table and row.get("status") == "已连接"
        ]
        conn: dict[str, Any] | None = None
        if candidates:
            # 优先沿用当前有效证据绑定的连接，避免在同一库名的多条连接间无谓漂移
            prev = self.current_evidence(domain_code)
            prev_conn = (prev or {}).get("连接编号", "")
            conn = next((c for c in candidates if c.get("连接编号") == prev_conn), None) or candidates[0]

        if conn is None:
            evidence = self._record(
                domain_code, ds_table, "", EVIDENCE_NO_CONNECTION,
                f"数据源表 {ds_table} 没有已连接的连接配置", reason)
            return {"ok": False, "evidence": evidence,
                    "message": f"数据源表 {ds_table} 没有已连接的连接配置，校验未通过"}

        evidence = self._record(domain_code, ds_table, str(conn.get("连接编号", "")), EVIDENCE_VALID, "", reason)
        return {"ok": True, "evidence": evidence,
                "message": f"数据源表 {ds_table} 校验通过，归属连接 {conn.get('连接编号')}"}

    # ───────────────────────────────────────────────
    # 计算端取数授权检查
    # ───────────────────────────────────────────────
    def check_fetch_authorization(self, domain_code: str) -> dict[str, Any]:
        """检查指标域当前是否被授权取数，并给出实际取数连接。

        只认证据绑定的连接编号：同库名的另一条连接不能替代这条证据；
        绑定连接断开后旧证据不能授权新的取数。
        """
        domain = next((r for r in store.rows("metric_domain") if r.get("域编号") == domain_code), None)
        if not domain:
            return {"ok": False, "evidence": None, "reason": f"指标域 {domain_code} 不存在"}
        ds_table = str(domain.get("数据源表") or "")

        evidence = self.current_evidence(domain_code)
        if evidence is None:
            return {"ok": False, "evidence": None,
                    "reason": f"指标域 {domain_code} 缺少域源映射校验证据，请先完成登记或启用校验"}

        status = evidence.get("校验状态", "")
        if status != EVIDENCE_VALID:
            reason = evidence.get("失效原因") or f"校验状态为 {status}"
            return {"ok": False, "evidence": evidence,
                    "reason": f"证据 {evidence.get('校验编号')} 未授权：{reason}"}

        conn_code = str(evidence.get("连接编号") or "")
        conn = next((r for r in store.rows("datasource_connect") if r.get("连接编号") == conn_code), None)
        if conn is None:
            return {"ok": False, "evidence": evidence,
                    "reason": f"证据 {evidence.get('校验编号')} 绑定的连接 {conn_code} 已不存在"}
        if conn.get("status") != "已连接":
            return {"ok": False, "evidence": evidence,
                    "reason": f"证据 {evidence.get('校验编号')} 绑定的连接 {conn_code} 已断开，旧证据不能授权新的取数"}
        if conn.get("数据库名") != ds_table:
            return {"ok": False, "evidence": evidence,
                    "reason": f"连接 {conn_code} 的数据库名与指标域数据源表 {ds_table} 不一致"}

        return {
            "ok": True,
            "evidence": evidence,
            "连接编号": conn_code,
            "连接地址": conn.get("连接地址", ""),
            "数据源类型": conn.get("数据源类型", ""),
            "数据源表": ds_table,
        }

    # ───────────────────────────────────────────────
    # 连接断开：作废绑定该连接的有效证据
    # ───────────────────────────────────────────────
    def invalidate_for_connection(self, conn_code: str, *, reason: str = "连接断开") -> int:
        """连接断开后，把绑定该连接编号的有效证据全部作废，返回作废条数。"""
        count = 0
        for row in store.rows(MODULE):
            if row.get("连接编号") == conn_code and row.get("校验状态") == EVIDENCE_VALID:
                row["校验状态"] = EVIDENCE_INVALID
                row["status"] = EVIDENCE_INVALID
                row["失效原因"] = reason
                row["pending"] = False
                row["abnormal"] = True
                count += 1
        return count
