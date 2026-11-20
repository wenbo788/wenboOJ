import uuid
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
async def test_problem_spj_crud():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h, uid = await _reg_login(ac, "spj_mgr")
        async with AsyncSessionLocal() as db:
            u = await db.get(User, uid)
            u.can_manage_problems = True
            await db.commit()
        r = await ac.post("/problems", json={
            "title": f"SPJ题_{uuid.uuid4().hex[:6]}",
            "difficulty": "入门",
            "is_public": True,
            "is_spj": True,
            "spj_language": "cpp",
            "spj_code": "int main(){return 0;}",
        }, headers=h)
        assert r.status_code == 200
        pid = r.json()["id"]
        assert r.json()["is_spj"] is True
        assert r.json()["spj_language"] == "cpp"
        assert r.json()["spj_code"] == "int main(){return 0;}"

        r = await ac.put(f"/problems/{pid}", json={
            "spj_language": "python3",
            "spj_code": "import sys; sys.exit(0)",
        }, headers=h)
        assert r.status_code == 200
        assert r.json()["spj_language"] == "python3"
        assert r.json()["spj_code"] == "import sys; sys.exit(0)"

@pytest.mark.asyncio
async def test_spj_judge_flow(monkeypatch):
    async with AsyncSessionLocal() as db:
        p = Problem(
            title=f"SPJ测试_{uuid.uuid4().hex[:6]}",
            difficulty="入门",
            is_public=True,
            is_spj=True,
            spj_language="cpp",
            spj_code="int main(){return 0;}",
        )
        db.add(p)
        await db.flush()
        tc = ProblemTestCase(problem_id=p.id, input_data="1 2", expected_output="3", sort_order=1)
        db.add(tc)
        s_ac = Submission(problem_id=p.id, user_id=1, code="print(3)", language="python3", status="pending", score=0)
        s_wa = Submission(problem_id=p.id, user_id=1, code="print(3)", language="python3", status="pending", score=0)
        db.add_all([s_ac, s_wa])
        await db.commit()
        pid, tc_id, ac_sub_id, wa_sub_id = p.id, tc.id, s_ac.id, s_wa.id

    cmds: list[dict[str, Any]] = []

    async def fake_cmd(client: Any, cmd: dict[str, Any]) -> dict[str, Any]:
        cmds.append(cmd)
        args = cmd.get("args", [])
        if args and args[0] == "g++":
            return {"status": "Accepted", "fileIds": {"spj": "spj_f1"}}
        if args and args[0] == "python3" and args[1] == "main.py":
            return {"status": "Accepted", "files": {"stdout": "arbitrary_output\n"}}
        if args and args[0] == "./spj":
            cur_sub_id = getattr(fake_cmd, "cur_sub_id", None)
            if cur_sub_id == wa_sub_id:
                return {"status": "Nonzero Exit Status", "exitStatus": 1, "files": {"stderr": "wrong answer"}}
            return {"status": "Accepted", "exitStatus": 0, "files": {}}
        return {"status": "Accepted", "files": {}}

    async def fake_del(client: Any, fid: str) -> None:
        pass

    monkeypatch.setattr(judge, "_run_cmd", fake_cmd)
    monkeypatch.setattr(judge, "_delete_file", fake_del)

    fake_cmd.cur_sub_id = ac_sub_id
    await judge.judge_submission(ac_sub_id)
    async with AsyncSessionLocal() as db:
        s = await db.get(Submission, ac_sub_id)
        assert s.status == "accepted"
        assert s.score == 100

    fake_cmd.cur_sub_id = wa_sub_id
    await judge.judge_submission(wa_sub_id)
    async with AsyncSessionLocal() as db:
        s = await db.get(Submission, wa_sub_id)
        assert s.status == "wrong_answer"
        assert s.score == 0
        assert "wrong answer" in (s.error_message or "")

