from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contest import Contest
from app.models.team import Team, TeamMember
from app.models.user import User


async def is_contest_organizer(
    db: AsyncSession, contest: Contest, user: Optional[User]
) -> bool:
    """判断当前用户是否为比赛举办方：
    - 个人赛（举办个人）：比赛创建者本人（contest.owner_id == user.id）
    - 团队赛（举办团队）：比赛所属团队的所有人（包含团主与全部团队成员）
    """
    if user is None:
        return False
    # 举办个人（比赛创建者）
    if contest.owner_id == user.id:
        return True
    # 举办团队：团主与所有团队成员
    if contest.team_id is not None:
        team_owner_id = (await db.execute(
            select(Team.owner_id).where(Team.id == contest.team_id)
        )).scalar_one_or_none()
        if team_owner_id == user.id:
            return True
        is_member = (await db.execute(
            select(TeamMember.id).where(
                TeamMember.team_id == contest.team_id,
                TeamMember.user_id == user.id,
            )
        )).scalar_one_or_none() is not None
        if is_member:
            return True
    return False


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


async def get_shielded_contest_for_problem(
    db: AsyncSession, problem_id: int, user: Optional[User]
) -> Optional[Contest]:
    """若题目属于某场【未结束且开启了管理员参赛保护】的比赛，且当前用户【不是举办方】，
    则返回该比赛（表示对当前用户激活参赛保护，收回对该题的管理员特权）。
    """
    if user is None:
        return None
    now = datetime.now(timezone.utc)
    from app.models.contest import ContestProblem

    rows = (await db.execute(
        select(Contest)
        .join(ContestProblem, ContestProblem.contest_id == Contest.id)
        .where(ContestProblem.problem_id == problem_id)
    )).scalars().all()

    for c in rows:
        end = _aware(c.end_time)
        if end is not None and end >= now and getattr(c, "hide_submissions_from_admin", False):
            if not await is_contest_organizer(db, c, user):
                return c
    return None


async def is_team_organizing_shielded_contest(
    db: AsyncSession, team_id: int, user: Optional[User]
) -> bool:
    """该团队是否有【未结束且开启了管理员参赛保护】的比赛，且当前用户【不是举办方】。
    
    若为 True，非举办方的管理员访问该团队时不应凭借全站管理员身份穿透获取团队私有题。
    """
    if user is None:
        return False
    now = datetime.now(timezone.utc)
    contests = (await db.execute(
        select(Contest).where(
            Contest.team_id == team_id,
            Contest.hide_submissions_from_admin == True,
        )
    )).scalars().all()

    for c in contests:
        end = _aware(c.end_time)
        if end is not None and end >= now:
            if not await is_contest_organizer(db, c, user):
                return True
    return False


async def get_unstarted_contest_for_problem(
    db: AsyncSession, problem_id: int, user: Optional[User]
) -> Optional[Contest]:
    """若题目属于某场尚未开赛的比赛，且当前用户不是该比赛举办方，则返回该比赛。
    
    用于在团队题目列表中向非举办方隐藏尚未开赛的赛题，防止赛前看题。
    """
    now = datetime.now(timezone.utc)
    from app.models.contest import ContestProblem

    rows = (await db.execute(
        select(Contest)
        .join(ContestProblem, ContestProblem.contest_id == Contest.id)
        .where(ContestProblem.problem_id == problem_id)
    )).scalars().all()

    for c in rows:
        st = _aware(c.start_time)
        en = _aware(c.end_time)
        if st is not None and en is not None and now < st <= en:
            if not await is_contest_organizer(db, c, user):
                return c
    return None
