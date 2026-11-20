"""1v1 Battle and Arena API endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.deps import get_current_user
from app.models.battle import (
    TIER_NAMES,
    TIER_ORDER,
    Battle,
    UserBattleStats,
)
from app.models.problem import Problem
from app.models.submission import Submission
from app.models.user import User
from app.services import battle as battle_svc
from app.services.judge import JudgeError, judge_submission, try_run as sandbox_try_run
from app.services.problem import ProblemService
from app.utils.ratelimit import check

router = APIRouter(prefix="/battle", tags=["battle"])

ROMAN_NUMERALS = {1: "I", 2: "II", 3: "III"}


class MatchRequest(BaseModel):
    mode: str = Field(default="casual", pattern="^(casual|ranked)$")
    simulate: bool = False
    forfeit_ongoing: bool = False


class BattleSubmitRequest(BaseModel):
    code: str = Field(min_length=1, max_length=65536)
    language: str = Field(pattern="^(cpp|c|python3)$")


def _user_identity(user: User) -> dict[str, Any]:
    """前端 userNameColor 计算身份色 + 主页跳转所需的最小字段集。"""
    return {
        "user_number": user.user_number,
        "is_banned": bool(user.is_banned),
        "is_cheater": bool(user.is_cheater),
        "is_admin": bool(user.is_admin),
        "is_super_admin": bool(user.is_super_admin),
        "can_manage_users": bool(user.can_manage_users),
        "can_manage_posts": bool(user.can_manage_posts),
        "can_manage_problems": bool(user.can_manage_problems),
        "can_manage_tags": bool(user.can_manage_tags),
    }


def _format_stats(stats: UserBattleStats, user: User) -> dict[str, Any]:
    tier_name = TIER_NAMES.get(stats.tier, "青铜")
    sub_roman = ROMAN_NUMERALS.get(stats.sub_tier, "III")
    win_rate = (stats.wins / stats.total_matches * 100) if stats.total_matches > 0 else 0.0

    return {
        "user_id": user.id,
        "username": user.username,
        "avatar_url": user.avatar_url,
        "user_tag": user.user_tag,
        "color_tier": user.color_tier,
        "name_color": user.name_color,
        **_user_identity(user),
        "experience": user.experience,
        "tier": stats.tier,
        "tier_name": tier_name,
        "sub_tier": stats.sub_tier,
        "sub_tier_roman": sub_roman,
        "points": stats.points,
        "rank_name": f"{tier_name} {sub_roman}",
        "rank_score": stats.rank_score,
        "total_matches": stats.total_matches,
        "wins": stats.wins,
        "losses": stats.losses,
        "draws": stats.draws,
        "win_rate": round(win_rate, 1),
        "win_streak": stats.win_streak,
        "max_win_streak": stats.max_win_streak,
    }


@router.get("/profile", summary="获取当前登录用户对战与段位信息")
async def get_my_battle_profile(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    stats = await battle_svc.get_or_create_user_stats(db, current_user.id)
    return _format_stats(stats, current_user)


@router.get("/leaderboard", summary="天梯段位排行榜")
async def get_ladder_leaderboard(
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Select all stats and sort in python using computed rank_score property
    # or tier index for SQL
    stmt = (
        select(UserBattleStats, User)
        .join(User, UserBattleStats.user_id == User.id)
        .where(User.is_active.is_(True))
    )
    res = await db.execute(stmt)
    rows = res.all()

    sorted_rows = sorted(
        rows,
        key=lambda pair: (pair[0].rank_score, pair[0].wins, pair[0].win_streak),
        reverse=True,
    )[:limit]

    items = []
    for rank, (stats, user) in enumerate(sorted_rows, start=1):
        item = _format_stats(stats, user)
        item["rank"] = rank
        items.append(item)

    return {"items": items, "total": len(items)}


@router.get("/history", summary="我的最近对战记录")
async def get_my_battle_history(
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    stmt = (
        select(Battle)
        .where(or_(Battle.user1_id == current_user.id, Battle.user2_id == current_user.id))
        .order_by(desc(Battle.id))
        .limit(limit)
    )
    res = await db.execute(stmt)
    battles = res.scalars().all()

    items = []
    for b in battles:
        is_user1 = b.user1_id == current_user.id
        opponent = b.user2 if is_user1 else b.user1

        if b.status == "ongoing":
            result = "ongoing"
        elif b.winner_id is None:
            result = "draw"
        elif b.winner_id == current_user.id:
            result = "win"
        else:
            result = "loss"

        items.append({
            "id": b.id,
            "mode": b.mode,
            "status": b.status,
            "result": result,
            "problem": {
                "id": b.problem_id,
                "title": b.problem.title if b.problem else "",
                "difficulty": b.problem.difficulty if b.problem else "",
                "code": f"P{1000 + b.problem_id}",
            },
            "opponent": {
                "id": opponent.id if opponent else 0,
                "username": opponent.username if opponent else "对手",
                "avatar_url": opponent.avatar_url if opponent else None,
                **(_user_identity(opponent) if opponent else {}),
            },
            "started_at": b.started_at,
            "finished_at": b.finished_at,
            "settlement": b.settlement.get("user1" if is_user1 else "user2") if b.settlement else None,
        })

    return {"items": items}


@router.get("/current", summary="获取当前进行中的对战（如果有）")
async def get_current_battle(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    stmt_ongoing = (
        select(Battle)
        .where(
            Battle.status == "ongoing",
            or_(Battle.user1_id == current_user.id, Battle.user2_id == current_user.id),
        )
        .order_by(desc(Battle.id))
        .limit(1)
    )
    res_ongoing = await db.execute(stmt_ongoing)
    battle = res_ongoing.scalar_one_or_none()
    if not battle:
        return {"has_ongoing": False}

    timed_out = await battle_svc.check_battle_timeout(db, battle)
    if timed_out or battle.status != "ongoing":
        return {"has_ongoing": False}

    now = datetime.now(timezone.utc)
    started_at = battle_svc._as_utc(battle.started_at)
    elapsed = int((now - started_at).total_seconds())
    remaining = max(0, battle.duration_seconds - elapsed)

    is_user1 = battle.user1_id == current_user.id
    opponent = battle.user2 if is_user1 else battle.user1

    return {
        "has_ongoing": True,
        "battle_id": battle.id,
        "mode": battle.mode,
        "remaining_seconds": remaining,
        "problem": {
            "id": battle.problem_id,
            "title": battle.problem.title if battle.problem else "",
            "difficulty": battle.problem.difficulty if battle.problem else "",
            "code": f"P{1000 + battle.problem_id}",
        },
        "opponent": {
            "id": opponent.id if opponent else 0,
            "username": opponent.username if opponent else "对手",
            "avatar_url": opponent.avatar_url if opponent else None,
        },
    }


@router.post("/match", summary="开始对战匹配")
async def start_matchmaking(
    payload: MatchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if payload.mode == "ranked" and payload.simulate:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="排位天梯模式不支持匹配模拟对手，仅普通对战模式可用",
        )

    # Check if user already in an ongoing battle
    stmt_ongoing = select(Battle).where(
        Battle.status == "ongoing",
        or_(Battle.user1_id == current_user.id, Battle.user2_id == current_user.id),
    ).order_by(desc(Battle.id)).limit(1)
    res_ongoing = await db.execute(stmt_ongoing)
    ongoing_battle = res_ongoing.scalar_one_or_none()
    if ongoing_battle:
        if payload.forfeit_ongoing:
            # Surrender current battle so player can rematch immediately
            winner_id = ongoing_battle.user2_id if current_user.id == ongoing_battle.user1_id else ongoing_battle.user1_id
            if current_user.id == ongoing_battle.user1_id:
                ongoing_battle.user1_status = "surrendered"
            else:
                ongoing_battle.user2_status = "surrendered"
            await battle_svc.settle_battle(db, ongoing_battle, winner_id=winner_id, finish_reason="surrender")
        else:
            timed_out = await battle_svc.check_battle_timeout(db, ongoing_battle)
            if not timed_out and ongoing_battle.status == "ongoing":
                return {"status": "matched", "battle_id": ongoing_battle.id}

    result = await battle_svc.enqueue_player(
        db,
        user_id=current_user.id,
        mode=payload.mode,
        simulate_fallback=payload.simulate,
    )
    return result


@router.delete("/match", summary="取消对战匹配")
async def cancel_matchmaking(
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    ok = await battle_svc.cancel_matchmaking(current_user.id)
    return {"ok": ok}


@router.get("/match/status", summary="查询匹配进度状态")
async def check_match_status(
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return await battle_svc.get_match_status(current_user.id)


@router.get("/rooms/{battle_id}", summary="获取对战房间详情与实时状态")
async def get_battle_room(
    battle_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    battle = await db.get(Battle, battle_id)
    if not battle:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="对战不存在")

    if current_user.id not in (battle.user1_id, battle.user2_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权进入此对战房间")

    # Check timeout settlement
    await battle_svc.check_battle_timeout(db, battle)

    stats1 = await battle_svc.get_or_create_user_stats(db, battle.user1_id)
    stats2 = await battle_svc.get_or_create_user_stats(db, battle.user2_id)

    # Remaining time calculation
    now = datetime.now(timezone.utc)
    started_at = battle_svc._as_utc(battle.started_at)
    elapsed = int((now - started_at).total_seconds())
    remaining = max(0, battle.duration_seconds - elapsed)

    problem = battle.problem
    p_dict = {
        "id": problem.id,
        "code": f"P{1000 + problem.id}",
        "title": problem.title,
        "difficulty": problem.difficulty,
        "time_limit": problem.time_limit,
        "memory_limit": problem.memory_limit,
        "background": problem.background or "",
        "description": problem.description or "",
        "input_format": problem.input_format or "",
        "output_format": problem.output_format or "",
        "hint": problem.hint or "",
        "samples": problem.samples or [],
    }

    # Query latest submission for current user in this battle
    stmt_sub = select(Submission).where(
        Submission.battle_id == battle.id,
        Submission.user_id == current_user.id,
    ).order_by(desc(Submission.id)).limit(1)
    res_sub = await db.execute(stmt_sub)
    my_latest_sub = res_sub.scalar_one_or_none()
    if not my_latest_sub:
        stmt_sub_fallback = select(Submission).where(
            Submission.problem_id == battle.problem_id,
            Submission.user_id == current_user.id,
        ).order_by(desc(Submission.id)).limit(1)
        res_fallback = await db.execute(stmt_sub_fallback)
        fallback_sub = res_fallback.scalar_one_or_none()
        if fallback_sub and battle_svc._as_utc(fallback_sub.created_at) >= started_at:
            my_latest_sub = fallback_sub
    sub_info = None
    if my_latest_sub:
        sub_info = {
            "id": my_latest_sub.id,
            "status": my_latest_sub.status,
            "time_used": my_latest_sub.time_used,
            "memory_used": my_latest_sub.memory_used,
            "error_message": my_latest_sub.error_message,
        }

    # Query screen switch violation counts
    v1 = await battle_svc.get_violation_status(db, battle.id, battle.user1_id)
    v2 = await battle_svc.get_violation_status(db, battle.id, battle.user2_id)
    count1 = v1.get("leave_count", 0) if v1 else 0
    count2 = v2.get("leave_count", 0) if v2 else 0
    my_screen_switch_count = count1 if battle.user1_id == current_user.id else count2

    return {
        "id": battle.id,
        "mode": battle.mode,
        "status": battle.status,
        "started_at": battle.started_at,
        "finished_at": battle.finished_at,
        "duration_seconds": battle.duration_seconds,
        "remaining_seconds": remaining,
        "winner_id": battle.winner_id,
        "settlement": battle.settlement,
        "user1": {
            "id": battle.user1.id,
            "username": battle.user1.username,
            "avatar_url": battle.user1.avatar_url,
            **_user_identity(battle.user1),
            "tier": stats1.tier,
            "sub_tier": stats1.sub_tier,
            "tier_name": TIER_NAMES.get(stats1.tier, "青铜"),
            "sub_tier_roman": ROMAN_NUMERALS.get(stats1.sub_tier, "III"),
            "status": battle.user1_status,
            "is_me": battle.user1_id == current_user.id,
            "screen_switch_count": count1,
        },
        "user2": {
            "id": battle.user2.id,
            "username": battle.user2.username,
            "avatar_url": battle.user2.avatar_url,
            **_user_identity(battle.user2),
            "tier": stats2.tier,
            "sub_tier": stats2.sub_tier,
            "tier_name": TIER_NAMES.get(stats2.tier, "青铜"),
            "sub_tier_roman": ROMAN_NUMERALS.get(stats2.sub_tier, "III"),
            "status": battle.user2_status,
            "is_me": battle.user2_id == current_user.id,
            "screen_switch_count": count2,
        },
        "problem": p_dict,
        "my_submission": sub_info,
        "my_screen_switch_count": my_screen_switch_count,
    }


@router.post("/rooms/{battle_id}/submit", summary="在对战中提交代码")
async def submit_battle_code(
    battle_id: int,
    payload: BattleSubmitRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    battle = await db.get(Battle, battle_id)
    if not battle:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="对战不存在")

    if current_user.id not in (battle.user1_id, battle.user2_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权参与此对战提交")

    if battle.status != "ongoing":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="对战已结束，无法继续提交")

    # Update player state to submitted
    if current_user.id == battle.user1_id:
        battle.user1_status = "submitted"
    else:
        battle.user2_status = "submitted"

    sub = Submission(
        problem_id=battle.problem_id,
        user_id=current_user.id,
        battle_id=battle.id,
        code=payload.code,
        language=payload.language,
        status="pending",
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)

    if current_user.id == battle.user1_id:
        battle.user1_submission_id = sub.id
    else:
        battle.user2_submission_id = sub.id
    await db.commit()

    background_tasks.add_task(judge_submission, sub.id)

    return {"submission_id": sub.id, "status": "pending"}
 
 
class BattleTryRunRequest(BaseModel):
    code: str = Field(min_length=1, max_length=65536)
    language: str = Field(pattern="^(cpp|c|python3)$")
    input: str = Field(default="", max_length=200000)


@router.post("/rooms/{battle_id}/try-run", summary="在对战中进行在线自测（编译 + 单次执行）")
async def try_run_battle_code(
    battle_id: int,
    payload: BattleTryRunRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    ok, wait = check(f"battle-try-run:{current_user.id}", 20, 60)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"自测运行太频繁，请 {wait} 秒后再试",
        )
    battle = await db.get(Battle, battle_id)
    if not battle:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="对战不存在")

    if current_user.id not in (battle.user1_id, battle.user2_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权在此对战中进行自测")

    if battle.status != "ongoing":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="对战已结束，无法进行自测")

    if not payload.code.strip():
        raise HTTPException(status_code=400, detail="代码不能为空")

    problem = battle.problem
    if not problem:
        problem = await ProblemService.get_by_id(db, battle.problem_id)
    if not problem:
        raise HTTPException(status_code=404, detail="对战题目不存在")

    try:
        return await sandbox_try_run(
            language=payload.language,
            code=payload.code,
            input_data=payload.input,
            time_limit_ms=problem.time_limit,
            memory_mb=problem.memory_limit,
        )
    except JudgeError as e:
        raise HTTPException(status_code=502, detail=f"评测沙箱不可用：{e}")


class BattleScreenSwitchRequest(BaseModel):
    action: Literal["leave", "return"]


@router.post("/rooms/{battle_id}/screen-switch", summary="上报对战切屏事件")
async def report_screen_switch(
    battle_id: int,
    payload: BattleScreenSwitchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """上报对战切屏事件。

    服务端权威判定能力：
    1. 服务端在记录切屏事件的同时进行阈值检测，一旦达到判负条件（离开次数>=2次或离开超时>=14.5秒），
       由服务端直接强制结算判负，无需等待违规方客户端主动发起 surrender 请求。
    2. 若违规方篡改前端或强退关闭浏览器，对手轮询房间时服务端通过 check_battle_timeout 自动判定超时判负。
    3. 注：针对高对抗性场景，后续版本规划引入基于 WebSocket 的服务端心跳探活与裁判系统。
    """
    battle = await db.get(Battle, battle_id)
    if not battle:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="对战不存在")

    if current_user.id not in (battle.user1_id, battle.user2_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权操作此对战")

    if battle.status != "ongoing":
        return {"ok": False, "status": battle.status}

    res = await battle_svc.record_screen_switch(battle_id, current_user.id, payload.action)

    # 服务端权威判定：违规达到阈值立即强制判负，不依赖客户端主动发起 surrender
    now_ts = datetime.now(timezone.utc).timestamp()
    is_second_violation = res.get("leave_count", 0) >= 2
    is_timeout_violation = (
        res.get("max_leave_duration", 0.0) >= 14.5
        or (res.get("last_leave_time") is not None and (now_ts - res["last_leave_time"]) >= 14.5)
    )

    if is_second_violation or is_timeout_violation:
        finish_reason = "screen_switch_second" if is_second_violation else "screen_switch_timeout"
        winner_id = battle.user2_id if current_user.id == battle.user1_id else battle.user1_id
        if current_user.id == battle.user1_id:
            battle.user1_status = "surrendered"
        else:
            battle.user2_status = "surrendered"
        await battle_svc.settle_battle(db, battle, winner_id=winner_id, finish_reason=finish_reason)
        return {
            "ok": True,
            "auto_forfeited": True,
            "winner_id": winner_id,
            "finish_reason": finish_reason,
            **res,
        }

    return {"ok": True, **res}


class BattleSurrenderRequest(BaseModel):
    reason: Literal["surrender", "screen_switch_timeout", "screen_switch_second"] = Field(
        default="surrender"
    )


@router.post("/rooms/{battle_id}/surrender", summary="主动认输/投降或切屏违规判负")
async def surrender_battle(
    battle_id: int,
    payload: BattleSurrenderRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    battle = await db.get(Battle, battle_id)
    if not battle:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="对战不存在")

    if current_user.id not in (battle.user1_id, battle.user2_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权操作此对战")

    requested_reason = payload.reason if payload and payload.reason else "surrender"
    if battle.status != "ongoing":
        saved_reason = (battle.settlement or {}).get("finish_reason") or requested_reason
        return {"ok": True, "status": battle.status, "winner_id": battle.winner_id, "finish_reason": saved_reason}

    if requested_reason in ("screen_switch_timeout", "screen_switch_second"):
        # 从服务端状态校验是否真的发生了对应违规
        violation_data = await battle_svc.get_violation_status(db, battle_id, current_user.id)
        if not battle_svc.is_violation_valid(violation_data, requested_reason):
            raise HTTPException(status_code=400, detail="违规状态不匹配，无法以此原因判负")
    finish_reason = requested_reason

    # Other player is winner
    winner_id = battle.user2_id if current_user.id == battle.user1_id else battle.user1_id
    if current_user.id == battle.user1_id:
        battle.user1_status = "surrendered"
    else:
        battle.user2_status = "surrendered"

    await battle_svc.settle_battle(db, battle, winner_id=winner_id, finish_reason=finish_reason)
    return {"ok": True, "winner_id": winner_id, "finish_reason": finish_reason}
