"""多评测机故障切换（主用挂了自动改走备用）。

最关键的不变量：**一次提交的「编译 + 全部测试点」必须落在同一台沙箱上**。
go-judge 的 copyOutCached 产生的 fileId 只存在于编译它的那台，
编译在 A 台、测试点跑在 B 台的话，B 台找不到 fileId，选手会收到莫名其妙的
Runtime Error。所以切换粒度是「整次评测」，本文件专门守住这一点。
"""

import time
import uuid

import pytest
from sqlalchemy import select
from unittest.mock import AsyncMock

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services import judge
from app.services.judge import JudgeError, judge_submission

PRIMARY = "http://primary.test:5050"
BACKUP = "http://backup.test:5050"


@pytest.fixture(autouse=True)
def _two_judges(monkeypatch):
    """每个用例都从「主用 + 一台备用、无冷却记录」的干净状态开始。"""
    monkeypatch.setattr(settings, "GO_JUDGE_URL", PRIMARY)
    monkeypatch.setattr(settings, "GO_JUDGE_FALLBACK_URLS", BACKUP)
    monkeypatch.setattr(settings, "GO_JUDGE_FAILOVER_COOLDOWN_SECONDS", 60)
    judge.reset_judge_health()
    yield
    judge.reset_judge_health()


# ==================== 造数据 ====================

async def _seed_user() -> int:
    from app.core.security import hash_password
    from app.services.extended_auth import create_user_with_number

    name = f"jf_{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        user = await create_user_with_number(
            db, username=name, email=f"{name}@example.com",
            hashed_password=hash_password("supersecret1"),
        )
        await db.commit()
        return user.id


async def _seed_problem(cases: list[tuple[str, str]]) -> int:
    from app.models.problem import Problem
    from app.models.submission import TestCase

    async with AsyncSessionLocal() as db:
        prob = Problem(
            title=f"评测机切换_{uuid.uuid4().hex[:8]}", difficulty="入门",
            description="", is_public=True, time_limit=1000, memory_limit=128,
        )
        db.add(prob)
        await db.flush()
        for i, (inp, out) in enumerate(cases):
            db.add(TestCase(problem_id=prob.id, input_data=inp,
                            expected_output=out, sort_order=i))
        await db.commit()
        return prob.id


async def _seed_submission(user_id: int, problem_id: int, language: str = "cpp") -> int:
    from app.models.submission import Submission

    async with AsyncSessionLocal() as db:
        sub = Submission(
            problem_id=problem_id, user_id=user_id, language=language,
            code="#include <iostream>\nint main(){return 0;}\n",
            status="pending", score=0,
        )
        db.add(sub)
        await db.commit()
        await db.refresh(sub)
        return sub.id


async def _status_of(submission_id: int) -> tuple[str, str | None, int]:
    from app.models.submission import Submission

    async with AsyncSessionLocal() as db:
        sub = (await db.execute(
            select(Submission).where(Submission.id == submission_id)
        )).scalar_one()
        return sub.status, sub.error_message, sub.score


def _fake_runner(*, fail_on: set[str] | None = None,
                 used: list[str] | None = None) -> object:
    """假的 go-judge：编译返回缓存 fileId，运行返回 Accepted。"""
    fail_on = fail_on or set()

    async def fake_run_cmd(client, cmd):
        url = str(client.base_url).rstrip("/")
        if used is not None:
            used.append(url)
        if url in fail_on:
            raise JudgeError(f"无法连接评测沙箱: connect to {url} failed")
        args = cmd.get("args") or []
        if args and "g++" in args:
            return {"status": "Accepted", "fileIds": {"main": "cached_bin"}}
        return {
            "status": "Accepted",
            "files": {"stdout": "ok\n", "stderr": ""},
            "time": 1_000_000,
            "memory": 1024 * 1024,
        }

    return fake_run_cmd


@pytest.fixture(autouse=True)
def _no_file_cleanup(monkeypatch):
    monkeypatch.setattr(judge, "_delete_file", AsyncMock())


# ==================== 用例 ====================

@pytest.mark.asyncio
async def test_healthy_primary_serves_everything(monkeypatch):
    """主用正常时，全部请求都落在主用，备用完全不被碰。"""
    used: list[str] = []
    monkeypatch.setattr(judge, "_run_cmd", _fake_runner(used=used))

    uid, pid = await _seed_user(), await _seed_problem([("1\n", "ok\n"), ("2\n", "ok\n")])
    sub_id = await _seed_submission(uid, pid)
    await judge_submission(sub_id)

    assert set(used) == {PRIMARY}
    assert await _status_of(sub_id) == ("accepted", None, 100)


@pytest.mark.asyncio
async def test_failover_reruns_whole_submission_on_backup(monkeypatch):
    """主用连不上 → 整份提交（含编译）在备用上重跑，且主用上不留任何残留。"""
    used: list[str] = []
    monkeypatch.setattr(
        judge, "_run_cmd", _fake_runner(fail_on={PRIMARY}, used=used)
    )

    uid = await _seed_user()
    pid = await _seed_problem([("1\n", "ok\n"), ("2\n", "ok\n")])
    sub_id = await _seed_submission(uid, pid)
    await judge_submission(sub_id)

    # ① 主用只被试探了一次，之后全部落在备用
    assert used[0] == PRIMARY
    assert set(used[1:]) == {BACKUP}
    # ② 编译 + 两个测试点一共 3 次，都在备用那台（关键不变量）
    assert used[1:] == [BACKUP, BACKUP, BACKUP]
    # ③ 结果照常落库，不是 system_error
    assert await _status_of(sub_id) == ("accepted", None, 100)


