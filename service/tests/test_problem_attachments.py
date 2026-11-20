"""题目附件功能回归测试。

覆盖：
- 作者 / 题目管理员可上传，详情接口返回 attachments 列表；
- 普通用户上传 403；
- 单文件超 16MB 拒绝；
- 可执行扩展名（.exe / .bat / .sh 等）拒绝；
- 作者 / 管理员可删除附件，删除后详情接口不再返回。
"""

import uuid
from io import BytesIO

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.user import User


async def _reg_login(ac: AsyncClient, name: str, **flags: bool) -> tuple[dict, int]:
    r = await ac.post("/users", json={
        "username": name, "email": f"{name}@example.com", "password": "supersecret1"})
    assert r.status_code == 201, r.text
    if flags:
        async with AsyncSessionLocal() as db:
            u = (await db.execute(select(User).where(User.username == name))).scalar_one()
            for k, v in flags.items():
                setattr(u, k, v)
            await db.commit()
    r = await ac.post("/tokens", data={"username": name, "password": "supersecret1"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, r.json()["access_token"]


async def _create_problem(ac: AsyncClient, h: dict) -> int:
    r = await ac.post("/problems", json={
        "title": f"附件题_{uuid.uuid4().hex[:6]}",
        "difficulty": "入门",
        "is_public": True,
    }, headers=h)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _file(name: str, content: bytes, ct: str = "application/octet-stream"):
    f = BytesIO(content)
    f.name = name
    return f


@pytest.mark.asyncio
async def test_author_upload_and_delete_attachment():
    suffix = uuid.uuid4().hex[:8]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        author_h, _ = await _reg_login(ac, f"au_{suffix}", can_manage_problems=True)
        pid = await _create_problem(ac, author_h)

        # 上传附件
        r = await ac.post(
            f"/problems/{pid}/attachments",
            headers=author_h,
            files={"file": ("data.txt", b"hello world", "text/plain")},
        )
        assert r.status_code == 200, r.text
        att = r.json()["attachment"]
        assert att["orig_name"] == "data.txt"
        assert att["size_bytes"] == 11
        assert att["download_url"] == f"/problems/{pid}/attachments/{att['id']}/download"

        # 详情接口返回附件
        d = (await ac.get(f"/problems/{pid}", headers=author_h)).json()
        assert len(d["attachments"]) == 1
        assert d["attachments"][0]["id"] == att["id"]
        assert d["attachments"][0]["download_url"].endswith(f"/problems/{pid}/attachments/{att['id']}/download")

        # 下载接口带鉴权能取到文件
        dr = await ac.get(att["download_url"], headers=author_h)
        assert dr.status_code == 200, dr.text
        assert dr.content == b"hello world"

        # 删除附件
        r = await ac.delete(f"/problems/{pid}/attachments/{att['id']}", headers=author_h)
        assert r.status_code == 200, r.text

        # 删除后详情不再返回
        d = (await ac.get(f"/problems/{pid}", headers=author_h)).json()
        assert d["attachments"] == []


@pytest.mark.asyncio
async def test_normal_user_upload_forbidden():
    suffix = uuid.uuid4().hex[:8]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        author_h, _ = await _reg_login(ac, f"au_{suffix}", can_manage_problems=True)
        normal_h, _ = await _reg_login(ac, f"nu_{suffix}")
        pid = await _create_problem(ac, author_h)

        r = await ac.post(
            f"/problems/{pid}/attachments",
            headers=normal_h,
            files={"file": ("x.txt", b"x", "text/plain")},
        )
        # 非作者/管理员上传：主题库题按 404（防探测），团队非管理员按 403
        assert r.status_code in (403, 404), r.text


@pytest.mark.asyncio
async def test_oversized_attachment_rejected():
    suffix = uuid.uuid4().hex[:8]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        author_h, _ = await _reg_login(ac, f"au_{suffix}", can_manage_problems=True)
        pid = await _create_problem(ac, author_h)

        big = b"x" * (16 * 1024 * 1024 + 1)
        r = await ac.post(
            f"/problems/{pid}/attachments",
            headers=author_h,
            files={"file": ("big.bin", big, "application/octet-stream")},
        )
        assert r.status_code == 400, r.text
        assert "16" in r.json()["detail"]


@pytest.mark.asyncio
async def test_executable_extension_rejected():
    suffix = uuid.uuid4().hex[:8]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        author_h, _ = await _reg_login(ac, f"au_{suffix}", can_manage_problems=True)
        pid = await _create_problem(ac, author_h)

        r = await ac.post(
            f"/problems/{pid}/attachments",
            headers=author_h,
            files={"file": ("evil.exe", b"MZ", "application/octet-stream")},
        )
        assert r.status_code == 400, r.text
        assert ".exe" in r.json()["detail"]


@pytest.mark.asyncio
async def test_delete_attachment_removes_disk_file():
    """删除附件后磁盘文件必须一并清理，不能留孤儿文件在storage 里。"""
    suffix = uuid.uuid4().hex[:8]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        author_h, _ = await _reg_login(ac, f"du_{suffix}", can_manage_problems=True)
        pid = await _create_problem(ac, author_h)

        r = await ac.post(
            f"/problems/{pid}/attachments",
            headers=author_h,
            files={"file": ("orphan.txt", b"x" * 32, "text/plain")},
        )
        assert r.status_code == 200, r.text
        att = r.json()["attachment"]

        from app.api.problems import _PRIVATE_ATTACH_DIR
        stored = await _stored_name(pid, att["id"])
        fpath = _PRIVATE_ATTACH_DIR / str(pid) / stored
        assert fpath.exists(), "上传后磁盘文件应存在"

        r = await ac.delete(f"/problems/{pid}/attachments/{att['id']}", headers=author_h)
        assert r.status_code == 200, r.text

        assert not fpath.exists(), "删除附件后磁盘文件必须被清理"


async def _stored_name(problem_id: int, attachment_id: int) -> str:
    """从 DB 读取附件的 stored_path（磁盘文件名）。"""
    from app.models.problem import ProblemAttachment
    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            select(ProblemAttachment).where(ProblemAttachment.id == attachment_id)
        )).scalar_one()
        return row.stored_path


