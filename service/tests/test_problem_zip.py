"""测试 ZIP 压缩包解析题目功能。"""

import io
import zipfile as zf
import pytest

from app.services.problem_zip import (
    parse_problem_zip,
    parse_zip_case_entry,
    locate_problem_markdown,
)


def _build_zip(files: dict[str, str | bytes]) -> bytes:
    buf = io.BytesIO()
    with zf.ZipFile(buf, "w", zf.ZIP_DEFLATED) as z:
        for name, content in files.items():
            if isinstance(content, str):
                z.writestr(name, content.encode("utf-8"))
            else:
                z.writestr(name, content)
    return buf.getvalue()


def test_parse_zip_case_entry_various_formats():
    # 1. 扁平 1.in / 1.out
    res1 = parse_zip_case_entry("1.in")
    assert res1 is not None
    subtask_id, sort_key, ext, disp = res1
    assert subtask_id is None
    assert ext == "in"
    assert disp == "1"

    # 2. .ans 映射到 out
    res2 = parse_zip_case_entry("testdata/1.ans")
    assert res2 is not None
    assert res2[2] == "out"

    # 3. 目录型子任务 subtask1/1.in
    res3 = parse_zip_case_entry("testdata/subtask2/3.in")
    assert res3 is not None
    assert res3[0] == 2
    assert res3[1] == (2, "", 3)

    # 4. 文件名型子任务 subtask1_2.in
    res4 = parse_zip_case_entry("subtask1_2.in")
    assert res4 is not None
    assert res4[0] == 1
    assert res4[1] == (1, "", 2)

    # 5. 非数字名 sample.in
    res5 = parse_zip_case_entry("sample.in")
    assert res5 is not None
    assert res5[0] is None
    assert res5[3] == "sample"

    # 6. 系统与隐藏文件应被忽略
    assert parse_zip_case_entry("__MACOSX/._1.in") is None
    assert parse_zip_case_entry(".DS_Store") is None


def test_parse_problem_zip_basic():
    md = """---
title: "加法大师"
difficulty: "入门"
time_limit: 1500ms
memory_limit: 256MB
tags:
  - 基础
  - 模拟
---
## 题目描述
计算 $A+B$。

## 输入格式
两个数 $A, B$。

## 输出格式
一个数 $A+B$。
"""
    zip_bytes = _build_zip({
        "problem.md": md,
        "testdata/1.in": "1 2\n",
        "testdata/1.out": "3\n",
        "testdata/2.in": "10 20\n",
        "testdata/2.out": "30\n",
    })

    res = parse_problem_zip(zip_bytes, "test_prob.zip")
    meta = res["problem_meta"]
    assert meta["title"] == "加法大师"
    assert meta["difficulty"] == "入门"
    assert meta["time_limit"] == 1500
    assert meta["memory_limit"] == 256
    assert meta["tags"] == ["基础", "模拟"]
    assert "计算 $A+B$。" in meta["description"]

    cases = res["test_cases"]
    assert len(cases) == 2
    assert cases[0]["input"] == "1 2\n"
    assert cases[0]["output"] == "3\n"
    assert cases[1]["input"] == "10 20\n"
    assert cases[1]["output"] == "30\n"
    assert res["subtask_config"] is None


def test_parse_problem_zip_subtasks():
    md = """# 树形网络

## 题目描述
树上激光路径。
"""
    zip_bytes = _build_zip({
        "my_problem/statement.md": md,
        "my_problem/subtask1/1.in": "1",
        "my_problem/subtask1/1.out": "1",
        "my_problem/subtask1/2.in": "2",
        "my_problem/subtask1/2.out": "2",
        "my_problem/subtask2/1.in": "3",
        "my_problem/subtask2/1.out": "3",
    })

    res = parse_problem_zip(zip_bytes)
    assert res["problem_meta"]["title"] == "树形网络"
    assert len(res["test_cases"]) == 3
    assert res["detected_subtasks"] == [1, 2]
    cfg = res["subtask_config"]
    assert cfg is not None
    assert len(cfg) == 2
    assert cfg[0]["id"] == 1 and cfg[0]["score"] == 50
    assert cfg[1]["id"] == 2 and cfg[1]["score"] == 50


def test_parse_problem_zip_ans_and_input_output_pairing():
    md = """# 匹配测试"""
    zip_bytes = _build_zip({
        "problem.md": md,
        "data/input1.in": "100",
        "data/output1.ans": "200",
    })
    res = parse_problem_zip(zip_bytes)
    assert len(res["test_cases"]) == 1
    assert res["test_cases"][0]["input"] == "100"
    assert res["test_cases"][0]["output"] == "200"


def test_parse_problem_zip_missing_md():
    zip_bytes = _build_zip({
        "1.in": "1",
        "1.out": "1",
    })
    with pytest.raises(ValueError, match="未找到题目 Markdown 题面文件"):
        parse_problem_zip(zip_bytes)


def test_parse_problem_zip_missing_testcases():
    zip_bytes = _build_zip({
        "problem.md": "# Title",
    })
    with pytest.raises(ValueError, match="未找到有效测试点"):
        parse_problem_zip(zip_bytes)


def test_parse_problem_zip_unpaired_cases():
    zip_bytes = _build_zip({
        "problem.md": "# Title",
        "1.in": "1",
    })
    with pytest.raises(ValueError, match="缺少配对的输入/输出文件"):
        parse_problem_zip(zip_bytes)


import uuid
from httpx import ASGITransport, AsyncClient
from app.main import app