@pytest.mark.asyncio
async def test_all_judges_down_marks_system_error(monkeypatch):
    """两台都不可用 → system_error，且错误信息要说清试过几台、最后一台是谁。"""
    monkeypatch.setattr(judge, "_run_cmd", _fake_runner(fail_on={PRIMARY, BACKUP}))

    uid = await _seed_user()
    pid = await _seed_problem([("1\n", "ok\n")])
    sub_id = await _seed_submission(uid, pid)
    await judge_submission(sub_id)

    status, message, _ = await _status_of(sub_id)
    assert status == "system_error"
    assert message is not None
    assert "2 台" in message
    # 面向用户的错误信息不得泄露评测机地址（内网拓扑）
    assert PRIMARY not in message
    assert BACKUP not in message


@pytest.mark.asyncio
async def test_failed_judge_is_cooled_down_for_next_submission(monkeypatch):
    """主用挂过一次后，下一份提交直接先用备用，不再白等一次连接超时。"""
    used: list[str] = []
    monkeypatch.setattr(
        judge, "_run_cmd", _fake_runner(fail_on={PRIMARY}, used=used)
    )

    uid = await _seed_user()
    pid = await _seed_problem([("1\n", "ok\n")])

    first = await _seed_submission(uid, pid)
    await judge_submission(first)
    assert used[0] == PRIMARY                    # 第一份：先试主用

    used.clear()
    second = await _seed_submission(uid, pid)
    await judge_submission(second)
    assert used and used[0] == BACKUP            # 第二份：直接走备用
    assert PRIMARY not in used
    assert await _status_of(second) == ("accepted", None, 100)


@pytest.mark.asyncio
async def test_recovered_primary_is_used_again_after_cooldown(monkeypatch):
    """冷却期一过，主用重新回到第一优先（不需要重启服务）。"""
    used: list[str] = []
    monkeypatch.setattr(
        judge, "_run_cmd", _fake_runner(fail_on={PRIMARY}, used=used)
    )
    uid = await _seed_user()
    pid = await _seed_problem([("1\n", "ok\n")])
    await judge_submission(await _seed_submission(uid, pid))

    # 模拟冷却到期 + 主用已修好
    judge.reset_judge_health()
    used.clear()
    healthy = _fake_runner(used=used)
    monkeypatch.setattr(judge, "_run_cmd", healthy)
    await judge_submission(await _seed_submission(uid, pid))

    assert used and used[0] == PRIMARY
    assert set(used) == {PRIMARY}


@pytest.mark.asyncio
async def test_try_run_also_fails_over(monkeypatch):
    """题目页「自测环境」同样要走切换，否则主用挂了自测就废了。"""
    from app.services.judge import try_run

    used: list[str] = []
    monkeypatch.setattr(
        judge, "_run_cmd", _fake_runner(fail_on={PRIMARY}, used=used)
    )

    res = await try_run(
        language="cpp", code="int main(){return 0;}",
        input_data="", time_limit_ms=1000, memory_mb=128,
    )

    assert res["status"] == "ok"
    assert PRIMARY in used
    assert set(used) == {PRIMARY, BACKUP}


def test_stale_success_does_not_clear_newer_failure(monkeypatch):
    """并发场景：一次「发起于故障之前」的成功返回，不能把刚记录的故障抹掉。

    否则 A 协程刚把这台判为不可用，B 协程的旧成功一返回就把它恢复成健康，
    于是主用明明挂着却被反复优先尝试（每条提交都白等一次连接超时）。
    """
    started_at = time.monotonic()
    judge._mark_endpoint_down(PRIMARY)                      # 别的协程刚判它故障
    judge._mark_endpoint_up(PRIMARY, started_at=started_at)  # 本次成功发起于故障之前
    assert judge._ordered_endpoints()[0] == BACKUP, "故障记录被旧的成功抹掉了"

    # 反过来：成功发生在故障之后（这台确实已恢复），应当正常解除冷却
    judge.reset_judge_health()
    judge._mark_endpoint_down(PRIMARY)
    judge._mark_endpoint_up(PRIMARY, started_at=time.monotonic() + 1)
    assert judge._ordered_endpoints()[0] == PRIMARY


def test_endpoints_parsing_dedup_and_order(monkeypatch):
    """GO_JUDGE_FALLBACK_URLS 的解析：去空白、去尾斜杠、去重、主用恒在最前。"""
    monkeypatch.setattr(settings, "GO_JUDGE_URL", "http://main:5050/")
    monkeypatch.setattr(
        settings, "GO_JUDGE_FALLBACK_URLS",
        " http://b1:5050 , http://main:5050 ,, http://b2:5050/ ",
    )
    assert settings.go_judge_endpoints == [
        "http://main:5050", "http://b1:5050", "http://b2:5050",
    ]
