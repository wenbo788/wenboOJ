"""1v1 Battle service: matchmaking, rank rating, problem assignment, and settlement."""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.battle import (
    TIER_BRONZE,
    TIER_DIAMOND,
    TIER_GOLD,
    TIER_ORDER,
    TIER_PLATINUM,
    TIER_SILVER,
    Battle,
    UserBattleStats,
)
from app.models.problem import Problem
from app.models.submission import Submission
from app.models.user import User

logger = logging.getLogger("oj.battle")

# Difficulty mapping for each tier
TIER_DIFFICULTIES: dict[str, list[str]] = {
    TIER_BRONZE: ["入门", "普及-"],
    TIER_SILVER: ["普及-", "普及"],
    # 旧档位名（改名前的「普及+/提高」）一并保留：这张表是按 problem.difficulty
    # 过滤候选题的，部署窗口期（新代码已上、存量数据迁移未跑）若不含旧串，
    # 该档位的存量题会被漏选
    TIER_GOLD: ["普及", "普及+/提高-", "普及+/提高"],
    TIER_PLATINUM: ["普及+/提高-", "普及+/提高", "提高"],
    TIER_DIAMOND: ["提高+/省选-", "省选/NOI-", "NOI/NOI+/CTSC"],
}

# In-memory matchmaking queue: user_id -> QueueItem
_MATCH_QUEUE: dict[int, dict[str, Any]] = {}
_QUEUE_LOCK = asyncio.Lock()

# In-memory screen switch violation tracker: (battle_id, user_id) -> dict
# Note: In multi-worker production deployments, _SCREEN_VIOLATION_TRACKER should be backed by Redis.
_SCREEN_VIOLATION_TRACKER: dict[tuple[int, int], dict[str, Any]] = {}
_VIOLATION_LOCK = asyncio.Lock()
_VIOLATION_TTL_SECONDS = 7200  # 2 hours TTL to sweep abandoned battle tracking entries


async def record_screen_switch(battle_id: int, user_id: int, action: str) -> dict[str, Any]:
    """Record player screen switch leave/return event with TTL sweeping."""
    async with _VIOLATION_LOCK:
        now_ts = datetime.now(timezone.utc).timestamp()
        # Periodic sweep to prevent memory leak from abandoned battles
        for k in list(_SCREEN_VIOLATION_TRACKER.keys()):
            e = _SCREEN_VIOLATION_TRACKER.get(k)
            if e and (now_ts - e.get("updated_at", now_ts)) > _VIOLATION_TTL_SECONDS:
                _SCREEN_VIOLATION_TRACKER.pop(k, None)

        key = (battle_id, user_id)
        entry = _SCREEN_VIOLATION_TRACKER.setdefault(
            key,
            {
                "leave_count": 0,
                "last_leave_time": None,
                "max_leave_duration": 0.0,
                "created_at": now_ts,
                "updated_at": now_ts,
            },
        )
        entry["updated_at"] = now_ts
        if action == "leave":
            entry["leave_count"] += 1
            entry["last_leave_time"] = now_ts
        elif action == "return":
            if entry["last_leave_time"] is not None:
                duration = max(0.0, now_ts - entry["last_leave_time"])
                if duration > entry["max_leave_duration"]:
                    entry["max_leave_duration"] = duration
                entry["last_leave_time"] = None
        return dict(entry)


async def get_violation_status(
    db: AsyncSession, battle_id: int, user_id: int
) -> dict[str, Any] | None:
    """Retrieve screen switch violation data for given battle and user."""
    async with _VIOLATION_LOCK:
        entry = _SCREEN_VIOLATION_TRACKER.get((battle_id, user_id))
        if not entry:
            return None
        return dict(entry)


def is_violation_valid(violation_data: dict[str, Any] | None, reason: str) -> bool:
    """Validate whether requested forfeit reason matches server-recorded screen violations."""
    if not violation_data:
        return False
    now_ts = datetime.now(timezone.utc).timestamp()
    if reason == "screen_switch_second":
        return violation_data.get("leave_count", 0) >= 2
    if reason == "screen_switch_timeout":
        max_dur = violation_data.get("max_leave_duration", 0.0)
        if max_dur >= 14.5:
            return True
        last_leave = violation_data.get("last_leave_time")
        if last_leave is not None and (now_ts - last_leave) >= 14.5:
            return True
        return False
    return False


