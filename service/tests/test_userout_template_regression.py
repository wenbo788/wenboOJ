"""回归：保存过模板后，UserOut 系接口不能 500。

bug 现场（用户报告）：保存代码模板后，个人主页打开就是后端 500。
根因：UserOut.code_template 声明为 dict，但 ORM 列存的是 JSON 字符串，
response_model 逐字段校验时 ValidationError → 500。
没保存过模板的用户 code_template=None 能通过校验，所以只有「保存过模板」
的人炸 —— 与「我的个人主页 500」完全吻合。
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_user_out_endpoints_survive_saved_template():
    suffix = uuid.uuid4().hex[:8]
    username = f"uo_{suffix}"
    password = "supersecret1"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/users", json={
            "username": username, "email": f"{username}@example.com",
            "password": password})
        assert r.status_code == 201, r.text
        r = await ac.post("/tokens", data={"username": username, "password": password})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        me = (await ac.get("/auth/me", headers=h)).json()
        user_id, user_number = me["id"], me["user_number"]

        # 保存模板（此后 ORM 的 code_template 变成 JSON 字符串）
        tpl = {"cpp": "// my cpp", "c": "// my c"}
        r = await ac.put("/users/me/prefs",
                         json={"code_template": tpl, "code_font": "space-mono"},
                         headers=h)
        assert r.status_code == 200, r.text

        # UserOut 系接口逐个过一遍：都是「个人主页 / 改资料 / 用户列表」在用的
        for path in (
            f"/users/{user_id}",
            f"/users/number/{user_number}",
            f"/users/by-username/{username}",
            "/users/me",
        ):
            r = await ac.get(path, headers=h)
            assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text}"
            body = r.json()
            assert body["code_template"] == tpl, path
            assert body["code_font"] == "space-mono", path

        # 改资料（response_model=UserOut）
        r = await ac.put("/users/me/profile", json={}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["code_template"] == tpl
