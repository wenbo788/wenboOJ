"""比赛排行榜的分制计算（XCPC / IOI / OI）。

**为什么单独抽出来**：`GET /contests/{id}/rank`（展示）和等级分结算
（`services/contest_rating.py`）必须用**同一套**名次算法 —— 否则「榜单上的
第 3 名」和「结算时算的第 3 名」早晚会不一样。以前结算直接调用端点函数
（还传 `current_user=None`），既绕又脆；现在两边都走这里。

这里只算**数据**：名次、通过数、罚时/总分、逐题明细。可见性（是否允许看榜、
OI 赛中冻结等）留在端点里 —— 那是展示策略，不是分制。

虚拟参赛的提交不挂 ``contest_id``（只挂 ``virtual_contest_id``），按 ``contest_id``
查询天然排除；这里再显式排一遍（``Submission.virtual_contest_id IS NULL``）作防御，
免得将来某条写入路径带上 ``contest_id`` 把虚拟成绩混进正式榜单。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.models.contest import Contest, ContestParticipant, ContestProblem, ContestTeam
from app.models.submission import Submission

ALIAS = "ABCDEFGHJKLMNPQRSTUVWXYZ"  # 比赛题别名

RULE_LABELS = {
    "xcpc": "XCPC 赛制",
    "acm": "XCPC 赛制",
    "oi": "OI 赛制",
    "ioi": "IOI 赛制",
}


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    """SQLite 读回 naive datetime，统一按 UTC 处理（Postgres 返回 aware）。"""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _user_rank_dict(p: ContestParticipant) -> dict[str, Any]:
    u = p.user
    return {
        "user_id": p.user_id,
        "username": u.username if u else "未知",
        "avatar_url": (u.avatar_url or "") if u else "",
        "user_tag": (u.display_tag if u else "") if u else "",
        "username_color": (u.username_color or "") if u else "",
        "is_admin": bool(u.is_admin) if u else False,
        "is_super_admin": bool(u.is_super_admin) if u else False,
        "is_big_admin": bool(getattr(u, "is_big_admin", False)) if u else False,
        "is_cheater": bool(u.is_cheater) if u else False,
        "can_manage_users": bool(u.can_manage_users) if u else False,
        "can_manage_posts": bool(u.can_manage_posts) if u else False,
        "can_manage_problems": bool(u.can_manage_problems) if u else False,
        "color_tier": (u.color_tier or "gray") if u else "gray",
        "name_color": (u.name_color or "") if u else "",
        "user_number": u.user_number if u else None,
    }


def _row_tiebreak(row: dict[str, Any]) -> int:
    """完全并列时的稳定次序：用户/队伍 id。

    没有它的话，`rows.sort` 是稳定排序，但输入顺序来自数据库 —— 同分同罚时的
    名次会随查询计划变化，等级分结算也就不可复现（评审阻断项）。
    """
    user = row.get("user") or {}
    team = row.get("team") or {}
    return int(user.get("user_id") or team.get("id") or 0)


async def build_rank_rows(db: AsyncSession, contest: Contest) -> dict[str, Any]:
    """按赛制算出排行榜行，返回 ``{rule_type, is_team_contest, aliases, rows}``。

    ``rows`` 里每行都已带 ``rank``（1 基），顺序就是最终名次顺序。
    """
    raw_rule = getattr(contest, "rule_type", "xcpc") or "xcpc"
    rule_type = "xcpc" if raw_rule == "acm" else raw_rule
    is_team_contest = bool(getattr(contest, "is_team_contest", False))

    cps = (await db.execute(
        select(ContestProblem).where(ContestProblem.contest_id == contest.id)
        .order_by(ContestProblem.sort_order)
    )).scalars().all()
    aliases = [
        ALIAS[cp.sort_order] if cp.sort_order < len(ALIAS) else str(cp.sort_order)
        for cp in cps
    ]

    alias_by_pid = {
        cp.problem_id: (ALIAS[cp.sort_order] if cp.sort_order < len(ALIAS) else str(cp.sort_order))
        for cp in cps
    }
    participants = (await db.execute(
        select(ContestParticipant).where(ContestParticipant.contest_id == contest.id)
        # 固定顺序：同分选手的名次不能取决于数据库返回顺序
        .order_by(ContestParticipant.user_id)
        .options(selectinload(ContestParticipant.user))
    )).scalars().unique().all()

    teams: list[ContestTeam] = []
    team_by_id: dict[int, ContestTeam] = {}
    team_members_map: dict[int, list[ContestParticipant]] = {}
    user_to_team_id: dict[int, int] = {}

    if is_team_contest:
        teams = (await db.execute(
            select(ContestTeam).where(ContestTeam.contest_id == contest.id)
            .options(joinedload(ContestTeam.leader))
            .order_by(ContestTeam.created_at.asc())
        )).scalars().all()
        for t in teams:
            team_by_id[t.id] = t
            team_members_map[t.id] = []
        for p in participants:
            if p.team_id and p.team_id in team_by_id:
                team_members_map[p.team_id].append(p)
                user_to_team_id[p.user_id] = p.team_id

    # 查询所有已评测的提交（按时序升序排好）
    subs = (await db.execute(
        select(Submission).where(
            Submission.contest_id == contest.id,
            Submission.status.notin_(["pending", "judging", "cancelled"]),
            # 虚拟参赛的成绩不进正式榜（防御：正常路径不挂 contest_id）
            Submission.virtual_contest_id.is_(None),
        ).order_by(Submission.created_at.asc(), Submission.id.asc())
    )).scalars().all()

    start = _aware(contest.start_time)
    rows = []

    if rule_type == "xcpc":
        # XCPC：通过题数降序 → 总罚时升序 → 最后 AC 时间升序
        stat: dict[tuple[int, int], dict[str, Any]] = {}
        first_solve_target_id: dict[int, int] = {}

        for sub in subs:
            if is_team_contest:
                target_id = sub.contest_team_id or user_to_team_id.get(sub.user_id)
                if not target_id or target_id not in team_by_id:
                    continue
            else:
                target_id = sub.user_id

            key = (target_id, sub.problem_id)
            if key not in stat:
                stat[key] = {"tries": 0, "ac_minutes": None, "first_ac_time": None}

            # 首次 AC 后的提交不计入罚次与罚时
            if stat[key]["ac_minutes"] is not None:
                continue

            sub_status = str(sub.status or "").lower()
            if sub_status == "accepted":
                minutes = 0
                if sub.created_at and start:
                    minutes = max(0, int((_aware(sub.created_at) - start).total_seconds() // 60))
                stat[key]["ac_minutes"] = minutes
                stat[key]["first_ac_time"] = _aware(sub.created_at) if sub.created_at else None
                if sub.problem_id not in first_solve_target_id:
                    first_solve_target_id[sub.problem_id] = target_id
            else:
                # 编译错误不罚时
                if sub_status != "compile_error":
                    stat[key]["tries"] += 1

        if is_team_contest:
            for t in teams:
                solved_count, total_penalty = 0, 0
                detail: dict[str, Any] = {}
                last_ac_time: Optional[datetime] = None

                for cp in cps:
                    alias = alias_by_pid.get(cp.problem_id, "?")
                    s = stat.get((t.id, cp.problem_id))
                    if s is None:
                        detail[alias] = {"tries": 0, "solved": False, "score": 0, "first_solved": False}
                        continue
                    if s["ac_minutes"] is not None:
                        solved_count += 1
                        p_ = 20 * s["tries"] + s["ac_minutes"]
                        total_penalty += p_
                        is_fb = (first_solve_target_id.get(cp.problem_id) == t.id)
                        detail[alias] = {
                            "tries": s["tries"],
                            "solved": True,
                            "minutes": s["ac_minutes"],
                            "penalty": p_,
                            "score": 100,
                            "first_solved": is_fb,
                        }
                        if s["first_ac_time"]:
                            if last_ac_time is None or s["first_ac_time"] > last_ac_time:
                                last_ac_time = s["first_ac_time"]
                    else:
                        detail[alias] = {
                            "tries": s["tries"],
                            "solved": False,
                            "score": 0,
                            "first_solved": False,
                        }

                rows.append({
                    "team": {
                        "id": t.id,
                        "name": t.name,
                        "leader_id": t.leader_id,
                        "members": [_user_rank_dict(mp) for mp in team_members_map.get(t.id, [])],
                    },
                    "solved": solved_count,
                    "penalty": total_penalty,
                    "total_score": solved_count * 100,
                    "last_time": last_ac_time.isoformat() if last_ac_time else None,
                    "detail": detail,
                })
        else:
            for p in participants:
                solved_count, total_penalty = 0, 0
                detail: dict[str, Any] = {}
                last_ac_time: Optional[datetime] = None

                for cp in cps:
                    alias = alias_by_pid.get(cp.problem_id, "?")
                    s = stat.get((p.user_id, cp.problem_id))
                    if s is None:
                        detail[alias] = {"tries": 0, "solved": False, "score": 0, "first_solved": False}
                        continue
                    if s["ac_minutes"] is not None:
                        solved_count += 1
                        p_ = 20 * s["tries"] + s["ac_minutes"]
                        total_penalty += p_
                        is_fb = (first_solve_target_id.get(cp.problem_id) == p.user_id)
                        detail[alias] = {
                            "tries": s["tries"],
                            "solved": True,
                            "minutes": s["ac_minutes"],
                            "penalty": p_,
                            "score": 100,
                            "first_solved": is_fb,
                        }
                        if s["first_ac_time"]:
                            if last_ac_time is None or s["first_ac_time"] > last_ac_time:
                                last_ac_time = s["first_ac_time"]
                    else:
                        detail[alias] = {
                            "tries": s["tries"],
                            "solved": False,
                            "score": 0,
                            "first_solved": False,
                        }

                rows.append({
                    "user": _user_rank_dict(p),
                    "solved": solved_count,
                    "penalty": total_penalty,
                    "total_score": solved_count * 100,
                    "last_time": last_ac_time.isoformat() if last_ac_time else None,
                    "detail": detail,
                })

        rows.sort(key=lambda r: (-r["solved"], r["penalty"], r["last_time"] or "9999-12-31",
                                 _row_tiebreak(r)))

    elif rule_type == "oi":
        # OI：每题取最高分或最后一次提交
        stat_oi: dict[tuple[int, int], dict[str, Any]] = {}
        for sub in subs:
            if is_team_contest:
                target_id = sub.contest_team_id or user_to_team_id.get(sub.user_id)
                if not target_id or target_id not in team_by_id:
                    continue
            else:
                target_id = sub.user_id

            key = (target_id, sub.problem_id)
            if key not in stat_oi:
                stat_oi[key] = {"last_score": 0, "tries": 0, "last_time": None}
            stat_oi[key]["last_score"] = sub.score or 0
            stat_oi[key]["tries"] += 1
            stat_oi[key]["last_time"] = _aware(sub.created_at) if sub.created_at else None

        if is_team_contest:
            for t in teams:
                total_score, solved_count = 0, 0
                detail = {}
                last_sub_time: Optional[datetime] = None

                for cp in cps:
                    alias = alias_by_pid.get(cp.problem_id, "?")
                    s = stat_oi.get((t.id, cp.problem_id))
                    if s is None:
                        detail[alias] = {"score": 0, "solved": False, "tries": 0}
                        continue
                    score = s["last_score"]
                    total_score += score
                    is_solved = score >= 100
                    if is_solved:
                        solved_count += 1
                    detail[alias] = {"score": score, "solved": is_solved, "tries": s["tries"]}
                    if s["last_time"]:
                        if last_sub_time is None or s["last_time"] > last_sub_time:
                            last_sub_time = s["last_time"]

                rows.append({
                    "team": {
                        "id": t.id,
                        "name": t.name,
                        "leader_id": t.leader_id,
                        "members": [_user_rank_dict(mp) for mp in team_members_map.get(t.id, [])],
                    },
                    "solved": solved_count,
                    "penalty": 0,
                    "total_score": total_score,
                    "last_time": last_sub_time.isoformat() if last_sub_time else None,
                    "detail": detail,
                })
        else:
            for p in participants:
                total_score, solved_count = 0, 0
                detail = {}
                last_sub_time: Optional[datetime] = None

                for cp in cps:
                    alias = alias_by_pid.get(cp.problem_id, "?")
                    s = stat_oi.get((p.user_id, cp.problem_id))
                    if s is None:
                        detail[alias] = {"score": 0, "solved": False, "tries": 0}
                        continue
                    score = s["last_score"]
                    total_score += score
                    is_solved = score >= 100
                    if is_solved:
                        solved_count += 1
                    detail[alias] = {"score": score, "solved": is_solved, "tries": s["tries"]}
                    if s["last_time"]:
                        if last_sub_time is None or s["last_time"] > last_sub_time:
                            last_sub_time = s["last_time"]

                rows.append({
                    "user": _user_rank_dict(p),
                    "solved": solved_count,
                    "penalty": 0,
                    "total_score": total_score,
                    "last_time": last_sub_time.isoformat() if last_sub_time else None,
                    "detail": detail,
                })
        rows.sort(key=lambda r: (-r["total_score"], -r["solved"], r["last_time"] or "9999-12-31",
                                 _row_tiebreak(r)))

    else:
        # IOI：每题取最高分
        stat_ioi: dict[tuple[int, int], dict[str, Any]] = {}
        for sub in subs:
            if is_team_contest:
                target_id = sub.contest_team_id or user_to_team_id.get(sub.user_id)
                if not target_id or target_id not in team_by_id:
                    continue
            else:
                target_id = sub.user_id

            key = (target_id, sub.problem_id)
            if key not in stat_ioi:
                stat_ioi[key] = {"best_score": 0, "tries": 0, "best_time": None}
            stat_ioi[key]["tries"] += 1
            sc = sub.score or 0
            if sc > stat_ioi[key]["best_score"] or stat_ioi[key]["best_time"] is None:
                if sc > stat_ioi[key]["best_score"]:
                    stat_ioi[key]["best_score"] = sc
                stat_ioi[key]["best_time"] = _aware(sub.created_at) if sub.created_at else None

        if is_team_contest:
            for t in teams:
                total_score, solved_count = 0, 0
                detail = {}
                last_improve_time: Optional[datetime] = None

                for cp in cps:
                    alias = alias_by_pid.get(cp.problem_id, "?")
                    s = stat_ioi.get((t.id, cp.problem_id))
                    if s is None:
                        detail[alias] = {"score": 0, "solved": False, "tries": 0}
                        continue
                    score = s["best_score"]
                    total_score += score
                    is_solved = score >= 100
                    if is_solved:
                        solved_count += 1
                    detail[alias] = {"score": score, "solved": is_solved, "tries": s["tries"]}
                    if s["best_time"]:
                        if last_improve_time is None or s["best_time"] > last_improve_time:
                            last_improve_time = s["best_time"]

                rows.append({
                    "team": {
                        "id": t.id,
                        "name": t.name,
                        "leader_id": t.leader_id,
                        "members": [_user_rank_dict(mp) for mp in team_members_map.get(t.id, [])],
                    },
                    "solved": solved_count,
                    "penalty": 0,
                    "total_score": total_score,
                    "last_time": last_improve_time.isoformat() if last_improve_time else None,
                    "detail": detail,
                })
        else:
            for p in participants:
                total_score, solved_count = 0, 0
                detail = {}
                last_improve_time: Optional[datetime] = None

                for cp in cps:
                    alias = alias_by_pid.get(cp.problem_id, "?")
                    s = stat_ioi.get((p.user_id, cp.problem_id))
                    if s is None:
                        detail[alias] = {"score": 0, "solved": False, "tries": 0}
                        continue
                    score = s["best_score"]
                    total_score += score
                    is_solved = score >= 100
                    if is_solved:
                        solved_count += 1
                    detail[alias] = {"score": score, "solved": is_solved, "tries": s["tries"]}
                    if s["best_time"]:
                        if last_improve_time is None or s["best_time"] > last_improve_time:
                            last_improve_time = s["best_time"]

                rows.append({
                    "user": _user_rank_dict(p),
                    "solved": solved_count,
                    "penalty": 0,
                    "total_score": total_score,
                    "last_time": last_improve_time.isoformat() if last_improve_time else None,
                    "detail": detail,
                })
        rows.sort(key=lambda r: (-r["total_score"], -r["solved"], r["last_time"] or "9999-12-31",
                                 _row_tiebreak(r)))

    for i, r in enumerate(rows):
        r["rank"] = i + 1


    return {
        "rule_type": rule_type,
        "is_team_contest": is_team_contest,
        "aliases": aliases,
        "rows": rows,
    }
