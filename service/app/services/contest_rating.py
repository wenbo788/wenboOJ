"""比赛等级分（rating）结算。

规则（简化版 Elo，思路同 Codeforces 的「预期名次」）：

1. 每场结算赛取**名次**（由现有的比赛排行榜算法得出，不在这里重算分制）；
2. 对第 i 名：
   - 预期胜率 ``expected_i = Σ_j 1 / (1 + 10 ** ((r_j - r_i) / 400))``
     （即「理论上能排在多少人前面」）
   - 实际得分 ``actual_i = (N - rank_i) / (N - 1)``，第一名 1、最后一名 0
   - ``delta = round(K * (actual_i - expected_i / (N - 1)))``
3. K 按「已结算场次」衰减：<5 场 40（新手分动得快）、<10 场 30、其余 20；
4. 下限 100 分，不设上限。

刻意做得很朴素：
- **不回填历史** —— 只有本规则上线后结算的比赛才计入；
- 只支持**个人赛**（组队赛按队伍还是按个人算歧义太大，MVP 不做）；
- 只结算 `is_rated=True` 且**已结束**的比赛，且每人每场只结算一次。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contest import Contest
from app.models.contest_rating import ContestRating
from app.models.submission import Submission
from app.models.user import User

START_RATING = 1500
MIN_RATING = 100


def k_factor(rated_contests: int) -> int:
    """K 系数：场次越少，分数波动越大。"""
    if rated_contests < 5:
        return 40
    if rated_contests < 10:
        return 30
    return 20


def expected_scores(ratings: list[int]) -> list[float]:
    """每个人的「预期排在前面的人数」（和为 N 的近似）。"""
    out: list[float] = []
    for i, r in enumerate(ratings):
        total = 0.0
        for j, other in enumerate(ratings):
            if i == j:
                continue
            total += 1.0 / (1.0 + 10 ** ((other - r) / 400.0))
        out.append(total)
    return out


def rating_deltas(ratings: list[int], ranks: list[int], rated_counts: list[int]) -> list[int]:
    """给定（按名次排好序的）评分、名次、场次，返回每人的 delta。

    ``rank`` 为 1 基名次；同分同名次的情况由调用方决定（这里按传入顺序）。
    """
    n = len(ratings)
    if n < 2:
        return [0] * n
    exp = expected_scores(ratings)
    deltas: list[int] = []
    for i in range(n):
        expected_ratio = exp[i] / (n - 1)
        actual = (n - ranks[i]) / (n - 1)
        k = k_factor(rated_counts[i])
        deltas.append(round(k * (actual - expected_ratio)))
    return deltas


@dataclass
class RatingRow:
    user_id: int
    rank: int
    before: int
    after: int
    delta: int
    rated_contests_before: int


async def settle_contest(db: AsyncSession, contest: Contest) -> list[RatingRow]:
    """结算一场比赛：算名次（走 contest_rank.build_rank_rows）→ 算分 → 落库。

    只结算「至少提交过一次」的人（报名了没交不扣分），名次在这些人里重排。
    """
    from app.services.contest_rank import build_rank_rows

    ok, reason = is_settleable(contest)
    if not ok:
        raise ValueError(reason)

    # 还有提交在评测中 → 名次随时会变，而结算幂等、写进去改不回来
    from sqlalchemy import func as sa_func

    pending = (await db.execute(
        select(sa_func.count()).select_from(Submission).where(
            Submission.contest_id == contest.id,
            Submission.status.in_(["pending", "judging"]),
        )
    )).scalar() or 0
    if pending:
        raise ValueError(f"还有 {pending} 份提交在评测中，等评测结束再结算")

    data = await build_rank_rows(db, contest)
    rows = data.get("rows") or []

    submitted = set((await db.execute(
        select(Submission.user_id)
        .where(
            Submission.contest_id == contest.id,
            Submission.status.notin_(["pending", "judging", "cancelled"]),
            # 虚拟参赛不是正式参赛，不参与结算（防御）
            Submission.virtual_contest_id.is_(None),
        )
        .distinct()
    )).scalars().all())

    ordered: list[int] = []
    for row in rows:
        user = row.get("user") or {}
        uid = user.get("user_id")
        if uid and uid in submitted:
            ordered.append(int(uid))
    if len(ordered) < 2:
        raise ValueError("参赛人数少于 2 人，不结算等级分")

    return await apply_rating(db, contest, ordered)


async def apply_rating(
    db: AsyncSession,
    contest: Contest,
    ordered_user_ids: list[int],
) -> list[RatingRow]:
    """按名次结算一场比赛，写历史并更新 users 上的当前分。

    ``ordered_user_ids``：按名次从第 1 名到最后的 user_id 列表（调用方负责
    用既有的排行榜算法算好名次）。
    """
    if len(ordered_user_ids) < 2:
        raise ValueError("参赛人数少于 2 人，不结算等级分")

    # with_for_update：并发结算时锁住这些用户行，避免两个请求各读到旧分、
    # 各自 +delta 又把对方的写覆盖掉（Postgres 生效；SQLite 方言会忽略）。
    users = {
        u.id: u
        for u in (await db.execute(
            select(User).where(User.id.in_(ordered_user_ids)).with_for_update()
        )).scalars().all()
    }
    missing = [uid for uid in ordered_user_ids if uid not in users]
    if missing:
        raise ValueError(f"参赛者不存在: {missing}")

    ratings = [users[uid].rating for uid in ordered_user_ids]
    counts = [users[uid].rated_contests for uid in ordered_user_ids]
    ranks = list(range(1, len(ordered_user_ids) + 1))
    deltas = rating_deltas(ratings, ranks, counts)

    rows: list[RatingRow] = []
    for idx, uid in enumerate(ordered_user_ids):
        u = users[uid]
        before = u.rating
        after = max(MIN_RATING, before + deltas[idx])
        rows.append(RatingRow(
            user_id=uid, rank=ranks[idx], before=before,
            after=after, delta=after - before,
            rated_contests_before=u.rated_contests,
        ))
        u.rating = after
        u.max_rating = max(u.max_rating, after)
        u.rated_contests = u.rated_contests + 1
        db.add(ContestRating(
            contest_id=contest.id, user_id=uid, rank=ranks[idx],
            participants=len(ordered_user_ids),
            rating_before=before, rating_after=after, delta=after - before,
            rated_contests_before=rows[-1].rated_contests_before,
        ))

    await db.commit()
    return rows


async def get_contest_rating(db: AsyncSession, contest_id: int) -> list[dict[str, Any]]:
    """读取一场比赛已结算的等级分变化（含昵称，用于展示）。

    显式 join User：不用关系属性，免得在 async 会话里点出懒加载。
    """
    stmt = (
        select(ContestRating, User)
        .join(User, User.id == ContestRating.user_id)
        .where(ContestRating.contest_id == contest_id)
        .order_by(ContestRating.rank)
    )
    pairs = (await db.execute(stmt)).all()
    return [
        {
            "user_id": r.user_id,
            "user_number": u.user_number,
            "username": u.username,
            "rank": r.rank,
            "participants": r.participants,
            "rating_before": r.rating_before,
            "rating_after": r.rating_after,
            "delta": r.delta,
        }
        for r, u in pairs
    ]


def is_settleable(contest: Contest, now: datetime | None = None) -> tuple[bool, str]:
    """这场比赛现在能不能结算：返回 (能否, 不能的原因)。"""
    now = now or datetime.now(timezone.utc)
    end = contest.end_time
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if not getattr(contest, "is_rated", False):
        return False, "这场比赛没有勾选「计入等级分」"
    if getattr(contest, "is_team_contest", False):
        return False, "组队赛暂不支持等级分结算"
    if now <= end:
        return False, "比赛还没结束"
    return True, ""
