import io
import uuid
import zipfile
from typing import Any
import pytest
from httpx import ASGITransport, AsyncClient
from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.problem import Problem
from app.models.submission import Submission, TestCase as ProblemTestCase
from app.models.user import User
from app.services import judge


async def _reg_login(ac: AsyncClient, pfx: str) -> tuple[dict[str, str], int]:
    u = f"{pfx}_{uuid.uuid4().hex[:8]}"
    pwd = "supersecret1"
    r = await ac.post("/users", json={"username": u, "email": f"{u}@e.com", "password": pwd})
    assert r.status_code == 201
    r = await ac.post("/tokens", data={"username": u, "password": pwd})
    assert r.status_code == 200
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = (await ac.get("/auth/me", headers=h)).json()
    return h, me["id"]


@pytest.mark.asyncio
async def test_subtask_all_passed(monkeypatch):
    """测试子任务全部通过时的评测结果与满分。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        _, uid = await _reg_login(ac, "st_user1")

    async with AsyncSessionLocal() as db:
        p = Problem(
            title=f"Subtask测试_{uuid.uuid4().hex[:6]}",
            difficulty="普及",
            is_public=True,
            subtask_config=[
                {"id": 1, "score": 30, "name": "Subtask 1"},
                {"id": 2, "score": 70, "name": "Subtask 2"},
            ],
        )
        db.add(p)
        await db.flush()

        tc1 = ProblemTestCase(problem_id=p.id, input_data="1", expected_output="2", subtask_id=1, sort_order=1)
        tc2 = ProblemTestCase(problem_id=p.id, input_data="2", expected_output="4", subtask_id=2, sort_order=2)
        db.add_all([tc1, tc2])
        await db.flush()

        s = Submission(problem_id=p.id, user_id=uid, code="print(int(input())*2)", language="python3", status="pending", score=0)
        db.add(s)
        await db.commit()
        sub_id = s.id

    async def fake_cmd(client: Any, cmd: dict[str, Any]) -> dict[str, Any]:
        args = cmd.get("args", [])
        if args and args[0] == "python3":
            # 根据输入计算输出
            inp = cmd.get("files", [{}])[0].get("content", "").strip()
            val = int(inp) * 2 if inp.isdigit() else 0
            return {
                "status": "Accepted",
                "time": 20_000_000,
                "memory": 2048 * 1024,
                "files": {"stdout": f"{val}\n", "stderr": ""},
            }
        return {"status": "Accepted", "files": {}}

    async def fake_del(client: Any, fid: str) -> None:
        pass

    monkeypatch.setattr(judge, "_run_cmd", fake_cmd)
    monkeypatch.setattr(judge, "_delete_file", fake_del)

    await judge.judge_submission(sub_id)

    async with AsyncSessionLocal() as db:
        res_sub = await db.get(Submission, sub_id)
        assert res_sub is not None
        assert res_sub.status == "accepted"
        assert res_sub.score == 100
        assert res_sub.subtask_results is not None
        assert len(res_sub.subtask_results) == 2
        assert res_sub.subtask_results[0]["score"] == 30
        assert res_sub.subtask_results[0]["status"] == "accepted"
        assert res_sub.subtask_results[1]["score"] == 70
        assert res_sub.subtask_results[1]["status"] == "accepted"


@pytest.mark.asyncio
async def test_subtask_partial_pass(monkeypatch):
    """测试部分子任务通过时，获得部分分且状态为 partially_correct。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        _, uid = await _reg_login(ac, "st_user2")

    async with AsyncSessionLocal() as db:
        p = Problem(
            title=f"Subtask部分分_{uuid.uuid4().hex[:6]}",
            difficulty="普及",
            is_public=True,
            subtask_config=[
                {"id": 1, "score": 40, "name": "小数据"},
                {"id": 2, "score": 60, "name": "大数据"},
            ],
        )
        db.add(p)
        await db.flush()

        tc1 = ProblemTestCase(problem_id=p.id, input_data="10", expected_output="10", subtask_id=1, sort_order=1)
        tc2 = ProblemTestCase(problem_id=p.id, input_data="1000", expected_output="1000", subtask_id=2, sort_order=2)
        db.add_all([tc1, tc2])
        await db.flush()

        s = Submission(problem_id=p.id, user_id=uid, code="print(10)", language="python3", status="pending", score=0)
        db.add(s)
        await db.commit()
        sub_id = s.id

    async def fake_cmd(client: Any, cmd: dict[str, Any]) -> dict[str, Any]:
        # 始终输出 10，因此 tc1 会 AC，tc2 会 WA
        return {
            "status": "Accepted",
            "time": 15_000_000,
            "memory": 1024 * 1024,
            "files": {"stdout": "10\n", "stderr": ""},
        }

    async def fake_del(client: Any, fid: str) -> None:
        pass

    monkeypatch.setattr(judge, "_run_cmd", fake_cmd)
    monkeypatch.setattr(judge, "_delete_file", fake_del)

    await judge.judge_submission(sub_id)

    async with AsyncSessionLocal() as db:
        res_sub = await db.get(Submission, sub_id)
        assert res_sub is not None
        assert res_sub.status == "partially_correct"
        assert res_sub.score == 40
        assert res_sub.subtask_results is not None
        assert len(res_sub.subtask_results) == 2
        assert res_sub.subtask_results[0]["score"] == 40
        assert res_sub.subtask_results[0]["status"] == "accepted"
        assert res_sub.subtask_results[1]["score"] == 0
        assert res_sub.subtask_results[1]["status"] == "wrong_answer"


