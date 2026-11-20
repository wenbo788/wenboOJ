"""虚拟参赛（virtual contest）业务逻辑。

把一场**已结束**的比赛镜像出来自己再打一遍：

- 时长照抄原比赛（``end_time - start_time``），从点「开始」那一刻算；
- 提交带 ``contest_id`` 但**另带** ``virtual_contest_id``：原赛榜与等级分结算
  都按这个字段过滤掉，所以不会污染真实成绩；
- 同一用户同一场比赛**同时只能有一个进行中的虚拟赛**（到期/手动结束后可以再来）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contest import Contest
from app.models.submission import Submission
from app.models.virtual_contest import VirtualContest

# 原比赛时长至少按 10 分钟算（防止极端数据导致一开就结束）
MIN_DURATION = timedelta(minutes=10)
# 虚拟赛时长上限 12 小时（原比赛数据异常时不至于挂一天）
MAX_DURATION = timedelta(hours=12)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def is_finished(vc: VirtualContest, now: datetime | None = None) -> bool:
    """是否已经结束（手动结束或到点）。"""
    now = now or datetime.now(timezone.utc)
    if vc.finished_at is not None:
        return True
    ends = _aware(vc.ends_at)
    return bool(ends and now > ends)


def remaining_seconds(vc: VirtualContest, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    if is_finished(vc, now):
        return 0
    ends = _aware(vc.ends_at)
    return max(0, int((ends - now).total_seconds())) if ends else 0


async def get_active_virtual(
    db: AsyncSession, user_id: int, contest_id: int, *, persist_expiry: bool = False
) -> VirtualContest | None:
    """该用户在这场比赛中「进行中」的虚拟赛。

    **默认只读**（``persist_expiry=False``）：GET 接口不该有写库副作用，
    到期了就直接返回 None，``finished_at`` 由写路径（start/finish）补。
    """
    vc = (await db.execute(
        select(VirtualContest)
        .where(
            VirtualContest.user_id == user_id,
            VirtualContest.source_contest_id == contest_id,
            VirtualContest.finished_at.is_(None),
        )
        .order_by(VirtualContest.id.desc())
    )).scalars().first()
    if vc is None:
        return None
    if is_finished(vc):
        if persist_expiry:
            # 写路径（start/finish）顺手收尾，避免历史行一直挂着 finished_at IS NULL
            vc.finished_at = _aware(vc.ends_at)
            try:
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        return None
    return vc


def validate_startable(contest: Contest, now: datetime | None = None) -> tuple[bool, str]:
    """这场能不能开虚拟赛：返回 (能否, 不能的原因)。"""
    now = now or datetime.now(timezone.utc)
    if getattr(contest, "is_team_contest", False):
        return False, "组队赛暂不支持虚拟参赛"
    # 只允许公开比赛：私有/团队赛的题目可见性本来就是受限的，而虚拟赛这条
    # 通道会绕过「报名」校验，等于让任何登录用户直接提交私有赛题（越权）。
    if (getattr(contest, "visibility", "public") or "public") != "public":
        return False, "只有公开比赛支持虚拟参赛"
    end = _aware(contest.end_time)
    if end and now <= end:
        return False, "比赛还没结束，结束后才能虚拟参赛"
    return True, ""


async def start(
    db: AsyncSession, contest: Contest, user_id: int, now: datetime | None = None
) -> VirtualContest:
    now = now or datetime.now(timezone.utc)
    # 写路径：顺手把到期的旧行收尾
    existing = await get_active_virtual(db, user_id, contest.id, persist_expiry=True)
    if existing is not None:
        return existing

    start_at = _aware(contest.start_time)
    end_at = _aware(contest.end_time)
    duration = (end_at - start_at) if (start_at and end_at) else MAX_DURATION
    duration = min(max(duration, MIN_DURATION), MAX_DURATION)

    vc = VirtualContest(
        user_id=user_id,
        source_contest_id=contest.id,
        started_at=now,
        ends_at=now + duration,
    )
    db.add(vc)
    try:
        await db.commit()
    except IntegrityError:
        # 并发 start：部分唯一索引（uq_virtual_active）挡下第二个请求。
        # 回滚后把已存在的那一条返回给调用方，别给用户一个 500。
        await db.rollback()
        again = await get_active_virtual(db, user_id, contest.id)
        if again is not None:
            return again
        raise
    await db.refresh(vc)
    return vc


async def finish(db: AsyncSession, vc: VirtualContest) -> VirtualContest:
    if vc.finished_at is None:
        vc.finished_at = datetime.now(timezone.utc)
        try:
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    return vc


def to_dict(vc: VirtualContest, now: datetime | None = None) -> dict:
    return {
        "id": vc.id,
        "source_contest_id": vc.source_contest_id,
        "started_at": _aware(vc.started_at).isoformat() if vc.started_at else None,
        "ends_at": _aware(vc.ends_at).isoformat() if vc.ends_at else None,
        "finished_at": _aware(vc.finished_at).isoformat() if vc.finished_at else None,
        "active": not is_finished(vc, now),
        "remaining_seconds": remaining_seconds(vc, now),
    }


async def results(
    db: AsyncSession, user_id: int, virtual_id: int, problem_ids: list[int]
) -> list[dict]:
    """**这一轮**虚拟赛的成绩汇总（按题：是否通过 / 最高分 / 提交次数）。

    必须按 ``virtual_id`` 精确过滤：把历史的每一轮都算进来会让「提前结束 →
    再开一轮」继承上一轮的成绩（评审指出的阻断项）。
    """
    subs = (await db.execute(
        select(Submission)
        .where(
            Submission.user_id == user_id,
            Submission.virtual_contest_id == virtual_id,
        )
        .order_by(Submission.id)
    )).scalars().all()

    by_problem: dict[int, dict] = {
        pid: {"problem_id": pid, "solved": False, "best_score": 0,
              "attempts": 0, "first_ac_at": None}
        for pid in problem_ids
    }
    for s in subs:
        item = by_problem.get(s.problem_id)
        if item is None:
            continue
        item["attempts"] += 1
        item["best_score"] = max(item["best_score"], int(s.score or 0))
        if str(s.status or "").lower() == "accepted":
            item["solved"] = True
            if item["first_ac_at"] is None and s.created_at is not None:
                item["first_ac_at"] = _aware(s.created_at).isoformat()
    return list(by_problem.values())