@pytest.mark.asyncio
async def test_spj_compile_error(monkeypatch):
    async with AsyncSessionLocal() as db:
        p = Problem(
            title=f"SPJ编译错_{uuid.uuid4().hex[:6]}",
            difficulty="入门",
            is_public=True,
            is_spj=True,
            spj_language="cpp",
            spj_code="bad syntax",
        )
        db.add(p)
        await db.flush()
        tc = ProblemTestCase(problem_id=p.id, input_data="1", expected_output="1", sort_order=1)
        db.add(tc)
        s = Submission(problem_id=p.id, user_id=1, code="print(1)", language="python3", status="pending", score=0)
        db.add(s)
        await db.commit()
        sid = s.id

    async def fake_cmd(client: Any, cmd: dict[str, Any]) -> dict[str, Any]:
        args = cmd.get("args", [])
        if args and args[0] == "g++":
            return {"status": "Compile Error", "files": {"stderr": "syntax error on line 1"}}
        return {"status": "Accepted", "files": {}}

    monkeypatch.setattr(judge, "_run_cmd", fake_cmd)
    await judge.judge_submission(sid)
    async with AsyncSessionLocal() as db:
        sub = await db.get(Submission, sid)
        assert sub.status == "system_error"
        assert "Special Judge 编译失败" in (sub.error_message or "")

@pytest.mark.asyncio
async def test_spj_python_and_validation(monkeypatch):
    async with AsyncSessionLocal() as db:
        p_py = Problem(
            title=f"SPJ_PY_{uuid.uuid4().hex[:6]}",
            difficulty="入门",
            is_public=True,
            is_spj=True,
            spj_language="python3",
            spj_code="import sys; sys.exit(0)",
        )
        p_empty = Problem(
            title=f"SPJ_EMPTY_{uuid.uuid4().hex[:6]}",
            difficulty="入门",
            is_public=True,
            is_spj=True,
            spj_language="cpp",
            spj_code="",
        )
        p_badlang = Problem(
            title=f"SPJ_BAD_{uuid.uuid4().hex[:6]}",
            difficulty="入门",
            is_public=True,
            is_spj=True,
            spj_language="rust",
            spj_code="fn main(){}",
        )
        db.add_all([p_py, p_empty, p_badlang])
        await db.flush()
        tc1 = ProblemTestCase(problem_id=p_py.id, input_data="1", expected_output="1", sort_order=1)
        tc2 = ProblemTestCase(problem_id=p_empty.id, input_data="1", expected_output="1", sort_order=1)
        tc3 = ProblemTestCase(problem_id=p_badlang.id, input_data="1", expected_output="1", sort_order=1)
        db.add_all([tc1, tc2, tc3])
        s_py = Submission(problem_id=p_py.id, user_id=1, code="print(1)", language="python3", status="pending", score=0)
        s_empty = Submission(problem_id=p_empty.id, user_id=1, code="print(1)", language="python3", status="pending", score=0)
        s_badlang = Submission(problem_id=p_badlang.id, user_id=1, code="print(1)", language="python3", status="pending", score=0)
        db.add_all([s_py, s_empty, s_badlang])
        await db.commit()
        sid_py, sid_empty, sid_bad = s_py.id, s_empty.id, s_badlang.id

    py_cmd_seen = []
    async def fake_cmd(client: Any, cmd: dict[str, Any]) -> dict[str, Any]:
        args = cmd.get("args", [])
        if args and args[0] == "python3" and "spj.py" in args:
            py_cmd_seen.append(cmd)
            return {"status": "Accepted", "exitStatus": 0, "files": {}}
        return {"status": "Accepted", "files": {"stdout": "1\n"}}

    monkeypatch.setattr(judge, "_run_cmd", fake_cmd)
    monkeypatch.setattr(judge, "_delete_file", lambda c, f: None)

    await judge.judge_submission(sid_py)
    async with AsyncSessionLocal() as db:
        sub = await db.get(Submission, sid_py)
        assert sub.status == "accepted"
        assert len(py_cmd_seen) == 1
        assert "spj.py" in py_cmd_seen[0]["copyIn"]

    await judge.judge_submission(sid_empty)
    async with AsyncSessionLocal() as db:
        sub = await db.get(Submission, sid_empty)
        assert sub.status == "system_error"
        assert "未配置评测代码" in (sub.error_message or "")

    await judge.judge_submission(sid_bad)
    async with AsyncSessionLocal() as db:
        sub = await db.get(Submission, sid_bad)
        assert sub.status == "system_error"
        assert "不支持的 SPJ 语言" in (sub.error_message or "")
