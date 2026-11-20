import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api import submissions as submissions_api
from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.problem import Problem
from app.models.submission import Submission
from app.models.user import User


async def _register_and_login(
    ac: AsyncClient, prefix: str
) -> tuple[dict[str, str], int]:
    suffix = uuid.uuid4().hex[:8]
    username = f"{prefix}_{suffix}"
    password = "supersecret1"
    response = await ac.post(
        "/users",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": password,
        },
    )
    assert response.status_code == 201, response.text
    response = await ac.post(
        "/tokens", data={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    user = (await ac.get("/auth/me", headers=headers)).json()
    return headers, user["id"]


@pytest.mark.asyncio
async def test_manager_can_rejudge_selected_scores(monkeypatch):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t"
    ) as ac:
        manager_headers, manager_id = await _register_and_login(ac, "rj_manager")
        normal_headers, normal_id = await _register_and_login(ac, "rj_normal")

        async with AsyncSessionLocal() as db:
            manager = await db.get(User, manager_id)
            manager.can_manage_problems = True
            problem = Problem(
                title=f"重测测试题_{uuid.uuid4().hex[:8]}",
                difficulty="入门",
                is_public=True,
            )
            db.add(problem)
            await db.flush()
            submissions = [
                Submission(
                    problem_id=problem.id,
                    user_id=normal_id,
                    code="int main(){}",
                    language="cpp",
                    status="accepted",
                    score=100,
                ),
                Submission(
                    problem_id=problem.id,
                    user_id=normal_id,
                    code="int main(){}",
                    language="cpp",
                    status="wrong_answer",
                    score=50,
                ),
                Submission(
                    problem_id=problem.id,
                    user_id=normal_id,
                    code="int main(){}",
                    language="cpp",
                    status="wrong_answer",
                    score=49,
                ),
                Submission(
                    problem_id=problem.id,
                    user_id=normal_id,
                    code="int main(){}",
                    language="cpp",
                    status="pending",
                    score=100,
                ),
                Submission(
                    problem_id=problem.id,
                    user_id=normal_id,
                    code="int main(){}",
                    language="cpp",
                    status="wrong_answer",
                    score=0,
                ),
            ]
            db.add_all(submissions)
            await db.commit()
            problem_id = problem.id
            submission_ids = [sub.id for sub in submissions]

        queued_calls: list[tuple[list[int], bool]] = []

        async def fake_judge_submissions(ids: list[int], *, is_rejudge: bool):
            queued_calls.append((ids, is_rejudge))

        monkeypatch.setattr(
            submissions_api, "judge_submissions", fake_judge_submissions
        )

        response = await ac.post(
            f"/problems/{problem_id}/submissions/rejudge",
            json={"score": 100},
            headers=manager_headers,
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"queued": 1, "skipped": 1, "score": 100}
        assert queued_calls == [([submission_ids[0]], True)]

        async with AsyncSessionLocal() as db:
            rows = (await db.execute(
                select(Submission)
                .where(Submission.id.in_(submission_ids))
                .order_by(Submission.id.asc())
            )).scalars().all()
            assert [row.status for row in rows] == [
                "pending", "wrong_answer", "wrong_answer", "pending", "wrong_answer"
            ]
            assert [row.score for row in rows] == [0, 50, 49, 100, 0]

        response = await ac.post(
            f"/problems/{problem_id}/submissions/rejudge",
            json={"score": 0},
            headers=manager_headers,
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"queued": 1, "skipped": 1, "score": 0}
        assert queued_calls == [
            ([submission_ids[0]], True),
            ([submission_ids[4]], True),
        ]

        async with AsyncSessionLocal() as db:
            s4 = await db.get(Submission, submission_ids[4])
            s4.status = "wrong_answer"
            await db.commit()

        response = await ac.post(
            f"/problems/{problem_id}/submissions/rejudge",
            json={"score": None},
            headers=manager_headers,
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"queued": 3, "skipped": 2, "score": None}
        assert queued_calls == [
            ([submission_ids[0]], True),
            ([submission_ids[4]], True),
            ([submission_ids[1], submission_ids[2], submission_ids[4]], True),
        ]

        response = await ac.post(
            f"/problems/{problem_id}/submissions/rejudge",
            headers=manager_headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["score"] is None

        response = await ac.post(
            f"/problems/{problem_id}/submissions/rejudge",
            json={"score": 0},
            headers=normal_headers,
        )
        assert response.status_code == 403, response.text
