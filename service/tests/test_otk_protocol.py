"""otk-remote 协议端点（/otk/v1）的行为与安全口径。

覆盖协议三端点（拉题 / 提交 / 查询）、verdict 映射、错误格式
``{"error"}``、以及三条安全红线：

1. WA 等非 CE 状态不返回任何 detail / 逐点对比信息（防远端接口当
   测试数据 oracle）；
2. 提交查询只允许本人（防枚举）；
3. otk 提交与网页提交同一张表——网页提交列表天然可见。
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


async def _register_and_login(ac: AsyncClient) -> tuple[dict[str, str], int]:
    suffix = uuid.uuid4().hex[:8]
    username = f"otk_{suffix}"
    password = "supersecret1"
    r = await ac.post(
        "/users",
        json={"username": username, "email": f"{username}@example.com", "password": password},
    )
    assert r.status_code == 201, r.text
    r = await ac.post("/tokens", data={"username": username, "password": password})
    assert r.status_code == 200, r.text
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = (await ac.get("/auth/me", headers=headers)).json()
    return headers, me["id"]


async def _seed_problem(
    owner_id: int, *, is_public: bool = True, with_cases: bool = True,
) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.problem import Problem, REVIEW_APPROVED
    from app.models.submission import TestCase

    async with AsyncSessionLocal() as db:
        prob = Problem(
            title="A+B", difficulty="入门", description="求和",
            is_public=is_public, is_official=True, author_id=owner_id,
            review_status=REVIEW_APPROVED,
            time_limit=1000, memory_limit=128,
            samples=[{"input": "1 2\n", "output": "3\n"}],
        )
        db.add(prob)
        await db.flush()
        if with_cases:
            db.add(TestCase(
                problem_id=prob.id, input_data="1 2\n",
                expected_output="3\n", sort_order=0,
            ))
        await db.commit()
        return prob.id


async def _seed_submission(
    user_id: int, problem_id: int, *, status_: str,
    error_message: str | None = None,
    test_results: list | None = None,
) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.submission import Submission

    async with AsyncSessionLocal() as db:
        sub = Submission(
            problem_id=problem_id, user_id=user_id,
            code="#include <bits/stdc++.h>\nint main(){}",
            language="cpp", status=status_,
            error_message=error_message, test_results=test_results,
            score=100 if status_ == "accepted" else 0,
            time_used=12, memory_used=1024,
        )
        db.add(sub)
        await db.commit()
        await db.refresh(sub)
        return sub.id


async def test_otk_endpoints_require_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        for method, url, body in [
            ("get", "/otk/v1/problems/P1001", None),
            ("post", "/otk/v1/submissions", {"problem": "P1001", "language": "cpp", "source": "x"}),
            ("get", "/otk/v1/submissions/1", None),
        ]:
            # 无 token：401 + 协议 error 字段（不是 FastAPI 的 detail）
            r = await getattr(ac, method)(url, **({"json": body} if body else {}))
            assert r.status_code == 401, (url, r.text)
            assert "error" in r.json(), (url, r.text)

            # 坏 token 同样 401
            r = await getattr(ac, method)(
                url, headers={"Authorization": "Bearer not-a-jwt"},
                **({"json": body} if body else {}),
            )
            assert r.status_code == 401, (url, r.text)
            assert "error" in r.json(), (url, r.text)


async def test_otk_fetch_problem():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        headers, user_id = await _register_and_login(ac)
        problem_id = await _seed_problem(user_id)

        r = await ac.get(f"/otk/v1/problems/P{1000 + problem_id}", headers=headers)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["id"] == f"P{1000 + problem_id}"
        assert data["title"] == "A+B"
        assert data["time_limit_ms"] == 1000
        assert data["memory_limit_mb"] == 128
        assert data["samples"] == [{"input": "1 2\n", "output": "3\n"}]


async def test_otk_fetch_missing_or_invisible_is_404():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        headers, _ = await _register_and_login(ac)

        # 不存在：404 + error 字段
        r = await ac.get("/otk/v1/problems/P999999", headers=headers)
        assert r.status_code == 404, r.text
        assert r.json()["error"] == "题目不存在"

        # 他人未公开题：同样 404（不泄露存在性）
        _, other_id = await _register_and_login(ac)
        hidden = await _seed_problem(other_id, is_public=False)
        r = await ac.get(f"/otk/v1/problems/P{1000 + hidden}", headers=headers)
        assert r.status_code == 404, r.text
        assert "error" in r.json()


async def test_otk_submit_creates_pending_and_visible_on_web(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        headers, user_id = await _register_and_login(ac)
        problem_id = await _seed_problem(user_id)

        queued: list[int] = []

        async def fake_judge(sub_id: int):
            queued.append(sub_id)

        monkeypatch.setattr("app.api.otk.judge_submission", fake_judge)

        r = await ac.post(
            "/otk/v1/submissions",
            json={"problem": f"P{1000 + problem_id}", "language": "cpp", "source": "int main(){}"},
            headers=headers,
        )
        assert r.status_code == 201, r.text
        sub_id = int(r.json()["id"])

        # 刚提交：Pending / Judging（其余字段省略）
        r = await ac.get(f"/otk/v1/submissions/{sub_id}", headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["verdict"] in ("Pending", "Judging")

        # 来自 otk 的提交在网页端提交列表同样可见（同一张表）
        r = await ac.get(f"/problems/{problem_id}/submissions", headers=headers)
        assert r.status_code == 200, r.text
        assert any(item["id"] == sub_id for item in r.json()["items"])


async def test_otk_wa_returns_no_details(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        headers, user_id = await _register_and_login(ac)
        problem_id = await _seed_problem(user_id)

        sub_id = await _seed_submission(
            user_id, problem_id, status_="wrong_answer",
            # 模拟 error_message 里带了对比信息——otk 通道一律不得出站
            error_message="第 1 组数据:\n 期望 3\n 实际 4",
            test_results=[
                {"case": 1, "status": "accepted", "time": 5, "memory": 1024},
                {"case": 2, "status": "wrong_answer", "time": 7, "memory": 1100},
            ],
        )

        r = await ac.get(f"/otk/v1/submissions/{sub_id}", headers=headers)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["verdict"] == "WA"
        assert data["detail"] == ""
        assert data["score"] == 0 and data["max_score"] == 0
        assert data["time_ms"] == 12 and data["memory_kb"] == 1024
        assert [p["index"] for p in data["test_points"]] == [1, 2]
        assert data["test_points"][0]["verdict"] == "AC"
        assert data["test_points"][1]["verdict"] == "WA"
        # 逐点 detail 永远为空
        assert all(p["detail"] == "" for p in data["test_points"])


async def test_otk_ce_returns_compiler_output():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        headers, user_id = await _register_and_login(ac)
        problem_id = await _seed_problem(user_id)

        sub_id = await _seed_submission(
            user_id, problem_id, status_="compile_error",
            error_message="main.cpp:3:1: error: expected ';' before '}' token",
        )

        r = await ac.get(f"/otk/v1/submissions/{sub_id}", headers=headers)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["verdict"] == "CE"
        # 协议明文：CE 的 detail 放编译器输出（编译错误不涉及测试数据）
        assert "error: expected ';'" in data["detail"]


async def test_otk_verdict_mapping_for_other_terminal_states():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        headers, user_id = await _register_and_login(ac)
        problem_id = await _seed_problem(user_id)

        for status_, expected in [
            ("accepted", "AC"),
            ("time_limit_exceeded", "TLE"),
            ("memory_limit_exceeded", "MLE"),
            ("runtime_error", "RE"),
            ("system_error", "SE"),
            ("cancelled", "SE"),
        ]:
            sub_id = await _seed_submission(user_id, problem_id, status_=status_)
            r = await ac.get(f"/otk/v1/submissions/{sub_id}", headers=headers)
            assert r.status_code == 200, r.text
            assert r.json()["verdict"] == expected, status_


async def test_otk_submission_query_only_owner():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        headers_a, user_a = await _register_and_login(ac)
        headers_b, _ = await _register_and_login(ac)
        problem_id = await _seed_problem(user_a)
        sub_id = await _seed_submission(user_a, problem_id, status_="accepted")

        # 他人查询：404（不泄露提交存在性）
        r = await ac.get(f"/otk/v1/submissions/{sub_id}", headers=headers_b)
        assert r.status_code == 404, r.text
        assert "error" in r.json()

        # 非数字提交号：404
        r = await ac.get("/otk/v1/submissions/abc", headers=headers_a)
        assert r.status_code == 404, r.text


async def test_otk_submit_validation(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        headers, user_id = await _register_and_login(ac)
        problem_id = await _seed_problem(user_id)

        async def fake_judge(sub_id: int):  # noqa: ARG001 - 仅占位防真评测
            pass

        monkeypatch.setattr("app.api.otk.judge_submission", fake_judge)

        # 不支持的语言
        r = await ac.post(
            "/otk/v1/submissions",
            json={"problem": f"P{1000 + problem_id}", "language": "rust", "source": "fn main(){}"},
            headers=headers,
        )
        assert r.status_code == 400, r.text
        assert "error" in r.json()

        # 源码超过 256KB
        r = await ac.post(
            "/otk/v1/submissions",
            json={"problem": f"P{1000 + problem_id}", "language": "cpp", "source": "x" * (256 * 1024 + 1)},
            headers=headers,
        )
        assert r.status_code == 400, r.text
        assert "256KB" in r.json()["error"]

        # 无测试数据的题
        bare = await _seed_problem(user_id, with_cases=False)
        r = await ac.post(
            "/otk/v1/submissions",
            json={"problem": f"P{1000 + bare}", "language": "cpp", "source": "int main(){}"},
            headers=headers,
        )
        assert r.status_code == 400, r.text
        assert "测试数据" in r.json()["error"]