async def clear_violation_status(battle_id: int) -> None:
    """Clean up tracking data when battle finishes, with lock protection and TTL sweeping."""
    async with _VIOLATION_LOCK:
        now_ts = datetime.now(timezone.utc).timestamp()
        for key in list(_SCREEN_VIOLATION_TRACKER.keys()):
            entry = _SCREEN_VIOLATION_TRACKER.get(key)
            if key[0] == battle_id or (entry and (now_ts - entry.get("updated_at", now_ts)) > _VIOLATION_TTL_SECONDS):
                _SCREEN_VIOLATION_TRACKER.pop(key, None)


def _as_utc(dt: datetime | None) -> datetime:
    """Normalize datetime to timezone-aware UTC datetime."""
    if dt is None:
        return datetime.now(timezone.utc)
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


async def get_or_create_user_stats(db: AsyncSession, user_id: int) -> UserBattleStats:
    """Fetch existing user battle stats or initialize as Bronze III."""
    stmt = select(UserBattleStats).where(UserBattleStats.user_id == user_id)
    res = await db.execute(stmt)
    stats = res.scalar_one_or_none()
    if stats is None:
        stats = UserBattleStats(
            user_id=user_id,
            tier=TIER_BRONZE,
            sub_tier=3,
            points=0,
            total_matches=0,
            wins=0,
            losses=0,
            draws=0,
            win_streak=0,
            max_win_streak=0,
        )
        db.add(stats)
        await db.commit()
        await db.refresh(stats)
    return stats


async def select_battle_problem(
    db: AsyncSession, user1_id: int, user2_id: int, avg_tier: str
) -> Problem:
    """Select a public problem that matches the players' strength."""
    target_diffs = TIER_DIFFICULTIES.get(avg_tier, ["入门", "普及-"])

    # Collect problem IDs already accepted by either user
    stmt_ac = select(Submission.problem_id).where(
        Submission.user_id.in_([user1_id, user2_id]),
        Submission.status == "accepted",
    )
    res_ac = await db.execute(stmt_ac)
    solved_problem_ids = set(res_ac.scalars().all())

    # Candidate query for public official problems with target difficulties
    stmt_candidates = select(Problem).where(
        Problem.is_public.is_(True),
        Problem.team_id.is_(None),
        Problem.is_official.is_(True),
        Problem.difficulty.in_(target_diffs),
    )
    res_candidates = await db.execute(stmt_candidates)
    candidate_problems = res_candidates.scalars().all()

    # Prefer problems not yet AC-ed by both players
    fresh_problems = [p for p in candidate_problems if p.id not in solved_problem_ids]
    if fresh_problems:
        return random.choice(fresh_problems)

    if candidate_problems:
        return random.choice(candidate_problems)

    # Fallback: any public official problem
    stmt_any = select(Problem).where(
        Problem.is_public.is_(True),
        Problem.team_id.is_(None),
        Problem.is_official.is_(True),
    )
    res_any = await db.execute(stmt_any)
    any_problems = res_any.scalars().all()
    if any_problems:
        return random.choice(any_problems)

    raise ValueError("题库中暂无可用的公开对战题目")


async def create_battle(
    db: AsyncSession,
    user1_id: int,
    user2_id: int,
    mode: str,
) -> Battle:
    """Create and start a new 1v1 battle."""
    stats1 = await get_or_create_user_stats(db, user1_id)
    stats2 = await get_or_create_user_stats(db, user2_id)

    # Determine average tier
    tier1_idx = TIER_ORDER.index(stats1.tier) if stats1.tier in TIER_ORDER else 0
    tier2_idx = TIER_ORDER.index(stats2.tier) if stats2.tier in TIER_ORDER else 0
    avg_tier_idx = (tier1_idx + tier2_idx) // 2
    avg_tier = TIER_ORDER[avg_tier_idx]

    problem = await select_battle_problem(db, user1_id, user2_id, avg_tier)

    now = datetime.now(timezone.utc)
    battle = Battle(
        mode=mode,
        status="ongoing",
        user1_id=user1_id,
        user2_id=user2_id,
        problem_id=problem.id,
        started_at=now,
        duration_seconds=1800,  # 30 minutes
        user1_status="coding",
        user2_status="coding",
    )
    db.add(battle)
    await db.commit()
    await db.refresh(battle)
    logger.info("Created battle %d: user %d vs user %d on problem %d", battle.id, user1_id, user2_id, problem.id)
    return battle