@pytest.mark.asyncio
async def test_orphan_detection_and_dir_purge():
    """题目目录清理 + 孤儿文件对账：DB 无记录的磁盘文件应被检出并清掉。"""
    from app.api.problems import (
        _PRIVATE_ATTACH_DIR,
        _purge_problem_attachment_dir,
        find_orphan_attachment_files,
    )

    pid = 999000 + (uuid.uuid4().int % 1000)
    d = _PRIVATE_ATTACH_DIR / str(pid)
    d.mkdir(parents=True, exist_ok=True)
    (d / "aaa.txt").write_bytes(b"a")
    (d / "bbb.txt").write_bytes(b"b")

    # bbb 在 DB 中登记为存在，aaa 未登记
    orphans = find_orphan_attachment_files({(pid, "bbb.txt")})
    assert str(d / "aaa.txt") in orphans
    assert str(d / "bbb.txt") not in orphans

    # 题目删除场景：整目录清理
    _purge_problem_attachment_dir(pid)
    assert not d.exists(), "题目删除后附件目录应被清理"


@pytest.mark.asyncio
async def test_upload_rate_limited():
    """附件上传接口必须限流：窗口内第 21 次起返回 429（防磁盘 DoS）。"""
    from app.utils.ratelimit import check, reset

    suffix = uuid.uuid4().hex[:8]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        author_h, _ = await _reg_login(ac, f"rl_{suffix}", can_manage_problems=True)
        pid = await _create_problem(ac, author_h)

        reset()
        try:
            codes = []
            for i in range(21):
                r = await ac.post(
                    f"/problems/{pid}/attachments",
                    headers=author_h,
                    files={"file": (f"r{i}.txt", b"x", "text/plain")},
                )
                codes.append(r.status_code)
            assert 429 in codes, f"21 次连续上传应触发限流，实际状态码：{codes}"
            # 第一次请求不能被限流
            assert codes[0] == 200
        finally:
            reset()
            # 清理 20 个附件文件
            from app.api.problems import _purge_problem_attachment_dir
            _purge_problem_attachment_dir(pid)
