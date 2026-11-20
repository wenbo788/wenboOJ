"""管理名单与陶片鉴权回归：名单口径必须与权限真源一致。

背景：名单曾只按 users 表的 can_manage_* 裸字段筛人，导致白名单 UID /
is_super_admin / is_big_admin 因字段为 false 而**不显示**（他们实际有权限）。
现在名单与陶片鉴权都走 ``app.permissions`` 的真源函数：

- 真源口径为「白名单 / 超管 / 大管 / 对应字段持有者」；
- 名单四列返回的是**有效权限**，前端据此分列；
- 陶片删除（DELETE /judgement/logs/{id}）此前判裸字段 can_manage_posts，
  超管 / 白名单会被 403，现改为 can_manage_community。
"""

import itertools
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.judgement import JudgementLog
from app.models.user import User

# 高位 UID 递增分配器：随机数在 900000..999999 空间里随着注册次数增多会撞号
# （UNIQUE 约束），改为递增计数器 + 占用检查。pytest 串行执行，无并发顾虑。
_uid_seq = itertools.count(900000)


async def _next_high_uid(db, used: set[int] | None = None) -> int:
    """返回一个当前未被占用的高位 UID。

    ``used`` 可传入「已占用编号」快照供批量分配时复用，避免逐次全表查询
    （``_evict_uid`` 可能需要一次腾出多个号位）。分配出去的号位会立即记入
    该集合，保证同一批内不会重复分配。
    """
    if used is None:
        used = set((await db.execute(select(User.user_number))).scalars())
    while True:
        candidate = next(_uid_seq)
        if candidate not in used:
            used.add(candidate)
            return candidate


async def _register(ac: AsyncClient, name: str) -> None:
    r = await ac.post("/users", json={
        "username": name, "email": f"{name}@example.com", "password": "supersecret1"})
    assert r.status_code == 201, r.text


async def _login(ac: AsyncClient, name: str) -> dict:
    r = await ac.post("/tokens", data={"username": name, "password": "supersecret1"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _move_uid_high(name: str) -> None:
    """挪到高位，避开白名单 UID，避免误成白名单。"""
    async with AsyncSessionLocal() as db:
        u = (await db.execute(select(User).where(User.username == name))).scalar_one()
        u.user_number = await _next_high_uid(db)
        await db.commit()


async def _evict_uid(uid: int) -> None:
    """把占用指定 user_number 的用户全部挪走，腾出白名单号位。

    conftest 的新库里首个注册用户默认 user_number=1（白名单号位），
    直接把自己的测试用户改成 1 会撞 UNIQUE 约束，故先腾位。
    """
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(User).where(User.user_number == uid))).scalars().all()
        if not rows:
            return
        # 一次取出已占用编号快照，循环内复用，避免逐个分配时反复全表查询
        used = set((await db.execute(select(User.user_number))).scalars())
        for u in rows:
            u.user_number = await _next_high_uid(db, used)
        await db.commit()


async def _patch(name: str, **fields) -> int:
    """直改用户字段，返回其主键 id。"""
    async with AsyncSessionLocal() as db:
        u = (await db.execute(select(User).where(User.username == name))).scalar_one()
        for k, v in fields.items():
            setattr(u, k, v)
        await db.commit()
        return u.id


async def _add_judgement_log(admin_id: int, target_id: int) -> int:
    async with AsyncSessionLocal() as db:
        log = JudgementLog(admin_id=admin_id, target_user_id=target_id,
                           action_type="ban", action_detail={}, reason="测试")
        db.add(log)
        await db.commit()
        return log.id


def _find(admins: list, name: str) -> dict | None:
    """按用户名精确匹配（集合式匹配，不依赖列表顺序/首元素位置）。

    测试库是 session 级共享的，可能残留其他用例造的管理员；用户名全局唯一，
    故按名字过滤后最多一条。若出现多条说明断言前提被破坏，直接暴露出来。
    """
    found = [a for a in admins if a["username"] == name]
    assert len(found) <= 1, f"用户名重复匹配：{name} -> {found}"
    return found[0] if found else None


def _unique_ip_headers() -> dict:
    """给请求注入唯一 X-Real-IP：限流桶按 IP 隔离，避免跨用例串扰。"""
    return {"X-Real-IP": f"203.0.113.{uuid.uuid4().int % 254 + 1}"}


