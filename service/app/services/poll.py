"""站内投票：建 / 投 / 统计。

规则（刻意简单）：
- 任意管理员可发起（``permissions.is_any_admin``），标题 1~200 字，选项 2~10 个；
- 登录用户一人一票；多选投票一份可勾多个选项；
- **允许改票**：再次提交会整体替换自己之前的选择（单选/多选一致）；
- 截止时间可空（那就手动关）；截止或手动关闭后不能再投；
- 匿名投票不展示投票人名单，票数照常统计；
- 关闭「结束前公开票数」时，只有发起者/管理员看得到实时票数。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import permissions as perm
from app.models.poll import Poll, PollOption, PollVote
from app.models.user import User

MAX_OPTIONS = 10
MIN_OPTIONS = 2
MAX_TITLE = 200
MAX_OPTION_LEN = 200


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def is_open(poll: Poll, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if poll.closed_at is not None:
        return False
    ends = _aware(poll.ends_at)
    return ends is None or now <= ends


def can_see_results(poll: Poll, user: User | None) -> bool:
    """现在能不能看到票数。"""
    if poll.show_results_before_end:
        return True
    if not is_open(poll):
        return True
    return bool(user is not None and (user.id == poll.created_by or perm.is_any_admin(user)))


def validate_new_poll(payload: dict[str, Any], now: datetime | None = None) -> tuple[str, str, list[str], datetime | None]:
    """校验并归一化创建参数：返回 (title, description, options, ends_at)。"""
    now = now or datetime.now(timezone.utc)
    title = str(payload.get("title") or "").strip()
    if not title:
        raise ValueError("投票标题不能为空")
    if len(title) > MAX_TITLE:
        raise ValueError(f"标题不能超过 {MAX_TITLE} 字")

    description = str(payload.get("description") or "").strip() or ""

    raw_options = payload.get("options") or []
    if not isinstance(raw_options, list):
        raise ValueError("options 必须是数组")
    options: list[str] = []
    for item in raw_options:
        text = str(item or "").strip()
        if not text:
            continue
        if len(text) > MAX_OPTION_LEN:
            raise ValueError(f"选项不能超过 {MAX_OPTION_LEN} 字")
        options.append(text)
    if len(options) < MIN_OPTIONS:
        raise ValueError(f"至少需要 {MIN_OPTIONS} 个选项")
    if len(options) > MAX_OPTIONS:
        raise ValueError(f"最多 {MAX_OPTIONS} 个选项")
    if len(set(options)) != len(options):
        raise ValueError("选项不能重复")

    ends_at = None
    raw_end = payload.get("ends_at")
    if raw_end:
        try:
            ends_at = _aware(datetime.fromisoformat(str(raw_end).replace("Z", "+00:00")))
        except (TypeError, ValueError):
            raise ValueError("截止时间格式不正确")
        if ends_at is not None and ends_at <= now:
            raise ValueError("截止时间必须晚于当前时间")

    return title, description, options, ends_at


async def create_poll(db: AsyncSession, user: User, payload: dict[str, Any]) -> Poll:
    title, description, options, ends_at = validate_new_poll(payload)
    poll = Poll(
        title=title,
        description=description or None,
        allow_multiple=bool(payload.get("allow_multiple", False)),
        anonymous=bool(payload.get("anonymous", False)),
        show_results_before_end=bool(payload.get("show_results_before_end", True)),
        created_by=user.id,
        ends_at=ends_at,
    )
    poll.options = [
        PollOption(text=text, sort_order=i) for i, text in enumerate(options)
    ]
    db.add(poll)
    await db.commit()
    await db.refresh(poll)
    return poll


async def _option_ids(db: AsyncSession, poll_id: int) -> set[int]:
    rows = (await db.execute(
        select(PollOption.id).where(PollOption.poll_id == poll_id)
    )).scalars().all()
    return set(rows)


async def cast_vote(
    db: AsyncSession, poll: Poll, user: User, option_ids: list[int]
) -> None:
    """投票（整体替换自己的旧选择）。"""
    if not is_open(poll):
        raise ValueError("投票已结束")
    valid = await _option_ids(db, poll.id)
    try:
        chosen = {int(x) for x in option_ids}
    except (TypeError, ValueError):
        # 不把 Python 的 "invalid literal for int()" 甩给前端
        raise ValueError("选项 ID 格式不正确")
    if not chosen:
        raise ValueError("请至少选择一个选项")
    if not chosen <= valid:
        raise ValueError("选项不属于这个投票")
    if not poll.allow_multiple and len(chosen) > 1:
        raise ValueError("这是单选投票，只能选一个选项")

    await db.execute(delete(PollVote).where(
        PollVote.poll_id == poll.id, PollVote.user_id == user.id))
    for oid in chosen:
        db.add(PollVote(poll_id=poll.id, option_id=oid, user_id=user.id))
    await db.commit()


async def close_poll(db: AsyncSession, poll: Poll) -> None:
    """结束投票。用**条件更新**而不是「先查再改」：并发关闭时只有一个请求真的写入。"""
    from sqlalchemy import update

    await db.execute(
        update(Poll)
        .where(Poll.id == poll.id, Poll.closed_at.is_(None))
        .values(closed_at=datetime.now(timezone.utc))
    )
    await db.commit()
    await db.refresh(poll)


async def counts(db: AsyncSession, poll_id: int) -> dict[int, int]:
    rows = (await db.execute(
        select(PollVote.option_id, func.count())
        .where(PollVote.poll_id == poll_id)
        .group_by(PollVote.option_id)
    )).all()
    return {int(oid): int(n) for oid, n in rows}


async def my_votes(db: AsyncSession, poll_id: int, user_id: int) -> list[int]:
    return [
        int(x) for x in (await db.execute(
            select(PollVote.option_id).where(
                PollVote.poll_id == poll_id, PollVote.user_id == user_id)
        )).scalars().all()
    ]


async def voter_count(db: AsyncSession, poll_id: int) -> int:
    return int((await db.execute(
        select(func.count(func.distinct(PollVote.user_id)))
        .where(PollVote.poll_id == poll_id)
    )).scalar() or 0)


async def voters(db: AsyncSession, poll_id: int) -> list[dict[str, Any]]:
    """投票人名单（匿名投票不返回）。"""
    rows = (await db.execute(
        select(User)
        .join(PollVote, PollVote.user_id == User.id)
        .where(PollVote.poll_id == poll_id)
        .distinct()
        .order_by(User.user_number)
    )).scalars().all()
    return [
        {"user_number": u.user_number, "username": u.username,
         "avatar_url": u.avatar_url or ""}
        for u in rows
    ]


def _build_payload(
    poll: Poll,
    user: User | None,
    tally: dict[int, int],
    mine: list[int],
    voter_count: int,
    voters: list[dict[str, Any]],
) -> dict[str, Any]:
    show = can_see_results(poll, user)
    total = sum(tally.values())
    options = []
    for opt in poll.options:
        n = tally.get(opt.id, 0)
        options.append({
            "id": opt.id,
            "text": opt.text,
            "votes": n if show else None,
            "percent": round(n * 100 / total, 1) if (show and total) else (0.0 if show else None),
        })
    return {
        "id": poll.id,
        "title": poll.title,
        "description": poll.description or "",
        "allow_multiple": poll.allow_multiple,
        "anonymous": poll.anonymous,
        "show_results_before_end": poll.show_results_before_end,
        "created_by": poll.created_by,
        "created_at": _aware(poll.created_at).isoformat() if poll.created_at else None,
        "ends_at": _aware(poll.ends_at).isoformat() if poll.ends_at else None,
        "closed_at": _aware(poll.closed_at).isoformat() if poll.closed_at else None,
        "open": is_open(poll),
        "results_visible": show,
        "options": options,
        "total_votes": total if show else None,
        "voter_count": voter_count,
        "my_votes": mine,
        "voters": voters,
    }


async def poll_payload(
    db: AsyncSession, poll: Poll, user: User | None
) -> dict[str, Any]:
    """详情用：单个投票的完整 payload（含投票人名单）。"""
    show = can_see_results(poll, user)
    tally = await counts(db, poll.id) if show else {}
    mine = await my_votes(db, poll.id, user.id) if user is not None else []
    return _build_payload(
        poll, user, tally, mine,
        await voter_count(db, poll.id),
        (await voters(db, poll.id)) if (show and not poll.anonymous) else [],
    )


async def list_payloads(
    db: AsyncSession, polls: list[Poll], user: User | None
) -> list[dict[str, Any]]:
    """列表用：票数/我的投票/参与人数**各一条**查询算完，不再 5N 次往返。

    列表不返回投票人名单（人一多就是几百个名字），详情里才有。
    """
    if not polls:
        return []
    ids = [p.id for p in polls]

    rows = (await db.execute(
        select(PollVote.poll_id, PollVote.option_id, func.count())
        .where(PollVote.poll_id.in_(ids))
        .group_by(PollVote.poll_id, PollVote.option_id)
    )).all()
    tallies: dict[int, dict[int, int]] = {}
    for pid, oid, n in rows:
        tallies.setdefault(int(pid), {})[int(oid)] = int(n)

    voter_counts = {
        int(pid): int(n) for pid, n in (await db.execute(
            select(PollVote.poll_id, func.count(func.distinct(PollVote.user_id)))
            .where(PollVote.poll_id.in_(ids))
            .group_by(PollVote.poll_id)
        )).all()
    }

    mines: dict[int, list[int]] = {}
    if user is not None:
        for pid, oid in (await db.execute(
            select(PollVote.poll_id, PollVote.option_id)
            .where(PollVote.poll_id.in_(ids), PollVote.user_id == user.id)
        )).all():
            mines.setdefault(int(pid), []).append(int(oid))

    return [
        _build_payload(
            p, user, tallies.get(p.id, {}), mines.get(p.id, []),
            voter_counts.get(p.id, 0), [],
        )
        for p in polls
    ]
