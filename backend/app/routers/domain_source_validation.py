"""域源映射校验接口：查询校验证据、检查取数授权、触发重新校验。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.schemas import ActionResult, PageResult
from app.engine.domain_source_validator import DomainSourceValidator

router = APIRouter(prefix="/api/domain_source_validation", tags=["域源映射校验"])

validator = DomainSourceValidator()

LIST_FIELDS = ["校验编号", "域编号", "数据源表", "连接编号", "校验状态", "失效原因", "校验时间", "校验来源"]


@router.get("", response_model=PageResult[dict])
def list_records(
    domain_code: str | None = Query(default=None, description="按域编号过滤"),
    status: str | None = Query(default=None, description="有效、无可用连接、已失效、校验失败"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResult[dict]:
    """列出域源映射校验证据，每条证据记录数据源归属的连接编号与校验状态。"""
    rows = validator.list_records(domain_code)
    if status:
        rows = [row for row in rows if row.get("校验状态") == status]
    total = len(rows)
    start = (page - 1) * size
    return PageResult(items=rows[start:start + size], total=total, page=page, size=size)


@router.get("/{domain_code}/check")
def check_authorization(domain_code: str) -> dict[str, Any]:
    """计算端取数授权检查：只认证据绑定的连接编号，同库名连接不能替代。"""
    return validator.check_fetch_authorization(domain_code)


@router.post("/{domain_code}/revalidate", response_model=ActionResult)
def revalidate(domain_code: str) -> ActionResult:
    """重新校验指标域的数据源表与连接配置，生成新的校验证据。"""
    result = validator.validate_domain(domain_code, reason="重新校验")
    return ActionResult(ok=result["ok"], message=result["message"], entry=result["evidence"])