@pytest.mark.asyncio
async def test_admin_list_follows_permission_source():
    """名单须包含白名单/超管/大管，并按真源分列；Tag 列只认白名单/超管。"""
    sfx = uuid.uuid4().hex[:6]
    plain = f"pl_{sfx}"
    white = f"wl_{sfx}"
    sup = f"sup_{sfx}"
    big = f"big_{sfx}"
    comm = f"comm_{sfx}"
    prob = f"prob_{sfx}"
    fake_tag = f"ftag_{sfx}"
    admin_only = f"admonly_{sfx}"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        for n in (plain, white, sup, big, comm, prob, fake_tag, admin_only):
            await _register(ac, n)
            await _move_uid_high(n)

        # 白名单：先腾出号位 1，再把自己的用户设进去
        await _evict_uid(1)
        await _patch(white, user_number=1)
        await _patch(sup, is_super_admin=True)
        await _patch(big, is_big_admin=True)
        await _patch(comm, can_manage_posts=True)
        await _patch(prob, can_manage_problems=True)
        await _patch(fake_tag, can_manage_tags=True)
        # 仅 is_admin=True（泛管理员）：四列皆 false，但能进后台调管理接口，
        # 名单过滤口径必须与 perm.is_any_admin 对齐，不能把他剔除
        await _patch(admin_only, is_admin=True)

        r = await ac.get("/judgement/admins", headers=_unique_ip_headers())
        assert r.status_code == 200, r.text
        admins = r.json()["admins"]

        # 普通用户不在名单
        assert _find(admins, plain) is None

        # 只置 can_manage_tags 字段的用户：真源认该字段（字段仅白名单可授予），
        # 故应出现在名单，且只落在 Tag 管理列
        a = _find(admins, fake_tag)
        assert a is not None, "持有 can_manage_tags 字段的用户应在名单中"
        assert a["can_manage_tags"] is True
        assert a["can_manage_users"] is False
        assert a["can_manage_posts"] is False
        assert a["can_manage_problems"] is False

        # 白名单 / 超管：四列都有权限
        for n, label in ((white, "白名单"), (sup, "超管")):
            a = _find(admins, n)
            assert a is not None, f"{label} {n} 未出现在名单中"
            assert all((a["can_manage_users"], a["can_manage_posts"],
                        a["can_manage_problems"], a["can_manage_tags"])), \
                f"{label} 应四列均有权限：{a}"

        # 大管：有用户管理权限
        a = _find(admins, big)
        assert a is not None, "大管未出现在名单中"
        assert a["can_manage_users"] is True
        assert a["is_big_admin"] is True

        # 社管：只有秩序管理列
        a = _find(admins, comm)
        assert a is not None
        assert a["can_manage_posts"] is True
        assert a["can_manage_users"] is False
        assert a["can_manage_problems"] is False
        assert a["can_manage_tags"] is False

        # 题管：只有题目管理列
        a = _find(admins, prob)
        assert a is not None
        assert a["can_manage_problems"] is True
        assert a["can_manage_posts"] is False
        assert a["can_manage_tags"] is False

        # 名单按用户编号升序
        nums = [x["user_number"] for x in admins]
        assert nums == sorted(nums)

        # 白名单标记正确
        assert _find(admins, white)["is_whitelist"] is True

        # 仅 is_admin 的泛管理员仍然在名单中（过滤口径 = perm.is_any_admin）
        a = _find(admins, admin_only)
        assert a is not None, "仅 is_admin=True 的用户不应从公示名单中消失"
        assert a["is_admin"] is True


