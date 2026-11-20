"""举报 API 与秩序管理举报审核。

前台：提交举报 / 查看自己对某内容的举报状态 / 审核前撤销举报。
后台：举报组列表（含已删除内容的快照）/ 审核判定。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps import get_current_user
from app.models.benben import Benben
from app.models.forum import ForumComment, ForumPost
from app.models.report import (
    REPORT_BENBEN,
    REPORT_COMMENT,
    REPORT_POST,
    STATUS_ACTIVE,
    TARGET_TYPES,
    VERDICT_FALSE,
    VERDICT_GUILTY,
    Report,
)
from app.models.user import User
from app.schemas.report import ReportCreate, VerdictPayload
from app.services import moderation
from app.services.moderation import (
    AUTO_DELETE_THRESHOLD,
    CATEGORY_NAMES,
    REASON_GUILTY,
    REASON_MULTI,
    TARGET_NAMES,
    is_order_admin,
    load_target,
    restore_target,
    soft_delete_target,
    target_author,
    target_link,
)
from app.services.notification import add_notification

router = APIRouter(tags=["reports"])


def _reporter_brief(user: User) -> dict[str, Any]:
    return {
        "user_id": user.id,
        "username": user.username,
        "user_number": user.user_number,
        "user_tag": user.display_tag,
        "avatar_url": user.avatar_url or "",
    }


async def _active_count(db: AsyncSession, target_type: str, target_id: int) -> int:
    return (await db.execute(
        select(func.count())
        .select_from(Report)
        .where(
            Report.target_type == target_type,
            Report.target_id == target_id,
            Report.status == STATUS_ACTIVE,
        )
    )).scalar() or 0


def _target_snapshot(target_type: str, obj: Any) -> dict[str, Any]:
    """被举报内容的快照（软删除后仍可渲染，供后台查看）。"""
    deleted_info = {
        "is_deleted": bool(obj.is_deleted),
        "delete_reason": obj.delete_reason,
        "deleted_at": obj.deleted_at.isoformat() if obj.deleted_at else None,
        "deleted_by_id": obj.deleted_by_id,
    }
    if target_type == REPORT_BENBEN:
        return {
            "kind": REPORT_BENBEN,
            "id": obj.id,
            "content": obj.content,
            "reply_to": obj.reply_to,
            "created_at": obj.created_at.isoformat() if obj.created_at else None,
            "author": _reporter_brief(obj.user) if obj.user else None,
            **deleted_info,
        }
    if target_type == REPORT_POST:
        return {
            "kind": REPORT_POST,
            "id": obj.id,
            "title": obj.title,
            "content": obj.content,
            "forum": obj.forum,
            "created_at": obj.created_at.isoformat() if obj.created_at else None,
            "author": _reporter_brief(obj.author) if obj.author else None,
            **deleted_info,
        }
    return {
        "kind": REPORT_COMMENT,
        "id": obj.id,
        "post_id": obj.post_id,
        "post_title": obj.post.title if obj.post else None,
        "content": obj.content,
        "created_at": obj.created_at.isoformat() if obj.created_at else None,
        "author": _reporter_brief(obj.author) if obj.author else None,
        **deleted_info,
    }


# ============ 前台接口 ============

@router.post("/reports", summary="举报犇犇/帖子/帖子回复", status_code=status.HTTP_201_CREATED)
async def create_report(
    payload: ReportCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    # 有自由发言的人才可以举报
    if not current_user.can_speak:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="你已被禁言，无法举报",
        )

    target = await load_target(db, payload.target_type, payload.target_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="被举报内容不存在",
        )

    author = target_author(payload.target_type, target)
    if author is not None and author.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能举报自己的内容",
        )

    existing = (await db.execute(
        select(Report).where(
            Report.reporter_id == current_user.id,
            Report.target_type == payload.target_type,
            Report.target_id == payload.target_id,
        )
    )).scalar_one_or_none()

    if existing is not None:
        if existing.verdict is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="该内容已完成审核，不能再次举报",
            )
        if existing.status == STATUS_ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="你已经举报过该内容",
            )
        # 此前撤销过：重新激活原记录
        existing.status = STATUS_ACTIVE
        existing.category = payload.category
        existing.detail = payload.detail
    else:
        db.add(Report(
            reporter_id=current_user.id,
            target_type=payload.target_type,
            target_id=payload.target_id,
            category=payload.category,
            detail=payload.detail,
        ))
    await db.flush()

    active_count = await _active_count(db, payload.target_type, payload.target_id)
    auto_deleted = False
    if active_count >= AUTO_DELETE_THRESHOLD:
        # 多人举报：自动软删除，内容保留供后台审核
        await soft_delete_target(
            db,
            payload.target_type,
            target,
            reason=REASON_MULTI,
            admin_id=None,
        )
        auto_deleted = True
    else:
        await db.commit()

    return {
        "reported": True,
        "status": STATUS_ACTIVE,
        "active_count": active_count,
        "auto_deleted": auto_deleted,
    }


@router.get("/reports/check", summary="查询我对某内容的举报状态")
async def check_report(
    target_type: str = Query(pattern=f"^({'|'.join(TARGET_TYPES)})$"),
    target_id: int = Query(gt=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    report = (await db.execute(
        select(Report).where(
            Report.reporter_id == current_user.id,
            Report.target_type == target_type,
            Report.target_id == target_id,
        )
    )).scalar_one_or_none()
    if report is None:
        return {"reported": False}
    return {
        "reported": report.status == STATUS_ACTIVE,
        "status": report.status,
        "verdict": report.verdict,
        "report_id": report.id,
        "revocable": report.verdict is None and report.status == STATUS_ACTIVE,
    }


@router.post("/reports/{report_id}/revoke", summary="撤销举报（审核前）")
async def revoke_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    report = (await db.execute(
        select(Report).where(Report.id == report_id)
    )).scalar_one_or_none()
    if report is None or report.reporter_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="举报不存在")
    if report.verdict is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="举报已审核，不能撤销",
        )
    if report.status != STATUS_ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该举报已经撤销",
        )

    report.status = "revoked"
    await db.flush()
    active_count = await _active_count(
        db, report.target_type, report.target_id
    )

    restored = False
    target = await load_target(
        db, report.target_type, report.target_id, include_deleted=True
    )
    if (
        active_count < AUTO_DELETE_THRESHOLD
        and target is not None
        and target.is_deleted
        and target.delete_reason == REASON_MULTI
    ):
        # 举报撤销后不足阈值：自动恢复此前被多人举报删除的内容
        restored = await restore_target(db, report.target_type, target)
    else:
        await db.commit()

    return {"active_count": active_count, "restored": restored}


# ============ 秩序管理后台接口 ============

@router.get("/reports/admin", summary="举报组列表（秩序管理）")
async def admin_list_reports(
    verdict_filter: str = Query(
        "pending",
        alias="verdict",
        pattern="^(pending|guilty|false_report|all)$",
    ),
    target_type: str = Query(
        "all", pattern=f"^(all|{'|'.join(TARGET_TYPES)})$"
    ),
    page: int = Query(0, ge=0),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if not is_order_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要秩序管理权限",
        )

    active_expr = case(
        (Report.status == STATUS_ACTIVE, 1), else_=0
    )
    verdict_expr = func.max(Report.verdict)
    group_q = (
        select(
            Report.target_type.label("target_type"),
            Report.target_id.label("target_id"),
            verdict_expr.label("verdict"),
            func.sum(active_expr).label("active_count"),
            func.count().label("total_count"),
            func.max(Report.created_at).label("last_at"),
        )
        .group_by(Report.target_type, Report.target_id)
    )
    if target_type != "all":
        group_q = group_q.where(Report.target_type == target_type)
    if verdict_filter == "pending":
        # 仅当该 target 下所有举报均未审核时才算待审核
        group_q = group_q.having(func.max(Report.verdict).is_(None))
    elif verdict_filter in (VERDICT_GUILTY, VERDICT_FALSE):
        group_q = group_q.having(func.max(Report.verdict) == verdict_filter)

    count_q = select(func.count()).select_from(group_q.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # 待审核（verdict 为空）排最前，同状态按最近举报时间倒序
    groups = (await db.execute(
        group_q.order_by(
            case((verdict_expr.is_(None), 0), else_=1),
            func.max(Report.created_at).desc(),
        )
        .offset(page * page_size)
        .limit(page_size)
    )).mappings().all()

    pairs = [(g["target_type"], g["target_id"]) for g in groups]

    # 批量拉取这些组的举报明细
    reports_by_pair: dict[tuple[str, int], list[Report]] = {}
    if pairs:
        conditions = [
            (Report.target_type == tt) & (Report.target_id == tid)
            for tt, tid in pairs
        ]
        detail_rows = (await db.execute(
            select(Report).where(or_(*conditions)).order_by(Report.id)
        )).scalars().all()
        for r in detail_rows:
            reports_by_pair.setdefault(
                (r.target_type, r.target_id), []
            ).append(r)

    items: list[dict] = []
    for g in groups:
        tt, tid = g["target_type"], g["target_id"]
        target = await load_target(db, tt, tid, include_deleted=True)
        rows = reports_by_pair.get((tt, tid), [])
        items.append({
            "target_type": tt,
            "target_id": tid,
            "target_name": TARGET_NAMES[tt],
            "verdict": g["verdict"],
            "active_count": int(g["active_count"] or 0),
            "total_count": int(g["total_count"] or 0),
            "last_at": g["last_at"].isoformat() if g["last_at"] else None,
            "target": _target_snapshot(tt, target) if target is not None else None,
            "reports": [
                {
                    "id": r.id,
                    "reporter": _reporter_brief(r.reporter),
                    "category": r.category,
                    "category_name": CATEGORY_NAMES.get(r.category, r.category),
                    "detail": r.detail,
                    "status": r.status,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ],
        })

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }


@router.post(
    "/reports/admin/{target_type}/{target_id}/verdict",
    summary="审核举报（秩序管理）",
)
async def review_reports(
    target_type: str,
    target_id: int,
    payload: VerdictPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if not is_order_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要秩序管理权限",
        )
    if target_type not in TARGET_TYPES:
        raise HTTPException(status_code=400, detail="无效的目标类型")

    reports = (await db.execute(
        select(Report)
        .where(
            Report.target_type == target_type,
            Report.target_id == target_id,
        )
        .order_by(Report.id)
    )).scalars().all()
    if not reports:
        raise HTTPException(status_code=404, detail="举报不存在")
    if any(r.verdict is not None for r in reports):
        raise HTTPException(status_code=400, detail="该举报已审核")

    target = await load_target(db, target_type, target_id, include_deleted=True)
    now = datetime.now(timezone.utc)

    if payload.verdict == VERDICT_GUILTY:
        # ---- 举报成立：删除违规内容（不再自动禁言作者，由管理员手动处理） ----
        if target is not None and not target.is_deleted:
            await soft_delete_target(
                db,
                target_type,
                target,
                reason=REASON_GUILTY,
                admin_id=current_user.id,
            )

        author = (
            target_author(target_type, target) if target is not None else None
        )
        if author is not None:
            tname = TARGET_NAMES[target_type]
            add_notification(
                db,
                user_id=author.id,
                ntype="status",
                actor_id=current_user.id,
                link=target_link(target_type, target),
                content=(
                    f"你的{tname}经举报审核被认定为违规内容，已删除；"
                    "请遵守社区规范"
                ),
            )

        for r in reports:
            if r.verdict is None:
                r.verdict = VERDICT_GUILTY
                r.reviewed_by_id = current_user.id
                r.reviewed_at = now
        await db.commit()
        return {
            "verdict": VERDICT_GUILTY,
            "author_mute": None,
        }

    # ---- 举报不成立（恶意举报）：恢复内容（不再自动禁言举报人，由管理员手动处理） ----
    active_reports = [r for r in reports if r.status == STATUS_ACTIVE]

    restored = False
    if target is not None and target.is_deleted:
        restored = await restore_target(db, target_type, target)

    tname = TARGET_NAMES[target_type]
    link = (
        target_link(target_type, target)
        if target is not None
        else None
    )
    for r in active_reports:
        reporter = r.reporter
        add_notification(
            db,
            user_id=reporter.id,
            ntype="status",
            actor_id=current_user.id,
            link=link,
            content=(
                f"你举报的{tname}经审核不存在违规，你的举报被认定为恶意举报，"
                "请遵守社区规范"
            ),
        )

    for r in reports:
        if r.verdict is None:
            r.verdict = VERDICT_FALSE
            r.reviewed_by_id = current_user.id
            r.reviewed_at = now
    await db.commit()

    return {
        "verdict": VERDICT_FALSE,
        "content_restored": restored,
        "punished": [],
    }