def _calculate_ranked_win(stats: UserBattleStats) -> dict[str, Any]:
    """Calculate point and tier changes for ranked victory."""
    old_tier = stats.tier
    old_sub_tier = stats.sub_tier
    old_points = stats.points

    points_gain = 30
    new_points = old_points + points_gain
    new_tier = old_tier
    new_sub_tier = old_sub_tier
    promoted = False

    if new_points >= 100:
        promoted = True
        overflow = new_points - 100
        if new_tier == TIER_DIAMOND and new_sub_tier == 1:
            # Diamond I max points cap
            new_points = 100
            promoted = False
        elif new_sub_tier > 1:
            # e.g., Bronze III -> Bronze II
            new_sub_tier -= 1
            new_points = overflow
        else:
            # e.g., Bronze I -> Silver III
            tier_idx = TIER_ORDER.index(new_tier)
            if tier_idx + 1 < len(TIER_ORDER):
                new_tier = TIER_ORDER[tier_idx + 1]
                new_sub_tier = 3
                new_points = overflow

    stats.tier = new_tier
    stats.sub_tier = new_sub_tier
    stats.points = new_points
    stats.wins += 1
    stats.total_matches += 1
    stats.win_streak += 1
    if stats.win_streak > stats.max_win_streak:
        stats.max_win_streak = stats.win_streak

    return {
        "points_delta": points_gain,
        "old_tier": old_tier,
        "old_sub_tier": old_sub_tier,
        "old_points": old_points,
        "new_tier": new_tier,
        "new_sub_tier": new_sub_tier,
        "new_points": new_points,
        "promoted": promoted,
    }


def _calculate_ranked_loss(stats: UserBattleStats) -> dict[str, Any]:
    """Calculate point and tier changes for ranked loss with protection."""
    old_tier = stats.tier
    old_sub_tier = stats.sub_tier
    old_points = stats.points

    stats.losses += 1
    stats.total_matches += 1
    stats.win_streak = 0

    demoted = False

    # Bronze rookie protection: never demotes tier or sub-tier, minor loss
    if stats.tier == TIER_BRONZE:
        points_loss = 8
        new_points = max(0, old_points - points_loss)
        stats.points = new_points
        return {
            "points_delta": -min(points_loss, old_points),
            "old_tier": old_tier,
            "old_sub_tier": old_sub_tier,
            "old_points": old_points,
            "new_tier": stats.tier,
            "new_sub_tier": stats.sub_tier,
            "new_points": stats.points,
            "demoted": False,
        }

    # Silver and above
    points_loss = 15
    if old_points >= points_loss:
        # Simple point deduction without demotion
        stats.points = old_points - points_loss
    elif old_points > 0:
        # Zero-point protection: drops to 0 without immediate demotion
        stats.points = 0
    else:
        # At 0 points: graceful demotion with 70 buffer points
        demoted = True
        if stats.sub_tier < 3:
            # e.g., Silver I -> Silver II
            stats.sub_tier += 1
            stats.points = 70
        else:
            # e.g., Gold III -> Silver I
            tier_idx = TIER_ORDER.index(stats.tier)
            if tier_idx > 0:
                stats.tier = TIER_ORDER[tier_idx - 1]
                stats.sub_tier = 1
                stats.points = 75

    return {
        "points_delta": -points_loss if not demoted else 0,
        "old_tier": old_tier,
        "old_sub_tier": old_sub_tier,
        "old_points": old_points,
        "new_tier": stats.tier,
        "new_sub_tier": stats.sub_tier,
        "new_points": stats.points,
        "demoted": demoted,
    }


