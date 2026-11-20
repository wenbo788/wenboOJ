"""Unit tests for 1v1 Battle system."""

import uuid
from unittest.mock import patch
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.battle import (
    TIER_BRONZE,
    TIER_SILVER,
    TIER_GOLD,
    TIER_DIAMOND,
    UserBattleStats,
    Battle,
)
from app.models.problem import Problem
from app.models.user import User
from app.services import battle as battle_svc


async def _create_test_user(username_prefix: str) -> tuple[int, str]:
    suffix = uuid.uuid4().hex[:8]
    username = f"{username_prefix}_{suffix}"
    async with AsyncSessionLocal() as db:
        user = User(
            username=username,
            email=f"{username}@example.com",
            hashed_password="hashedpassword123",
            user_number=int(suffix[:6], 16) % 1000000 + 1,
            experience=100,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user.id, username


@pytest.mark.asyncio
async def test_user_battle_stats_init():
    """Test user battle stats defaults to Bronze III with 0 points."""
    uid, _ = await _create_test_user("battle_user")
    async with AsyncSessionLocal() as db:
        stats = await battle_svc.get_or_create_user_stats(db, uid)
        assert stats.tier == TIER_BRONZE
        assert stats.sub_tier == 3
        assert stats.points == 0
        assert stats.wins == 0
        assert stats.losses == 0
        assert stats.rank_score == 0


@pytest.mark.asyncio
async def test_ranked_win_and_promotion():
    """Test win point gain and sub-tier promotion."""
    uid, _ = await _create_test_user("battle_win")
    async with AsyncSessionLocal() as db:
        stats = await battle_svc.get_or_create_user_stats(db, uid)
        stats.points = 80

        # Win: +30 points -> 110 points -> Promotes to Bronze II with 10 points
        res = battle_svc._calculate_ranked_win(stats)
        assert res["promoted"] is True
        assert stats.tier == TIER_BRONZE
        assert stats.sub_tier == 2
        assert stats.points == 10
        assert stats.wins == 1
        assert stats.win_streak == 1


@pytest.mark.asyncio
async def test_ranked_tier_promotion():
    """Test promotion from Bronze I to Silver III."""
    uid, _ = await _create_test_user("battle_promo")
    async with AsyncSessionLocal() as db:
        stats = await battle_svc.get_or_create_user_stats(db, uid)
        stats.tier = TIER_BRONZE
        stats.sub_tier = 1
        stats.points = 90

        res = battle_svc._calculate_ranked_win(stats)
        assert res["promoted"] is True
        assert stats.tier == TIER_SILVER
        assert stats.sub_tier == 3
        assert stats.points == 20


@pytest.mark.asyncio
async def test_bronze_rookie_protection():
    """Test Bronze tier will not demote on loss, only minor deduction."""
    uid, _ = await _create_test_user("battle_bronze")
    async with AsyncSessionLocal() as db:
        stats = await battle_svc.get_or_create_user_stats(db, uid)
        stats.tier = TIER_BRONZE
        stats.sub_tier = 2
        stats.points = 5

        res = battle_svc._calculate_ranked_loss(stats)
        assert res["demoted"] is False
        assert stats.tier == TIER_BRONZE
        assert stats.sub_tier == 2
        assert stats.points == 0


@pytest.mark.asyncio
async def test_loss_graceful_demotion_with_buffer():
    """Test Silver tier demotion at 0 points has 70 buffer points to avoid rapid drop."""
    uid, _ = await _create_test_user("battle_buffer")
    async with AsyncSessionLocal() as db:
        stats = await battle_svc.get_or_create_user_stats(db, uid)
        stats.tier = TIER_SILVER
        stats.sub_tier = 1
        stats.points = 0

        res = battle_svc._calculate_ranked_loss(stats)
        assert res["demoted"] is True
        assert stats.tier == TIER_SILVER
        assert stats.sub_tier == 2
        assert stats.points == 70


@pytest.mark.asyncio
async def test_battle_create_and_settle():
    """Test complete battle flow: create, first to AC wins, and experience awarded."""
    u1_id, _ = await _create_test_user("player1")
    u2_id, _ = await _create_test_user("player2")

    async with AsyncSessionLocal() as db:
        # Create a test problem
        prob = Problem(
            title=f"对战测验题_{u1_id}",
            difficulty="普及",
            is_public=True,
            is_official=True,
            description="对战测试题面",
        )
        db.add(prob)
        await db.commit()
        await db.refresh(prob)

        user1 = await db.get(User, u1_id)
        user2 = await db.get(User, u2_id)
        exp1 = user1.experience or 0
        exp2 = user2.experience or 0

        battle = await battle_svc.create_battle(
            db,
            user1_id=u1_id,
            user2_id=u2_id,
            mode="ranked",
        )
        assert battle.status == "ongoing"
        assert battle.user1_id == u1_id
        assert battle.user2_id == u2_id

        # Player 1 ACs first
        await battle_svc.settle_battle(db, battle, winner_id=u1_id, finish_reason="ac")
        assert battle.status == "finished"
        assert battle.winner_id == u1_id
        assert battle.user1_status == "accepted"

        await db.refresh(user1)
        await db.refresh(user2)
        assert user1.experience == exp1 + 50
        assert user2.experience == exp2 + 15


@pytest.mark.asyncio
async def test_battle_api_endpoints():
    """Test battle REST API endpoints."""
    suffix = uuid.uuid4().hex[:8]
    username, pwd = f"bapi_{suffix}", "mypassword123"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        # Register and login
        r = await ac.post("/users", json={
            "username": username, "email": f"{username}@example.com", "password": pwd
        })
        assert r.status_code == 201

        r = await ac.post("/tokens", data={"username": username, "password": pwd})
        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Profile
        r = await ac.get("/battle/profile", headers=headers)
        assert r.status_code == 200
        data = r.json()
        assert data["tier"] == "bronze"
        assert data["sub_tier"] == 3
        assert data["points"] == 0

        # 2. Leaderboard
        r = await ac.get("/battle/leaderboard", headers=headers)
        assert r.status_code == 200
        assert "items" in r.json()

        # 3. Match queue & cancel
        r = await ac.post("/battle/match", json={"mode": "casual"}, headers=headers)
        assert r.status_code == 200
        assert r.json()["status"] in ("queued", "matched")

        r = await ac.get("/battle/match/status", headers=headers)
        assert r.status_code == 200

        r = await ac.delete("/battle/match", headers=headers)
        assert r.status_code == 200

        # 4. History
        r = await ac.get("/battle/history", headers=headers)
        assert r.status_code == 200
        assert "items" in r.json()


@pytest.mark.asyncio
async def test_battle_ranking_tier_and_win_tie_breaker():
    """Test leaderboard: higher tier first; when tier is equal, higher win count ranks first."""
    uA_id, uA_name = await _create_test_user("userA")
    uB_id, uB_name = await _create_test_user("userB")
    uC_id, uC_name = await _create_test_user("userC")

    async with AsyncSessionLocal() as db:
        # User A: Silver II, 50 points, 10 wins
        stA = await battle_svc.get_or_create_user_stats(db, uA_id)
        stA.tier = TIER_SILVER
        stA.sub_tier = 2
        stA.points = 50
        stA.wins = 10
        stA.total_matches = 15

        # User B: Silver II, 50 points, 20 wins (same tier and points as A, but more wins)
        stB = await battle_svc.get_or_create_user_stats(db, uB_id)
        stB.tier = TIER_SILVER
        stB.sub_tier = 2
        stB.points = 50
        stB.wins = 20
        stB.total_matches = 25

        # User C: Silver I, 10 points, 5 wins (higher sub-tier)
        stC = await battle_svc.get_or_create_user_stats(db, uC_id)
        stC.tier = TIER_SILVER
        stC.sub_tier = 1
        stC.points = 10
        stC.wins = 5
        stC.total_matches = 10

        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get("/ranking/battle?page=1&page_size=50")
        assert r.status_code == 200
        items = r.json()["items"]

        # Filter to our 3 users
        matched = [it for it in items if it["username"] in (uA_name, uB_name, uC_name)]
        assert len(matched) == 3
        # Expected rank order: C (Silver I) > B (Silver II with 20 wins) > A (Silver II with 10 wins)
        assert matched[0]["username"] == uC_name
        assert matched[1]["username"] == uB_name
        assert matched[2]["username"] == uA_name


@pytest.mark.asyncio
async def test_match_after_battle_finished_no_stale_jump():
    """Verify that after a battle finishes, rematch does not return the stale battle ID."""
    # Ensure problem exists
    async with AsyncSessionLocal() as db:
        prob = Problem(
            title="PTest A+B",
            difficulty="入门",
            is_public=True,
            is_official=True,
            time_limit=1000,
            memory_limit=128,
            description="A+B",
        )
        db.add(prob)
        await db.commit()

    suffix1 = uuid.uuid4().hex[:8]
    suffix2 = uuid.uuid4().hex[:8]
    suffix3 = uuid.uuid4().hex[:8]
    u1, p1 = f"b_rematch1_{suffix1}", "pass123456"
    u2, p2 = f"b_rematch2_{suffix2}", "pass123456"
    u3, p3 = f"b_rematch3_{suffix3}", "pass123456"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Register and login u1, u2, u3
        for u, p in [(u1, p1), (u2, p2), (u3, p3)]:
            await client.post("/users", json={"username": u, "email": f"{u}@test.com", "password": p})
        t1 = (await client.post("/tokens", data={"username": u1, "password": p1})).json()["access_token"]
        t2 = (await client.post("/tokens", data={"username": u2, "password": p2})).json()["access_token"]
        t3 = (await client.post("/tokens", data={"username": u3, "password": p3})).json()["access_token"]
        h1 = {"Authorization": f"Bearer {t1}"}
        h2 = {"Authorization": f"Bearer {t2}"}
        h3 = {"Authorization": f"Bearer {t3}"}

        # 1. User 1 enqueues
        r1 = await client.post("/battle/match", json={"mode": "casual"}, headers=h1)
        assert r1.status_code == 200
        assert r1.json()["status"] == "queued"

        # 2. User 2 enqueues -> paired!
        r2 = await client.post("/battle/match", json={"mode": "casual"}, headers=h2)
        assert r2.status_code == 200
        assert r2.json()["status"] == "matched"
        battle_id_1 = r2.json()["battle_id"]
        assert battle_id_1 is not None

        # 3. Check /battle/current returns ongoing battle
        cur1 = await client.get("/battle/current", headers=h1)
        assert cur1.status_code == 200
        assert cur1.json()["has_ongoing"] is True
        assert cur1.json()["battle_id"] == battle_id_1

        # 4. Check room details does not crash with timezone error
        room1 = await client.get(f"/battle/rooms/{battle_id_1}", headers=h1)
        assert room1.status_code == 200
        assert room1.json()["status"] == "ongoing"

        # 5. User 1 surrenders -> battle finishes!
        surr_res = await client.post(f"/battle/rooms/{battle_id_1}/surrender", headers=h1)
        assert surr_res.status_code == 200
        assert surr_res.json()["ok"] is True

        # 6. Check /battle/current now returns has_ongoing: False
        cur2 = await client.get("/battle/current", headers=h1)
        assert cur2.status_code == 200
        assert cur2.json()["has_ongoing"] is False

        # 7. User 1 starts a NEW match -> MUST NOT return the finished battle_id_1!
        r1_next = await client.post("/battle/match", json={"mode": "casual"}, headers=h1)
        assert r1_next.status_code == 200
        assert r1_next.json()["status"] == "queued"
        assert r1_next.json().get("battle_id") is None

        # 8. User 3 joins match -> pairs with User 1 into a NEW battle!
        r3 = await client.post("/battle/match", json={"mode": "casual"}, headers=h3)
        assert r3.status_code == 200
        assert r3.json()["status"] == "matched"
        battle_id_2 = r3.json()["battle_id"]
        assert battle_id_2 != battle_id_1


@pytest.mark.asyncio
async def test_screen_switch_and_surrender_validation():
    """Verify that surrender with screen_switch reasons requires matching server violation records."""
    suffix1 = uuid.uuid4().hex[:8]
    suffix2 = uuid.uuid4().hex[:8]
    u1, p1 = f"b_sc1_{suffix1}", "pass123456"
    u2, p2 = f"b_sc2_{suffix2}", "pass123456"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for u, p in [(u1, p1), (u2, p2)]:
            await client.post("/users", json={"username": u, "email": f"{u}@test.com", "password": p})
        t1 = (await client.post("/tokens", data={"username": u1, "password": p1})).json()["access_token"]
        t2 = (await client.post("/tokens", data={"username": u2, "password": p2})).json()["access_token"]
        h1 = {"Authorization": f"Bearer {t1}"}
        h2 = {"Authorization": f"Bearer {t2}"}

        # Pair u1 and u2
        await client.post("/battle/match", json={"mode": "casual"}, headers=h1)
        r_match = await client.post("/battle/match", json={"mode": "casual"}, headers=h2)
        battle_id = r_match.json()["battle_id"]

        # 1. Unverified reason="screen_switch_second" -> should be rejected with 400
        res_fake_2 = await client.post(
            f"/battle/rooms/{battle_id}/surrender",
            json={"reason": "screen_switch_second"},
            headers=h1,
        )
        assert res_fake_2.status_code == 400
        assert "违规状态不匹配" in res_fake_2.json()["detail"]

        # 2. Unverified reason="screen_switch_timeout" -> should be rejected with 400
        res_fake_timeout = await client.post(
            f"/battle/rooms/{battle_id}/surrender",
            json={"reason": "screen_switch_timeout"},
            headers=h1,
        )
        assert res_fake_timeout.status_code == 400
        assert "违规状态不匹配" in res_fake_timeout.json()["detail"]

        # 3. Report first leave
        r_leave1 = await client.post(
            f"/battle/rooms/{battle_id}/screen-switch",
            json={"action": "leave"},
            headers=h1,
        )
        assert r_leave1.status_code == 200
        assert r_leave1.json()["leave_count"] == 1

        # Still cannot forfeit as screen_switch_second (requires 2)
        res_still_1 = await client.post(
            f"/battle/rooms/{battle_id}/surrender",
            json={"reason": "screen_switch_second"},
            headers=h1,
        )
        assert res_still_1.status_code == 400

        # 4. Report second leave
        r_leave2 = await client.post(
            f"/battle/rooms/{battle_id}/screen-switch",
            json={"action": "leave"},
            headers=h1,
        )
        assert r_leave2.status_code == 200
        assert r_leave2.json()["leave_count"] == 2

        # 5. Now forfeit as screen_switch_second -> succeeds!
        res_ok = await client.post(
            f"/battle/rooms/{battle_id}/surrender",
            json={"reason": "screen_switch_second"},
            headers=h1,
        )
        assert res_ok.status_code == 200
        assert res_ok.json()["ok"] is True
        assert res_ok.json()["finish_reason"] == "screen_switch_second"


@pytest.mark.asyncio
async def test_screen_switch_tracker_ttl_sweep_and_clear():
    """测试切屏追踪器的异步清空与超时自动扫描机制。"""
    from datetime import datetime, timezone
    from app.services.battle import (
        _SCREEN_VIOLATION_TRACKER,
        _VIOLATION_LOCK,
        clear_violation_status,
        record_screen_switch,
    )

    # 1. 模拟插入一个过期的对战记录（2小时前）
    old_battle_id = 99998
    async with _VIOLATION_LOCK:
        _SCREEN_VIOLATION_TRACKER[(old_battle_id, 1)] = {
            "leave_count": 1,
            "last_leave_time": None,
            "max_leave_duration": 5.0,
            "created_at": 1000.0,
            "updated_at": 1000.0,  # 远古时间
        }

    # 2. 正常记录一个新对战的切屏
    curr_battle_id = 99999
    res = await record_screen_switch(curr_battle_id, 2, "leave")
    assert res["leave_count"] == 1

    # 3. 验证远古记录已在 record_screen_switch 过程中被自动扫除
    async with _VIOLATION_LOCK:
        assert (old_battle_id, 1) not in _SCREEN_VIOLATION_TRACKER
        assert (curr_battle_id, 2) in _SCREEN_VIOLATION_TRACKER

    # 4. 调用 clear_violation_status 清理当前对战
    await clear_violation_status(curr_battle_id)
    async with _VIOLATION_LOCK:
        assert (curr_battle_id, 2) not in _SCREEN_VIOLATION_TRACKER


@pytest.mark.asyncio
async def test_authoritative_server_settlement_on_unreturned_leave():
    """测试若玩家切屏离开超过15秒且未返回（如关闭网页），服务端通过 check_battle_timeout 主动权威判负。"""
    suffix1 = uuid.uuid4().hex[:8]
    suffix2 = uuid.uuid4().hex[:8]
    u1, p1 = f"b_auth1_{suffix1}", "pass123456"
    u2, p2 = f"b_auth2_{suffix2}", "pass123456"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for u, p in [(u1, p1), (u2, p2)]:
            await client.post("/users", json={"username": u, "email": f"{u}@test.com", "password": p})
        t1 = (await client.post("/tokens", data={"username": u1, "password": p1})).json()["access_token"]
        t2 = (await client.post("/tokens", data={"username": u2, "password": p2})).json()["access_token"]
        h1 = {"Authorization": f"Bearer {t1}"}
        h2 = {"Authorization": f"Bearer {t2}"}

        # Pair u1 and u2
        await client.post("/battle/match", json={"mode": "casual"}, headers=h1)
        r_match = await client.post("/battle/match", json={"mode": "casual"}, headers=h2)
        battle_id = r_match.json()["battle_id"]

        # u1 reports "leave"
        r_leave = await client.post(
            f"/battle/rooms/{battle_id}/screen-switch",
            json={"action": "leave"},
            headers=h1,
        )
        assert r_leave.status_code == 200

        # Simulate u1 closing tab and staying absent for 16 seconds
        from app.services.battle import _SCREEN_VIOLATION_TRACKER, _VIOLATION_LOCK
        from app.core.database import AsyncSessionLocal
        from app.models.battle import Battle

        async with _VIOLATION_LOCK:
            for k in _SCREEN_VIOLATION_TRACKER:
                if k[0] == battle_id:
                    _SCREEN_VIOLATION_TRACKER[k]["last_leave_time"] -= 20.0  # simulated 20s ago

        # Opponent checks room or current battle
        r_room = await client.get(f"/battle/rooms/{battle_id}", headers=h2)
        assert r_room.status_code == 200
        data = r_room.json()
        assert data["status"] == "finished"
        assert data["settlement"]["finish_reason"] == "screen_switch_timeout"


@pytest.mark.asyncio
async def test_simulate_restricted_to_casual():
    """Test simulate opponent is strictly forbidden in ranked mode and allowed in casual mode."""
    suffix = uuid.uuid4().hex[:8]
    username = f"sim_user_{suffix}"
    pwd = "TestPassword123!"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/users", json={
            "username": username, "email": f"{username}@example.com", "password": pwd
        })
        assert r.status_code == 201

        r = await ac.post("/tokens", data={"username": username, "password": pwd})
        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Attempt simulate in ranked mode -> must fail with 400
        r_ranked = await ac.post(
            "/battle/match",
            json={"mode": "ranked", "simulate": True},
            headers=headers,
        )
        assert r_ranked.status_code == 400
        assert "排位" in r_ranked.json()["detail"]

        # 2. Simulate in casual mode -> succeeds and creates casual battle
        r_casual = await ac.post(
            "/battle/match",
            json={"mode": "casual", "simulate": True},
            headers=headers,
        )
        assert r_casual.status_code == 200
        res_data = r_casual.json()
        assert res_data["status"] == "matched"
        assert "battle_id" in res_data

        # Verify battle mode in DB is casual
        async with AsyncSessionLocal() as db:
            battle = await db.get(Battle, res_data["battle_id"])
            assert battle is not None
            assert battle.mode == "casual"