async def _make_user(ac: AsyncClient) -> dict[str, str]:
    uid = uuid.uuid4().hex[:6]
    name = f"zip_user_{uid}"
    pwd = "password123"
    r = await ac.post("/users", json={"username": name, "email": f"{name}@ex.com", "password": pwd})
    assert r.status_code == 201
    r = await ac.post("/tokens", data={"username": name, "password": pwd})
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_import_problem_zip_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        auth = await _make_user(ac)

        md = """---
title: "导入API测试题"
difficulty: "普及-"
---
## 题目描述
测试通过 ZIP 接口完整导入题目。

## 输入格式
两个数。

## 输出格式
和。
"""
        zip_bytes = _build_zip({
            "problem.md": md,
            "testdata/1.in": "10 20\n",
            "testdata/1.out": "30\n",
            "testdata/2.in": "5 5\n",
            "testdata/2.out": "10\n",
        })

        files = {"file": ("problem.zip", zip_bytes, "application/zip")}
        resp = await ac.post("/problems/import-zip", files=files, headers=auth)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["success"] is True
        assert data["imported_test_cases"] == 2
        prob = data["problem"]
        assert prob["title"] == "导入API测试题"
        assert prob["difficulty"] == "普及-"
        prob_id = prob["id"]

        # 验证题目详情可获取
        detail_resp = await ac.get(f"/problems/{prob_id}", headers=auth)
        assert detail_resp.status_code == 200
        assert "测试通过 ZIP 接口完整导入题目" in detail_resp.json()["description"]

        # 测试更新已有题目
        updated_md = """# 导入API测试题（已更新）
## 题目描述
这是更新后的题目描述。
"""
        updated_zip = _build_zip({
            "problem.md": updated_md,
            "testdata/1.in": "100 200\n",
            "testdata/1.out": "300\n",
        })
        files_update = {"file": ("updated.zip", updated_zip, "application/zip")}
        update_resp = await ac.post(
            "/problems/import-zip",
            data={"problem_id": prob_id},
            files=files_update,
            headers=auth,
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["imported_test_cases"] == 1
        assert update_resp.json()["problem"]["title"] == "导入API测试题（已更新）"


@pytest.mark.asyncio
async def test_import_batch_zip_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        auth = await _make_user(ac)

        zip1 = _build_zip({
            "problem.md": "# 批量测试题1\n## 题目描述\n描述1",
            "testdata/1.in": "1\n",
            "testdata/1.out": "1\n",
        })
        zip2 = _build_zip({
            "problem.md": "# 批量测试题2\n## 题目描述\n描述2",
            "testdata/1.in": "2\n",
            "testdata/1.out": "4\n",
        })
        invalid_zip = _build_zip({
            "1.in": "3\n",
            "1.out": "9\n",
        })

        # 批量上传 2 个有效 + 1 个无效 (缺失 markdown)
        files = [
            ("files", ("prob1.zip", zip1, "application/zip")),
            ("files", ("prob2.zip", zip2, "application/zip")),
            ("files", ("invalid.zip", invalid_zip, "application/zip")),
        ]
        resp = await ac.post("/problems/import-batch-zip", files=files, headers=auth)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["total"] == 3
        assert data["succeeded"] == 2
        assert data["failed"] == 1

        results = data["results"]
        assert results[0]["filename"] == "prob1.zip"
        assert results[0]["success"] is True
        assert results[0]["problem"]["title"] == "批量测试题1"

        assert results[1]["filename"] == "prob2.zip"
        assert results[1]["success"] is True
        assert results[1]["problem"]["title"] == "批量测试题2"

        assert results[2]["filename"] == "invalid.zip"
        assert results[2]["success"] is False
        assert "未找到题目 Markdown 题面文件" in results[2]["error"]


def test_zip_bomb_protection_decompress_tracker():
    """测试 ZipDecompressTracker 对单文件超限和累计解压量超限的防护。"""
    from app.services.problem_zip import ZipDecompressTracker

    tracker = ZipDecompressTracker(max_file=50, max_total=100)
    zip_bytes = _build_zip({
        "large_file.txt": "A" * 60,
        "small_file.txt": "B" * 30,
    })

    with zf.ZipFile(io.BytesIO(zip_bytes)) as archive:
        info_large = archive.getinfo("large_file.txt")
        with pytest.raises(ValueError, match="解压后过大"):
            tracker.read_member(archive, info_large)

        tracker_total = ZipDecompressTracker(max_file=100, max_total=50)
        info_small = archive.getinfo("small_file.txt")
        # First read 30 bytes: ok
        tracker_total.read_member(archive, info_small)
        # Second read 30 bytes: total 60 > 50 -> raises ValueError
        with pytest.raises(ValueError, match="解压后总大小不能超过"):
            tracker_total.read_member(archive, info_small)


def test_svg_disallowed():
    """验证 .svg 不在允许的图片扩展名中，防止存储型 XSS。"""
    from app.services.problem_zip import _IMAGE_EXTENSIONS

    assert ".svg" not in _IMAGE_EXTENSIONS
    assert _IMAGE_EXTENSIONS == {".png", ".jpg", ".jpeg", ".gif", ".webp"}


@pytest.mark.asyncio
async def test_batch_zip_total_size_limit():
    """验证批量导入接口限制单次请求总负载不超过 500MB。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        auth = await _make_user(ac)

        # Mock an upload file exceeding total size
        class FakeFile:
            def __init__(self, size: int):
                self.filename = "fake.zip"
                self.size = size

        # Verify that sum of sizes > 500MB is rejected
        from app.api.problems import import_problems_batch_zip
        from fastapi import HTTPException
        fake_user = type("FakeUser", (), {"id": 999})()
        fake_files = [FakeFile(300 * 1024 * 1024), FakeFile(250 * 1024 * 1024)]
        with pytest.raises(HTTPException) as exc_info:
            await import_problems_batch_zip(files=fake_files, db=None, current_user=fake_user)  # type: ignore
        assert exc_info.value.status_code == 400
        assert "500MB" in exc_info.value.detail