async def settle_battle(
    db: AsyncSession,
    battle: Battle,
    winner_id: int | None,
    finish_reason: str = "ac",
) -> Battle:
    """Finalize battle, update ranks and grant experience points."""
    if battle.status == "finished":
        return battle

    battle.status = "finished"
    battle.winner_id = winner_id
    battle.finished_at = datetime.now(timezone.utc)

    stats1 = await get_or_create_user_stats(db, battle.user1_id)
    stats2 = await get_or_create_user_stats(db, battle.user2_id)
    user1 = await db.get(User, battle.user1_id)
    user2 = await db.get(User, battle.user2_id)

    settlement: dict[str, Any] = {
        "mode": battle.mode,
        "finish_reason": finish_reason,
        "winner_id": winner_id,
        "user1": {},
        "user2": {},
    }

    is_ranked = battle.mode == "ranked"

    if winner_id == battle.user1_id:
        battle.user1_status = "accepted" if finish_reason == "ac" else "coding"
        # User 1 won
        xp1 = 50 if is_ranked else 30
        xp2 = 15 if is_ranked else 10
        if is_ranked:
            u1_rank = _calculate_ranked_win(stats1)
            u2_rank = _calculate_ranked_loss(stats2)
        else:
            stats1.wins += 1
            stats1.total_matches += 1
            stats2.losses += 1
            stats2.total_matches += 1
            u1_rank = {}
            u2_rank = {}

        if user1:
            user1.experience = (user1.experience or 0) + xp1
        if user2:
            user2.experience = (user2.experience or 0) + xp2

        settlement["user1"] = {"result": "win", "xp_gain": xp1, "rank": u1_rank}
        settlement["user2"] = {"result": "loss", "xp_gain": xp2, "rank": u2_rank}

    elif winner_id == battle.user2_id:
        battle.user2_status = "accepted" if finish_reason == "ac" else "coding"
        # User 2 won
        xp1 = 15 if is_ranked else 10
        xp2 = 50 if is_ranked else 30
        if is_ranked:
            u1_rank = _calculate_ranked_loss(stats1)
            u2_rank = _calculate_ranked_win(stats2)
        else:
            stats1.losses += 1
            stats1.total_matches += 1
            stats2.wins += 1
            stats2.total_matches += 1
            u1_rank = {}
            u2_rank = {}

        if user1:
            user1.experience = (user1.experience or 0) + xp1
        if user2:
            user2.experience = (user2.experience or 0) + xp2

        settlement["user1"] = {"result": "loss", "xp_gain": xp1, "rank": u1_rank}
        settlement["user2"] = {"result": "win", "xp_gain": xp2, "rank": u2_rank}

    else:
        # Draw (e.g. timeout)
        xp = 15
        stats1.draws += 1
        stats1.total_matches += 1
        stats2.draws += 1
        stats2.total_matches += 1
        if user1:
            user1.experience = (user1.experience or 0) + xp
        if user2:
            user2.experience = (user2.experience or 0) + xp
        settlement["user1"] = {"result": "draw", "xp_gain": xp, "rank": {}}
        settlement["user2"] = {"result": "draw", "xp_gain": xp, "rank": {}}

    battle.settlement = settlement
    await db.commit()
    await db.refresh(battle)

    # Purge matchmaking queue entries for both participants
    async with _QUEUE_LOCK:
        _MATCH_QUEUE.pop(battle.user1_id, None)
        _MATCH_QUEUE.pop(battle.user2_id, None)

    await clear_violation_status(battle.id)

    logger.info("Settled battle %d, winner: %s, reason: %s", battle.id, winner_id, finish_reason)
    return battle


async def enqueue_player(
    db: AsyncSession,
    user_id: int,
    mode: str,
    simulate_fallback: bool = False,
) -> dict[str, Any]:
    """Enqueue player into matchmaking queue and attempt pairing."""
    stats = await get_or_create_user_stats(db, user_id)
    score = stats.rank_score

    async with _QUEUE_LOCK:
        # Purge any previous entry for this user
        _MATCH_QUEUE.pop(user_id, None)

        # Check existing candidates in queue
        best_opponent_id = None
        min_diff = 999999
        now = datetime.now(timezone.utc)

        for opp_id, entry in list(_MATCH_QUEUE.items()):
            if opp_id == user_id or entry["mode"] != mode:
                continue
            if entry.get("matched_battle_id"):
                continue

            wait_seconds = (now - _as_utc(entry["queued_at"])).total_seconds()
            score_diff = abs(entry["score"] - score)
            # Match tolerance expands with wait time: starts at 150, +50 per 5 seconds
            allowed_diff = 150 + int(wait_seconds / 5) * 50

            if score_diff <= allowed_diff and score_diff < min_diff:
                min_diff = score_diff
                best_opponent_id = opp_id

        if best_opponent_id is not None:
            # Pair both players
            opp_entry = _MATCH_QUEUE.pop(best_opponent_id)
            battle = await create_battle(db, best_opponent_id, user_id, mode)

            # Inform waiting opponent (polling get_match_status)
            _MATCH_QUEUE[best_opponent_id] = {
                "user_id": best_opponent_id,
                "mode": mode,
                "score": opp_entry["score"],
                "queued_at": opp_entry["queued_at"],
                "matched_battle_id": battle.id,
            }
            # Current player (user_id) gets it directly in HTTP response
            return {"status": "matched", "battle_id": battle.id}

        # If user explicitly requests simulate/practice mode (only available in casual mode)
        if simulate_fallback and mode == "casual":
            bot_stmt = select(User.id).where(User.id != user_id, User.is_active.is_(True)).order_by(User.id).limit(1)
            res_bot = await db.execute(bot_stmt)
            bot_user_id = res_bot.scalar_one_or_none()
            if bot_user_id:
                battle = await create_battle(db, user_id, bot_user_id, "casual")
                return {"status": "matched", "battle_id": battle.id}

        # No immediate match, enqueue player
        _MATCH_QUEUE[user_id] = {
            "user_id": user_id,
            "mode": mode,
            "score": score,
            "queued_at": now,
            "matched_battle_id": None,
        }
        return {"status": "queued"}


