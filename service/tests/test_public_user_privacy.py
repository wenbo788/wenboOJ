"""第七轮评审回归：公开用户端点不泄露敏感字段 + 附件下载 MIME 兜底。"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.problems import _safe_download_media_type
from app.main import app


async def _register(ac: AsyncClient, tag: str):
    uname = f"pub_{tag}"
    r = await ac.post("/users", json={
        "username": uname, "email": f"{uname}@example.com",
        "password": "supersecret1"})
    assert r.status_code == 201, r.text
    body = r.json()
    return uname, body["id"], body["user_number"]


@pytest.mark.asyncio
async def test_public_user_endpoints_hide_sensitive_fields():
    """/users/{id}、/number/{n}、/by-username/{u} 不得泄露 email/phone/
    can_* 管理标志/内部计数；角色徽章与展示字段保留。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        uname, uid, unum = await _register(ac, "hide")
        for path in (f"/users/{uid}", f"/users/number/{unum}",
                     f"/users/by-username/{uname}"):
            r = await ac.get(path)
            assert r.status_code == 200, f"{path}: {r.text}"
            body = r.json()
            # 隐私与内部字段必须缺失
            for key in ("email", "phone", "real_name", "is_active",
                        "can_speak", "speak_until", "can_manage_users",
                        "can_manage_posts", "can_manage_problems",
                        "can_assign_admin", "can_manage_tags",
                        "malicious_report_count", "content_violation_count",
                        "last_username_change", "oierdb_uid"):
                assert key not in body, f"{path} 泄露 {key}"
            # 展示/徽章字段保留
            assert body["username"] == uname
            assert body["user_number"] == unum
            assert "is_admin" in body and "color_tier" in body
            assert "experience" in body and "bio" in body


def test_safe_download_media_type_downgrades_unsafe():
    """可执行脚本的 MIME 一律降级 octet-stream；安全类型原样放行。"""
    assert _safe_download_media_type("text/html") == "application/octet-stream"
    assert _safe_download_media_type("image/svg+xml") == "application/octet-stream"
    assert _safe_download_media_type("application/xhtml+xml") == "application/octet-stream"
    assert _safe_download_media_type("text/plain;charset=utf-8") == "application/octet-stream"
    assert _safe_download_media_type(None) == "application/octet-stream"
    assert _safe_download_media_type("") == "application/octet-stream"
    # 安全类型放行（含参数与大小写）
    assert _safe_download_media_type("application/pdf") == "application/pdf"
    assert _safe_download_media_type("image/png") == "image/png"
    assert _safe_download_media_type("Image/PNG") == "image/png"


@pytest.mark.asyncio
async def test_download_attachment_media_type_downgraded(tmp_path, monkeypatch):
    """端到端：上传时伪造 text/html 的附件，下载响应必须是 octet-stream。"""
    from unittest.mock import patch

    from app.core.database import AsyncSessionLocal
    from app.models.problem import Problem, ProblemAttachment

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        uname, uid, _ = await _register(ac, "mime")
        r = await ac.post("/tokens", data={
            "username": uname, "password": "supersecret1"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}

        # 直插一个 content_type 被伪造为 text/html 的附件
        async with AsyncSessionLocal() as db:
            p = Problem(title="mime-test", description="d", difficulty="easy",
                        time_limit=1000, memory_limit=256, author_id=uid)
            db.add(p)
            await db.flush()
            pid = p.id
            att = ProblemAttachment(
                problem_id=pid, orig_name="evil.html", stored_path="evil.html",
                content_type="text/html", size_bytes=5, uploader_id=uid)
            db.add(att)
            await db.commit()
            att_id = att.id

        # 伪造磁盘文件
        from app.api.problems import _PRIVATE_ATTACH_DIR
        disk = _PRIVATE_ATTACH_DIR / str(pid)
        disk.mkdir(parents=True, exist_ok=True)
        (disk / "evil.html").write_bytes(b"<h1>x</h1>")

        r = await ac.get(f"/problems/{pid}/attachments/{att_id}/download", headers=h)
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("application/octet-stream"), r.headers
        # 强制附件下载语义仍在
        assert "attachment" in r.headers.get("content-disposition", "")