@pytest.mark.asyncio
async def test_battle_try_run():
    """Test online self-test / try-run feature in 1v1 battle room."""
    suffix1 = uuid.uuid4().hex[:8]
    suffix2 = uuid.uuid4().hex[:8]
    u1, p1 = f"b_tr1_{suffix1}", "pass123456"
    u2, p2 = f"b_tr2_{suffix2}", "pass123456"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for u, p in [(u1, p1), (u2, p2)]:
            await client.post("/users", json={"username": u, "email": f"{u}@test.com", "password": p})
        t1 = (await client.post("/tokens", data={"username": u1, "password": p1})).json()["access_token"]
        t2 = (await client.post("/tokens", data={"username": u2, "password": p2})).json()["access_token"]
        h1 = {"Authorization": f"Bearer {t1}"}
        h2 = {"Authorization": f"Bearer {t2}"}

        # Pair u1 and u2
        await client.post("/battle/match", json={"mode": "casual"}, headers=h1)
        r_match = await client.post("/battle/match", json={"mode": "casual"}, headers=h2)
        battle_id = r_match.json()["battle_id"]

        fake_sandbox_res = {
            "status": "ok",
            "stdout": "42\n",
            "stderr": "",
            "time_ms": 15,
            "memory_kb": 2048,
            "detail": "",
        }

        with patch("app.api.battle.sandbox_try_run", return_value=fake_sandbox_res):
            # 1. Successful try-run by participant
            r_run = await client.post(
                f"/battle/rooms/{battle_id}/try-run",
                json={"language": "cpp", "code": "#include <iostream>\nint main(){ std::cout << 42 << std::endl; }", "input": "1 2"},
                headers=h1,
            )
            assert r_run.status_code == 200
            data = r_run.json()
            assert data["status"] == "ok"
            assert data["stdout"] == "42\n"
            assert data["time_ms"] == 15

            # 2. Empty code should be rejected with 400
            r_empty = await client.post(
                f"/battle/rooms/{battle_id}/try-run",
                json={"language": "cpp", "code": "   ", "input": ""},
                headers=h1,
            )
            assert r_empty.status_code == 400

            # 3. Invalid language should be rejected with 422/400
            r_lang = await client.post(
                f"/battle/rooms/{battle_id}/try-run",
                json={"language": "java", "code": "class Main{}", "input": ""},
                headers=h1,
            )
            assert r_lang.status_code in (400, 422)

        # 4. Unauthorized non-participant
        suffix3 = uuid.uuid4().hex[:8]
        u3, p3 = f"b_tr3_{suffix3}", "pass123456"
        await client.post("/users", json={"username": u3, "email": f"{u3}@test.com", "password": p3})
        t3 = (await client.post("/tokens", data={"username": u3, "password": p3})).json()["access_token"]
        h3 = {"Authorization": f"Bearer {t3}"}

        r_unauth = await client.post(
            f"/battle/rooms/{battle_id}/try-run",
            json={"language": "cpp", "code": "int main(){}", "input": ""},
            headers=h3,
        )
        assert r_unauth.status_code == 403






