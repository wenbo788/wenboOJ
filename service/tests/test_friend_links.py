"""Homepage friend links: public listing and admin-only replacement."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.user import User


async def _register(ac: AsyncClient, prefix: str, *, admin: bool = False) -> dict[str, str]:
    username = f"{prefix}_{uuid.uuid4().hex[:8]}"
    r = await ac.post(
        "/users",
        json={"username": username, "email": f"{username}@example.com", "password": "supersecret1"},
    )
    assert r.status_code == 201, r.text
    if admin:
        async with AsyncSessionLocal() as db:
            from sqlalchemy import select
            user = (await db.execute(select(User).where(User.username == username))).scalar_one()
            user.is_admin = True
            await db.commit()
    r = await ac.post("/tokens", data={"username": username, "password": "supersecret1"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.mark.asyncio
async def test_friend_link_public_list_and_admin_replace():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        user = await _register(ac, "fl_user")
        admin = await _register(ac, "fl_admin", admin=True)

        assert (await ac.get("/friend-links")).json() == {"links": []}

        payload = [
            {"title": "OI Wiki", "icon": "/static/oi-wiki.svg", "url": "https://oi-wiki.org"},
            {"title": "Luogu", "icon": "https://example.org/luogu.png", "url": "https://www.luogu.com.cn"},
        ]
        denied = await ac.put("/friend-links", headers=user, json=payload)
        assert denied.status_code == 403

        saved = await ac.put("/friend-links", headers=admin, json=payload)
        assert saved.status_code == 200, saved.text

        listed = await ac.get("/friend-links")
        assert listed.status_code == 200
        assert [(item["title"], item["url"]) for item in listed.json()["links"]] == [
            ("OI Wiki", "https://oi-wiki.org"),
            ("Luogu", "https://www.luogu.com.cn"),
        ]

        # Replace is atomic at the list level and persists display order.
        replacement = [{"title": "New Link", "icon": "/new.svg", "url": "https://new.example"}]
        assert (await ac.put("/friend-links", headers=admin, json=replacement)).status_code == 200
        listed = (await ac.get("/friend-links")).json()["links"]
        assert len(listed) == 1
        assert listed[0]["title"] == "New Link"


@pytest.mark.asyncio
async def test_friend_link_rejects_unsafe_or_incomplete_urls():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        admin = await _register(ac, "fl_admin", admin=True)
        bad_icon = await ac.put("/friend-links", headers=admin, json=[
            {"title": "Unsafe", "icon": "javascript:alert(1)", "url": "https://example.org"},
        ])
        assert bad_icon.status_code == 422

        bad_target = await ac.put("/friend-links", headers=admin, json=[
            {"title": "Unsafe", "icon": "/safe.svg", "url": "javascript:alert(1)"},
        ])
        assert bad_target.status_code == 422

        too_many = [
            {"title": f"Link {i}", "icon": "/icon.svg", "url": f"https://example.org/{i}"}
            for i in range(41)
        ]
        assert (await ac.put("/friend-links", headers=admin, json=too_many)).status_code == 400