@pytest.mark.asyncio
async def test_subtask_tle_skip_and_continue(monkeypatch):
    """测试子任务内点 TLE 后，跳过同组剩余点，但继续评测后续子任务。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        _, uid = await _reg_login(ac, "st_user3")

    async with AsyncSessionLocal() as db:
        p = Problem(
            title=f"Subtask_TLE跳过_{uuid.uuid4().hex[:6]}",
            difficulty="提高",
            is_public=True,
            subtask_config=[
                {"id": 1, "score": 25, "name": "Subtask 1"},
                {"id": 2, "score": 75, "name": "Subtask 2"},
            ],
        )
        db.add(p)
        await db.flush()

        # Subtask 1 有 2 个点
        tc1 = ProblemTestCase(problem_id=p.id, input_data="1", expected_output="1", subtask_id=1, sort_order=1)
        tc2 = ProblemTestCase(problem_id=p.id, input_data="2", expected_output="2", subtask_id=1, sort_order=2)
        # Subtask 2 有 1 个点
        tc3 = ProblemTestCase(problem_id=p.id, input_data="3", expected_output="3", subtask_id=2, sort_order=3)
        db.add_all([tc1, tc2, tc3])
        await db.flush()

        s = Submission(problem_id=p.id, user_id=uid, code="...", language="python3", status="pending", score=0)
        db.add(s)
        await db.commit()
        sub_id = s.id

    ran_cases = []

    async def fake_cmd(client: Any, cmd: dict[str, Any]) -> dict[str, Any]:
        inp = cmd.get("files", [{}])[0].get("content", "").strip()
        ran_cases.append(inp)
        if inp == "1":
            # 第一个点超时
            return {
                "status": "Time Limit Exceeded",
                "time": 1000_000_000,
                "memory": 2048 * 1024,
                "files": {},
            }
        # 其他点通过
        return {
            "status": "Accepted",
            "time": 10_000_000,
            "memory": 1024 * 1024,
            "files": {"stdout": f"{inp}\n"},
        }

    async def fake_del(client: Any, fid: str) -> None:
        pass

    monkeypatch.setattr(judge, "_run_cmd", fake_cmd)
    monkeypatch.setattr(judge, "_delete_file", fake_del)

    await judge.judge_submission(sub_id)

    # 验证运行情况：tc2 ("2") 应该被跳过未运行，但 tc3 ("3") 应该正常运行
    assert "1" in ran_cases
    assert "2" not in ran_cases
    assert "3" in ran_cases

    async with AsyncSessionLocal() as db:
        res_sub = await db.get(Submission, sub_id)
        assert res_sub is not None
        assert res_sub.score == 75
        assert res_sub.status == "partially_correct"
        assert res_sub.subtask_results is not None
        # Subtask 1 的点 2 状态为 skipped
        st1_cases = res_sub.subtask_results[0]["cases"]
        assert st1_cases[0]["status"] == "time_limit_exceeded"
        assert st1_cases[1]["status"] == "skipped"
        # Subtask 2 满分通过
        assert res_sub.subtask_results[1]["score"] == 75
        assert res_sub.subtask_results[1]["status"] == "accepted"


@pytest.mark.asyncio
async def test_subtasks_api_and_zip_upload():
    """测试子任务 API 配置与 ZIP 上传自动识别。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h, uid = await _reg_login(ac, "st_admin")
        async with AsyncSessionLocal() as db:
            u = await db.get(User, uid)
            u.can_manage_problems = True
            await db.commit()

        # 1. 创建题目
        r = await ac.post("/problems", json={
            "title": f"子任务测试题_{uuid.uuid4().hex[:6]}",
            "difficulty": "入门",
            "is_public": True,
        }, headers=h)
        assert r.status_code == 200
        pid = r.json()["id"]

        # 2. 上传带有子任务目录的 ZIP 文件
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w") as zf:
            zf.writestr("subtask1/1.in", "1")
            zf.writestr("subtask1/1.out", "1")
            zf.writestr("subtask1/2.in", "2")
            zf.writestr("subtask1/2.out", "2")
            zf.writestr("subtask2/1.in", "3")
            zf.writestr("subtask2/1.out", "3")

        zip_buf.seek(0)
        files = {"file": ("testcases.zip", zip_buf.getvalue(), "application/zip")}
        r = await ac.post(f"/problems/{pid}/test-cases/upload-zip", files=files, headers=h)
        assert r.status_code == 200
        data = r.json()
        assert data["imported"] == 3
        assert data["detected_subtasks"] == [1, 2]
        assert len(data["subtask_config"]) == 2

        # 3. 查询测试点列表，验证 subtask_id
        r = await ac.get(f"/problems/{pid}/test-cases", headers=h)
        assert r.status_code == 200
        cases = r.json()
        assert len(cases) == 3
        assert cases[0]["subtask_id"] == 1
        assert cases[1]["subtask_id"] == 1
        assert cases[2]["subtask_id"] == 2

        # 4. 更新子任务分值与名称
        r = await ac.put(f"/problems/{pid}/subtasks", json={
            "subtask_config": [
                {"id": 1, "score": 30, "name": "基础分"},
                {"id": 2, "score": 70, "name": "满分分"},
            ],
            "case_subtasks": {
                str(cases[0]["id"]): 1,
                str(cases[1]["id"]): 1,
                str(cases[2]["id"]): 2,
            }
        }, headers=h)
        assert r.status_code == 200
        assert r.json()["subtask_config"][0]["score"] == 30
        assert r.json()["subtask_config"][1]["score"] == 70

        # 5. 单个测试点 PATCH 更新
        r = await ac.patch(f"/problems/{pid}/test-cases/{cases[0]['id']}", json={
            "subtask_id": 2,
            "subtask_score": 70,
        }, headers=h)
        assert r.status_code == 200
        assert r.json()["subtask_id"] == 2
        assert r.json()["subtask_score"] == 70
