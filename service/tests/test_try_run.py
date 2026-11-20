"""题目页「自测环境」try-run 端点：权限 / 参数 / 限流 / 沙箱成功路径（mock）。

沙箱执行本身走 go-judge（本地测试环境未必有），成功路径用 mock 验证参数透传，
连接沙箱失败的真实路径由端点的 JudgeError → 502 分支兜底。
"""

import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.user import User


async def _make_problem_author(ac: AsyncClient, prefix: str) -> dict:
    """注册用户并授予建题权限（普通用户建题有投题审核门槛）。"""
    suffix = uuid.uuid4().hex[:8]
    username = f"{prefix}_{suffix}"
    r = await ac.post(
        "/users",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "supersecret1",
        },
    )
    assert r.status_code == 201, r.text
    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(User).where(User.username == username))).scalar_one()
        row.can_manage_problems = True
        await db.commit()
    r = await ac.post("/tokens", data={"username": username, "password": "supersecret1"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _public_problem(ac: AsyncClient, headers: dict) -> int:
    r = await ac.post(
        "/problems",
        json={
            "title": f"自测_{uuid.uuid4().hex[:8]}",
            "difficulty": "入门",
            "is_public": True,
        },
        headers=headers,
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


_FAKE_OK = {
    "status": "ok",
    "stdout": "3\n",
    "stderr": "",
    "time_ms": 7,
    "memory_kb": 3200,
    "detail": "",
}


@pytest.mark.asyncio
async def test_try_run_validation_and_mocked_success():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h = await _make_problem_author(ac, "tr")
        pid = await _public_problem(ac, h)

        # 未登录拒绝
        r = await ac.post(
            f"/problems/{pid}/try-run", json={"language": "cpp", "code": "int main(){}"}
        )
        assert r.status_code in (401, 403), r.text

        # 题目不存在 → 404（与详情同口径防探测）
        r = await ac.post(
            "/problems/999999999/try-run",
            headers=h,
            json={"language": "cpp", "code": "int main(){}"},
        )
        assert r.status_code == 404, r.text

        # 不支持的语言 → 400
        r = await ac.post(
            f"/problems/{pid}/try-run",
            headers=h,
            json={"language": "rust", "code": "fn main(){}"},
        )
        assert r.status_code == 400, r.text

        # 空代码 → 400
        r = await ac.post(
            f"/problems/{pid}/try-run", headers=h, json={"language": "cpp", "code": "   "}
        )
        assert r.status_code == 400, r.text

        # 代码超长（>64KB）→ 400
        r = await ac.post(
            f"/problems/{pid}/try-run",
            headers=h,
            json={"language": "cpp", "code": "a" * 70_000},
        )
        assert r.status_code == 400, r.text

        # 成功路径：mock 沙箱，验证 200 + 透传
        with patch("app.api.problems.sandbox_try_run", return_value=_FAKE_OK) as m:
            r = await ac.post(
                f"/problems/{pid}/try-run",
                headers=h,
                json={"language": "cpp", "code": "int main(){return 0;}", "input": "1 2\n"},
            )
        assert r.status_code == 200, r.text
        assert r.json()["stdout"] == "3\n"
        assert r.json()["time_ms"] == 7
        m.assert_awaited_once()


@pytest.mark.asyncio
async def test_try_run_rate_limited():
    """每分钟 20 次：第 21 次 429。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h = await _make_problem_author(ac, "tr")
        pid = await _public_problem(ac, h)

        with patch("app.api.problems.sandbox_try_run", return_value=_FAKE_OK):
            codes = []
            for _ in range(21):
                r = await ac.post(
                    f"/problems/{pid}/try-run",
                    headers=h,
                    json={"language": "cpp", "code": "int main(){return 0;}"},
                )
                codes.append(r.status_code)

        assert codes[:20] == [200] * 20, codes
        assert codes[20] == 429, codes