@pytest.mark.asyncio
async def test_judgement_log_delete_uses_permission_source():
    """超管/白名单即使 can_manage_posts=false 也能删陶片；普通用户 403。"""
    sfx = uuid.uuid4().hex[:6]
    sup = f"dsup_{sfx}"
    normal = f"dnorm_{sfx}"
    target = f"dtgt_{sfx}"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        for n in (sup, normal, target):
            await _register(ac, n)
            await _move_uid_high(n)
        sup_id = await _patch(sup, is_super_admin=True, can_manage_posts=False)
        target_id = await _patch(target, can_manage_posts=False)
        await _patch(normal, can_manage_posts=False)

        sh = await _login(ac, sup)
        nh = await _login(ac, normal)

        # 列表的 can_manage 走真源：超管为 true，普通用户 false
        r = await ac.get("/judgement/logs", headers=sh)
        assert r.status_code == 200, r.text
        assert r.json()["can_manage"] is True
        r = await ac.get("/judgement/logs", headers=nh)
        assert r.json()["can_manage"] is False

        # 普通用户删除被拒
        log_a = await _add_judgement_log(sup_id, target_id)
        r = await ac.delete(f"/judgement/logs/{log_a}", headers=nh)
        assert r.status_code == 403, r.text

        # 超管删除成功（此前因裸字段判定会被 403）
        r = await ac.delete(f"/judgement/logs/{log_a}", headers=sh)
        assert r.status_code == 200, r.text
        # 只断言 200 抓不到「返回成功但没 commit」的回归，回查数据库确认真的删掉了
        async with AsyncSessionLocal() as db:
            remaining = (await db.execute(
                select(JudgementLog).where(JudgementLog.id == log_a)
            )).scalar_one_or_none()
            assert remaining is None, "接口返回成功，但记录仍存在于数据库中"

        # 未登录 401
        log_b = await _add_judgement_log(sup_id, target_id)
        r = await ac.delete(f"/judgement/logs/{log_b}")
        assert r.status_code == 401, r.text


@pytest.mark.asyncio
async def test_admin_list_rate_limited_by_ip():
    """公开名单接口按 IP 限流，防止脚本枚举管理员身份。

    该接口无需登录且会公示角色身份（含 is_whitelist），枚举成本必须抬高。
    隔离说明：conftest 的 ``_isolate_rate_buckets`` 已在每个用例前后 reset，
    这里再显式 reset 一次，并用**唯一的 X-Real-IP** 独占一个限流桶，
    确保本用例不受其他用例的残留计数影响（反之亦然）。
    """
    from app.api.judgement import _IP_LIMIT_ADMIN_LIST
    from app.utils import ratelimit

    ratelimit.reset()
    max_requests, _window = _IP_LIMIT_ADMIN_LIST
    headers = _unique_ip_headers()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        # 阈值内正常返回
        for i in range(max_requests):
            r = await ac.get("/judgement/admins", headers=headers)
            assert r.status_code == 200, f"第 {i + 1} 次请求被拒：{r.status_code} {r.text[:120]}"

        # 超出阈值 → 429
        r = await ac.get("/judgement/admins", headers=headers)
        assert r.status_code == 429, r.text
        assert "频繁" in r.json()["detail"]
        # RFC 6585 §1.1：429 需带 Retry-After（便于客户端/CDN 自动退避）
        assert r.headers.get("retry-after"), "429 响应缺少 Retry-After 头"
        assert int(r.headers["retry-after"]) > 0


@pytest.mark.asyncio
async def test_register_rate_limited_by_ip():
    """注册入口按 IP 限流，防批量造小号。

    与名单接口同一策略（本 PR 一并加固 ``POST /users``：该入口是前端实际使用的
    注册通道，此前只有 ``/auth/register`` 有限流）。同样用唯一 X-Real-IP 独占桶。
    """
    from app.api.users import _IP_LIMIT_REGISTER
    from app.utils import ratelimit

    ratelimit.reset()
    max_requests, _window = _IP_LIMIT_REGISTER
    sfx = uuid.uuid4().hex[:6]
    headers = _unique_ip_headers()

    def payload(i: int) -> dict:
        return {
            "username": f"rl_{sfx}_{i}",
            "email": f"rl_{sfx}_{i}@example.com",
            "password": "supersecret1",
        }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        for i in range(max_requests):
            r = await ac.post("/users", json=payload(i), headers=headers)
            assert r.status_code == 201, \
                f"第 {i + 1} 次注册被拒：{r.status_code} {r.text[:120]}"

        r = await ac.post("/users", json=payload(max_requests), headers=headers)
        assert r.status_code == 429, r.text
        assert "频繁" in r.json()["detail"]
        assert r.headers.get("retry-after"), "注册限流 429 缺少 Retry-After 头"


