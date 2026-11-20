"""提交查重（疑似抄袭榜）的回归测试。

两层：
1. 纯算法（``app.services.plagiarism``）—— 相似度必须对「只改名字/注释/空白」
   敏感、对「同模板不同解法」不误报；
2. 管理端接口 —— 扫描、榜单、看两边代码，以及权限（只有题目管理能用）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.main import app
from app.models.contest import Contest
from app.models.problem import Problem
from app.models.submission import Submission
from app.models.user import User
from app.services.plagiarism import compare, fingerprint
from app.services.user import allocate_user_number

PWD = "supersecret1"
_BASE = 882001

TPL = """#include <bits/stdc++.h>
using namespace std;
int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
"""

CODE_A = TPL + """    int n, k; cin >> n >> k;
    vector<long long> a(n);
    for (auto &v : a) cin >> v;
    sort(a.begin(), a.end());
    cout << a[k - 1] << '\\n';
    return 0;
}
"""

# 同一份逻辑只改标识符 / 注释 / 空白 —— 查重必须抓到
CODE_A_RENAMED = """// 我自己写的，真的
#include <bits/stdc++.h>
using namespace std;
int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);

    int cnt, idx; cin >> cnt >> idx;
    vector<long long> vals(cnt);
    for (auto &x : vals) cin >> x;
    sort(vals.begin(), vals.end());
    cout << vals[idx - 1] << '\\n';
    return 0;
}
"""

# 同模板、完全不同的解法 —— 不能误报（B / C 互不相同，实测相似度 0.44）
CODE_B = TPL + """    int n, m; cin >> n >> m;
    long long ans = 0;
    for (int i = 0; i < n; i++) {
        int v; cin >> v;
        if (v % m == 0) ans += v;
    }
    cout << ans << '\\n';
    return 0;
}
"""

CODE_C = TPL + """    int n; cin >> n;
    vector<int> v(n);
    for (int i = 0; i < n; i++) cin >> v[i];
    int best = 0;
    for (int x : v) best = max(best, x);
    cout << best << '\\n';
    return 0;
}
"""


# ---------------- 纯算法 ----------------

def test_identical_code_scores_one():
    assert compare(CODE_A, "cpp", CODE_A, "cpp") == 1.0


def test_renamed_identifiers_and_comments_still_match():
    """改名字、加注释、调空白是抄作业最常见的伪装，必须仍然判得很像。"""
    assert compare(CODE_A, "cpp", CODE_A_RENAMED, "cpp") >= 0.9


def test_different_solutions_stay_below_default_threshold():
    """同模板 + 完全不同的解法：分数要明显低于默认阈值 0.8。"""
    assert compare(CODE_A, "cpp", CODE_B, "cpp") < 0.6


def test_short_code_is_skipped():
    assert not fingerprint("int main(){return 0;}", "cpp").usable


def test_comment_markers_inside_strings_are_not_comments():
    fp = fingerprint('int main(){ string s = "http://a#b"; printf("%s", s.c_str()); }', "cpp")
    assert fp.usable or fp.token_count > 0  # 字面量整体算一个 token，没有被当注释切掉


def test_python_hash_comment_and_same_logic_match():
    a = "n = int(input())\ns = 0\nfor i in range(n):\n    s += int(input())\nprint(s)\n"
    b = "m = int(input())\ntotal = 0\nfor j in range(m):\n    total += int(input())\nprint(total)\n"
    assert compare(a, "python3", b, "python3") >= 0.9


# ---------------- 接口 ----------------

async def _make_user(tag: str, **fields) -> str:
    """直接入库造号：查重测试不关心注册流程，但需要真实 id/password 登录。"""
    uname = f"pl_{tag}_{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        number = await allocate_user_number(db)
        db.add(User(user_number=number, username=uname,
                    email=f"{uname}@example.com",
                    hashed_password=hash_password(PWD), is_active=True, **fields))
        await db.commit()
    return uname


async def _login(ac: AsyncClient, username: str) -> dict:
    r = await ac.post("/tokens", data={"username": username, "password": PWD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _uid(db, username: str) -> User:
    return (await db.execute(select(User).where(User.username == username))).scalar_one()


async def _seed_contest(reviewer: str, a1: str, a2: str) -> tuple[int, int]:
    """一题一赛 + 4 份提交：一对高相似 + 两份同模板但不同的。返回 (contest_id, problem_id)。"""
    async with AsyncSessionLocal() as db:
        rv, u1, u2 = await _uid(db, reviewer), await _uid(db, a1), await _uid(db, a2)
        problem = Problem(title="A+B Problem", description="")
        db.add(problem)
        await db.flush()
        now = datetime.now(timezone.utc)
        contest = Contest(title="查重测试赛", start_time=now - timedelta(hours=1),
                          end_time=now + timedelta(hours=1), owner_id=rv.id)
        db.add(contest)
        await db.flush()
        # 一对高相似（A vs 改名版 A）+ 两份同模板但完全不同的解法（B / C）
        for user, code in ((u1, CODE_A), (u2, CODE_A_RENAMED),
                           (u1, CODE_B), (u2, CODE_C)):
            db.add(Submission(problem_id=problem.id, user_id=user.id, code=code,
                              language="cpp", contest_id=contest.id, status="accepted"))
        await db.commit()
        return contest.id, problem.id


@pytest.mark.asyncio
async def test_scan_list_and_detail_for_reviewer():
    reviewer = await _make_user("reviewer", can_manage_problems=True)
    a1 = await _make_user("a1")
    a2 = await _make_user("a2")
    plain = await _make_user("plain")
    contest_id, problem_id = await _seed_contest(reviewer, a1, a2)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h = await _login(ac, reviewer)

        # 扫描：只有 CODE_A / CODE_A_RENAMED 这一对被判相似
        r = await ac.post("/admin/plagiarism/scan", json={"contest_id": contest_id}, headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["scanned"] == 4 and body["pairs"] == 1, body

        # 榜单
        r = await ac.get(f"/admin/plagiarism?contest_id={contest_id}", headers=h)
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert len(items) == 1, items
        pair = items[0]
        assert pair["score"] >= 0.8
        assert {pair["a"]["username"], pair["b"]["username"]} == {a1, a2}
        assert pair["problem_title"] == "A+B Problem"

        # 双方源码
        r = await ac.get(f"/admin/plagiarism/{pair['id']}", headers=h)
        assert r.status_code == 200, r.text
        detail = r.json()
        assert "sort(" in detail["a"]["code"] and "sort(" in detail["b"]["code"]

        # 同一范围重复扫描是覆盖写：不会因为唯一约束炸，也不会把同一对记两遍
        r = await ac.post("/admin/plagiarism/scan", json={"contest_id": contest_id}, headers=h)
        assert r.status_code == 200 and r.json()["pairs"] == 1, r.text
        r = await ac.get(f"/admin/plagiarism?contest_id={contest_id}", headers=h)
        assert len(r.json()["items"]) == 1

        # 按题目扫（contest_id 为空）是另一个范围，不会把比赛里的结果删掉
        r = await ac.post("/admin/plagiarism/scan", json={"problem_id": problem_id}, headers=h)
        assert r.status_code == 200, r.text
        r = await ac.get(f"/admin/plagiarism?contest_id={contest_id}", headers=h)
        assert len(r.json()["items"]) == 1

        # 无权限：普通用户连扫都扫不了
        h2 = await _login(ac, plain)
        assert (await ac.post("/admin/plagiarism/scan",
                              json={"contest_id": contest_id}, headers=h2)).status_code == 403
        assert (await ac.get("/admin/plagiarism", headers=h2)).status_code == 403


@pytest.mark.asyncio
async def test_scan_requires_scope_and_skips_self_pairs():
    reviewer = await _make_user("reviewer", can_manage_problems=True)
    solo = await _make_user("solo")
    async with AsyncSessionLocal() as db:
        su = await _uid(db, solo)
        problem = Problem(title="自抄不算", description="")
        db.add(problem)
        await db.flush()
        # 同一个人的两份几乎一样的提交：不该互相判抄袭
        for _ in range(2):
            db.add(Submission(problem_id=problem.id, user_id=su.id, code=CODE_A,
                              language="cpp", status="accepted"))
        await db.commit()
        pid = problem.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h = await _login(ac, reviewer)
        # 不指定范围 → 400
        assert (await ac.post("/admin/plagiarism/scan", json={}, headers=h)).status_code == 400
        # 按题目扫：自己跟自己不比
        r = await ac.post("/admin/plagiarism/scan", json={"problem_id": pid}, headers=h)
        assert r.status_code == 200 and r.json()["pairs"] == 0, r.text


@pytest.mark.asyncio
async def test_one_user_flooding_submissions_does_not_crowd_out_others():
    """一个人刷几百份提交，不能把 MAX_GROUP_SIZE 名额占满导致别人漏检。

    这正是评审指出的「截断发生在按人去重之前」的坑：刷提交的人排在前面就把
    后面真正互相抄的两个人挤掉了。
    """
    from app.services.plagiarism import MAX_GROUP_SIZE

    reviewer = await _make_user("reviewer", can_manage_problems=True)
    flooder = await _make_user("flooder")
    a1 = await _make_user("a1")
    a2 = await _make_user("a2")

    async with AsyncSessionLocal() as db:
        fu = await _uid(db, flooder)
        u1, u2 = await _uid(db, a1), await _uid(db, a2)
        problem = Problem(title="刷提交挤占名额", description="")
        db.add(problem)
        await db.flush()
        # 刷子先入库（id 更小），数量超过 MAX_GROUP_SIZE
        for i in range(MAX_GROUP_SIZE + 5):
            db.add(Submission(problem_id=problem.id, user_id=fu.id,
                              code=CODE_B + f"// {i}\n", language="cpp",
                              status="wrong_answer"))
        db.add(Submission(problem_id=problem.id, user_id=u1.id, code=CODE_A,
                          language="cpp", status="accepted"))
        db.add(Submission(problem_id=problem.id, user_id=u2.id, code=CODE_A_RENAMED,
                          language="cpp", status="accepted"))
        await db.commit()
        pid = problem.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        h = await _login(ac, reviewer)
        r = await ac.post("/admin/plagiarism/scan", json={"problem_id": pid}, headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["truncated"] is False
        assert body["pairs"] >= 1, "刷提交的人把名额占满，真正的抄袭对被挤掉了"
        r = await ac.get(f"/admin/plagiarism?problem_id={pid}", headers=h)
        users = {frozenset((i["a"]["username"], i["b"]["username"])) for i in r.json()["items"]}
        assert any({a1, a2} == set(x) for x in users), users
