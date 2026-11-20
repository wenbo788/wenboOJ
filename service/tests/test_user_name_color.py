"""用户名显示色必须全站一致（Bug：个人主页名字颜色与其它地方不符）。

根因回顾：公开资料接口（``PublicUserOut``）**刻意不下发 can_manage_* 管理标志**
（隐私），而前端 ``userNameColor()`` 恰恰靠这些标志判题管（青 #13C2C2）/社管
（深蓝 #0D47A1）——于是这些人在个人主页被显示成购买档位色，与犇犇 / 私信 /
管理名单里的颜色对不上。

修法：后端用 ``permissions.user_name_color`` 算好（模型 ``User.name_color``），
各接口随 payload 下发；前端优先用它。这里钉住三件事：

1. 优先级链与前端严格同序（身份 > 作弊/封禁 > 自定义色 > 购买档位）
2. 个人主页与管理名单给出的颜色**完全一致**（同一个人的名字只有一种颜色）
3. 公开资料接口**仍然不泄露** can_manage_* —— 修颜色不能顺手把隐私口径破坏掉
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app import permissions as perm
from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.user import User


class _FakeUser:
    """只喂 user_name_color 需要的字段。"""

    def __init__(self, **kw):
        self.user_number = kw.get("user_number", 999)
        self.is_super_admin = kw.get("is_super_admin", False)
        self.is_big_admin = kw.get("is_big_admin", False)
        self.can_manage_problems = kw.get("can_manage_problems", False)
        self.can_manage_posts = kw.get("can_manage_posts", False)
        self.is_cheater = kw.get("is_cheater", False)
        self.is_banned = kw.get("is_banned", False)
        self.username_color = kw.get("username_color")
        self.color_tier = kw.get("color_tier", "gray")


def test_priority_chain_matches_frontend():
    """优先级链：与 web/src/utils/userColor.ts 的注释/实现逐条对齐。"""
    assert perm.user_name_color(None) == perm.COLOR_DEFAULT
    assert perm.user_name_color(_FakeUser(color_tier="blue")) == "#1890ff"
    # 白名单 / 超管 / 大管统一紫色（金色已回退，别再退回三套颜色）
    assert perm.COLOR_WHITE_LIST == perm.COLOR_SUPER_ADMIN == perm.COLOR_BIG_ADMIN == "#9C3DCF"
    # 身份色优先于自定义色与购买档位色
    assert perm.user_name_color(_FakeUser(user_number=210, color_tier="red")) == "#9C3DCF"
    assert perm.user_name_color(_FakeUser(is_super_admin=True)) == "#9C3DCF"
    assert perm.user_name_color(_FakeUser(is_big_admin=True)) == "#9C3DCF"
    assert perm.user_name_color(_FakeUser(can_manage_problems=True)) == perm.COLOR_PROBLEM_ADMIN
    assert perm.user_name_color(_FakeUser(can_manage_posts=True)) == perm.COLOR_COMMUNITY_ADMIN
    assert (
        perm.user_name_color(_FakeUser(can_manage_problems=True, username_color="#123456"))
        == perm.COLOR_PROBLEM_ADMIN
    )
    # 作弊者 / 封禁在身份之下、自定义与档位之上
    assert perm.user_name_color(_FakeUser(is_cheater=True, color_tier="red")) == perm.COLOR_CHEATER
    assert perm.user_name_color(_FakeUser(is_banned=True, username_color="#123456")) == perm.COLOR_BANNED
    # 普通用户：自定义色优先于购买档位色
    assert perm.user_name_color(_FakeUser(username_color="#123456", color_tier="red")) == "#123456"
    assert perm.user_name_color(_FakeUser(color_tier="unknown")) == perm.COLOR_DEFAULT


async def _register(ac: AsyncClient, prefix: str) -> tuple[str, int]:
    name = f"{prefix}_{uuid.uuid4().hex[:8]}"
    r = await ac.post("/users", json={
        "username": name, "email": f"{name}@example.com", "password": "supersecret1"})
    assert r.status_code == 201, r.text
    r = await ac.get(f"/users/by-username/{name}")
    assert r.status_code == 200, r.text
    return name, r.json()["id"]


async def _fresh_numbers(count: int) -> list[int]:
    """取几个当前没被占用的 user_number。

    写死编号会踩两个坑：自增编号会撞白名单 {1,3,4,68,165,210}（那样所有人都
    变成白名单金），写死的「安全段」又可能和别的测试撞唯一约束。这里从现有
    最大值往上取，且保证 ≥ 1000（必然不在白名单里）。
    """
    async with AsyncSessionLocal() as db:
        cur = (await db.execute(select(func.max(User.user_number)))).scalar() or 0
    base = max(int(cur), 1000) + 10
    return [base + i for i in range(count)]


async def _set_role(user_id: int, **fields) -> None:
    async with AsyncSessionLocal() as db:
        u = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
        for k, v in fields.items():
            setattr(u, k, v)
        await db.commit()


@pytest.mark.asyncio
async def test_profile_color_matches_roster_and_stays_private():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        problem_admin, pid = await _register(ac, "color_pa")
        community_admin, cid = await _register(ac, "color_ca")
        big_admin, bid = await _register(ac, "color_ba")
        plain, plid = await _register(ac, "color_plain")

        nums = await _fresh_numbers(4)
        await _set_role(pid, can_manage_problems=True, user_number=nums[0])
        await _set_role(cid, can_manage_posts=True, user_number=nums[1])
        await _set_role(bid, is_big_admin=True, user_number=nums[2])
        await _set_role(plid, color_tier="green", user_number=nums[3])

        # ① 个人主页（公开资料接口）给的颜色
        profiles = {}
        for name in (problem_admin, community_admin, big_admin, plain):
            r = await ac.get(f"/users/by-username/{name}")
            assert r.status_code == 200, r.text
            profiles[name] = r.json()

        assert profiles[problem_admin]["name_color"] == perm.COLOR_PROBLEM_ADMIN
        assert profiles[community_admin]["name_color"] == perm.COLOR_COMMUNITY_ADMIN
        assert profiles[big_admin]["name_color"] == perm.COLOR_BIG_ADMIN == "#9C3DCF"
        assert profiles[plain]["name_color"] == "#52c41a"

        # ② 隐私口径不能因为这次修复被破坏：公开资料仍不下发管理标志
        leaked = [k for k in profiles[problem_admin] if k.startswith("can_manage")]
        assert leaked == [], f"公开资料不应下发管理标志: {leaked}"

        # ③ 与「管理名单」这个公开参考面给出的颜色完全一致（同一个名字只有一种颜色）
        roster = (await ac.get("/judgement/admins")).json()["admins"]
        by_name = {a["username"]: a for a in roster}
        for name in (problem_admin, community_admin, big_admin):
            assert name in by_name, f"{name} 应出现在管理名单里"
            assert by_name[name]["name_color"] == profiles[name]["name_color"], (
                f"{name} 在管理名单与个人主页的颜色不一致："
                f"{by_name[name]['name_color']} vs {profiles[name]['name_color']}"
            )