async def cancel_matchmaking(user_id: int) -> bool:
    """Remove user from matchmaking queue."""
    async with _QUEUE_LOCK:
        if user_id in _MATCH_QUEUE:
            del _MATCH_QUEUE[user_id]
            return True
        return False


async def get_match_status(user_id: int) -> dict[str, Any]:
    """Query current matchmaking state."""
    async with _QUEUE_LOCK:
        entry = _MATCH_QUEUE.get(user_id)
        if not entry:
            return {"status": "idle"}
        if entry.get("matched_battle_id"):
            battle_id = entry["matched_battle_id"]
            # Clean up matched entry once acknowledged
            del _MATCH_QUEUE[user_id]
            return {"status": "matched", "battle_id": battle_id}
        wait_time = int((datetime.now(timezone.utc) - _as_utc(entry["queued_at"])).total_seconds())
        return {"status": "queued", "mode": entry["mode"], "wait_time": wait_time}


async def check_submission_for_battle(db: AsyncSession, submission: Submission) -> None:
    """Trigger battle win when player achieves accepted status on battle problem."""
    # Find battle for this submission
    battle: Battle | None = None
    if submission.battle_id:
        battle = await db.get(Battle, submission.battle_id)
    else:
        stmt = select(Battle).where(
            Battle.status == "ongoing",
            Battle.problem_id == submission.problem_id,
            or_(Battle.user1_id == submission.user_id, Battle.user2_id == submission.user_id),
        ).order_by(desc(Battle.id)).limit(1)
        res = await db.execute(stmt)
        battle = res.scalar_one_or_none()

    if not battle:
        return

    # Check timeout first
    if await check_battle_timeout(db, battle):
        return

    if battle.status != "ongoing":
        return

    is_user1 = submission.user_id == battle.user1_id
    if submission.status == "accepted":
        sub_time = _as_utc(submission.created_at)
        battle_start = _as_utc(battle.started_at)
        if submission.battle_id or battle_start <= sub_time:
            # First to AC wins
            if battle.winner_id is None:
                if is_user1:
                    battle.user1_submission_id = submission.id
                    battle.user1_status = "accepted"
                else:
                    battle.user2_submission_id = submission.id
                    battle.user2_status = "accepted"
                await settle_battle(db, battle, winner_id=submission.user_id, finish_reason="ac")
    else:
        # Non-AC submission: reset status from submitted back to coding
        if is_user1 and battle.user1_status == "submitted":
            battle.user1_status = "coding"
            await db.commit()
        elif not is_user1 and battle.user2_status == "submitted":
            battle.user2_status = "coding"
            await db.commit()


async def check_battle_timeout(db: AsyncSession, battle: Battle) -> bool:
    """Check if battle exceeded duration or had unreturned screen switch violation and settle authoritatively."""
    if battle.status != "ongoing":
        return False
    now = datetime.now(timezone.utc)
    started_at = _as_utc(battle.started_at)
    elapsed = (now - started_at).total_seconds()
    if elapsed >= battle.duration_seconds:
        await settle_battle(db, battle, winner_id=None, finish_reason="timeout")
        return True

    # 服务端主动判定切屏违规：若某选手离开超过 15 秒或达到 2 次违规，服务端权威判负
    now_ts = now.timestamp()
    forfeited_uid = None
    finish_reason = None
    async with _VIOLATION_LOCK:
        for uid in (battle.user1_id, battle.user2_id):
            entry = _SCREEN_VIOLATION_TRACKER.get((battle.id, uid))
            if not entry:
                continue
            last_leave = entry.get("last_leave_time")
            if last_leave is not None and (now_ts - last_leave) >= 15.0:
                forfeited_uid = uid
                finish_reason = "screen_switch_timeout"
                break
            if entry.get("leave_count", 0) >= 2:
                forfeited_uid = uid
                finish_reason = "screen_switch_second"
                break

    if forfeited_uid is not None and finish_reason:
        winner_id = battle.user2_id if forfeited_uid == battle.user1_id else battle.user1_id
        if forfeited_uid == battle.user1_id:
            battle.user1_status = "surrendered"
        else:
            battle.user2_status = "surrendered"
        await settle_battle(db, battle, winner_id=winner_id, finish_reason=finish_reason)
        return True

    return False
