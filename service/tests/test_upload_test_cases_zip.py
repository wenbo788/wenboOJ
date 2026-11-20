import io
import uuid
import zipfile
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.main import app
from app.models.user import User

@pytest.mark.asyncio
async def test_upload_test_cases_zip():
    s = uuid.uuid4().hex[:8]
    u, pwd = f"adm_{s}", "supersecret1"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/users", json={"username": u, "email": f"{u}@example.com", "password": pwd})
        assert r.status_code == 201
        async with AsyncSessionLocal() as db:
            row = (await db.execute(select(User).where(User.username == u))).scalar_one()
            row.can_manage_problems = True
            await db.commit()
        r = await ac.post("/tokens", data={"username": u, "password": pwd})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}

        r = await ac.post("/problems", json={"title": f"T_{s}", "difficulty": "入门", "is_public": True}, headers=h)
        assert r.status_code in (200, 201)
        pid = r.json()["id"]

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("testdata/1.in", "1 2\n")
            z.writestr("testdata/1.ans", "3\n")
            z.writestr("testdata/2.in", "3 4\n")
            z.writestr("testdata/2.out", "7\n")
            z.writestr("__MACOSX/._1.in", "junk")
        buf.seek(0)

        r = await ac.post(
            f"/problems/{pid}/test-cases/upload-zip",
            files={"file": ("data.zip", buf.read(), "application/zip")},
            headers=h,
        )
        assert r.status_code == 200, r.text
        assert r.json()["imported"] == 2

        r = await ac.get(f"/problems/{pid}/test-cases", headers=h)
        assert r.status_code == 200
        cases = r.json()
        assert len(cases) == 2
        assert cases[0]["input_data"] == "1 2\n"
        assert cases[0]["expected_output"] == "3\n"
        assert cases[1]["input_data"] == "3 4\n"
        assert cases[1]["expected_output"] == "7\n"

        buf2 = io.BytesIO()
        with zipfile.ZipFile(buf2, "w") as z:
            z.writestr("1.in", "10 20\n")
            z.writestr("1.out", "30\n")
        buf2.seek(0)

        r = await ac.post(
            f"/problems/{pid}/test-cases/upload-zip?clear_existing=true",
            files={"file": ("data2.zip", buf2.read(), "application/zip")},
            headers=h,
        )
        assert r.status_code == 200
        assert r.json()["imported"] == 1

        r = await ac.get(f"/problems/{pid}/test-cases", headers=h)
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["input_data"] == "10 20\n"

        r = await ac.delete(f"/problems/{pid}/test-cases", headers=h)
        assert r.status_code == 200
        assert r.json()["deleted_count"] == 1

        r = await ac.get(f"/problems/{pid}/test-cases", headers=h)
        assert r.status_code == 200
        assert len(r.json()) == 0

        # 测试批量上传 3 个测试点
        buf3 = io.BytesIO()
        with zipfile.ZipFile(buf3, "w") as z:
            z.writestr("1.in", "a")
            z.writestr("1.out", "b")
            z.writestr("2.in", "c")
            z.writestr("2.out", "d")
            z.writestr("3.in", "e")
            z.writestr("3.out", "f")
        buf3.seek(0)
        r = await ac.post(
            f"/problems/{pid}/test-cases/upload-zip",
            files={"file": ("data3.zip", buf3.read(), "application/zip")},
            headers=h,
        )
        assert r.status_code == 200
        assert r.json()["imported"] == 3

        r = await ac.get(f"/problems/{pid}/test-cases", headers=h)
        assert r.status_code == 200
        c3 = r.json()
        assert len(c3) == 3
        cid1, cid2, cid3 = c3[0]["id"], c3[1]["id"], c3[2]["id"]

        # 测试单点详情
        r_det = await ac.get(f"/problems/{pid}/test-cases/{cid1}", headers=h)
        assert r_det.status_code == 200
        assert r_det.json()["input_data"] == "a"

        # 测试单点删除
        r_del1 = await ac.delete(f"/problems/{pid}/test-cases/{cid1}", headers=h)
        assert r_del1.status_code == 200

        # 测试批量删除剩余测试点
        r_batch = await ac.post(
            f"/problems/{pid}/test-cases/batch-delete",
            json={"case_ids": [cid2, cid3]},
            headers=h,
        )
        assert r_batch.status_code == 200
        assert r_batch.json()["deleted_count"] == 2

        r_final = await ac.get(f"/problems/{pid}/test-cases", headers=h)
        assert r_final.status_code == 200
        assert len(r_final.json()) == 0

