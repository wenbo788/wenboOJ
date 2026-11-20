"""ESA AI CAPTCHA enforcement on both password-login endpoints."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app


@pytest.mark.asyncio
async def test_esa_required_protects_primary_and_legacy_login():
    old_required = settings.ESA_CAPTCHA_REQUIRED
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            username = f"esa_{uuid.uuid4().hex[:8]}"
            password = "supersecret1"
            created = await ac.post(
                "/users",
                json={"username": username, "email": f"{username}@example.com", "password": password},
            )
            assert created.status_code == 201, created.text

            # ESA 未启用时，客户端伪造参数不能绕过本地图形码。
            settings.ESA_CAPTCHA_REQUIRED = False
            forged = await ac.post(
                "/auth/login",
                json={
                    "identifier": username,
                    "password": password,
                    "captcha_verify_param": "forged-ticket",
                },
            )
            assert forged.status_code == 400
            assert "验证码" in forged.json()["detail"]

            settings.ESA_CAPTCHA_REQUIRED = True

            # ESA 强制模式不可退回本地图形码，也不能漏掉旧 /tokens 登录端点。
            missing_primary = await ac.post(
                "/auth/login",
                json={"identifier": username, "password": password},
            )
            assert missing_primary.status_code == 400
            assert "安全验证" in missing_primary.json()["detail"]

            missing_legacy = await ac.post(
                "/tokens",
                data={"username": username, "password": password},
            )
            assert missing_legacy.status_code == 400
            assert "安全验证" in missing_legacy.json()["detail"]

            # 模拟 ESA 已在边缘验签并放行业务请求：主登录仍执行原有密码校验并签发令牌。
            accepted = await ac.post(
                "/auth/login?captcha_verify_param=esa-test-ticket",
                json={
                    "identifier": username,
                    "password": password,
                    "captcha_verify_param": "esa-test-ticket",
                },
            )
            assert accepted.status_code == 200, accepted.text
            assert accepted.json().get("access_token")
    finally:
        settings.ESA_CAPTCHA_REQUIRED = old_required
