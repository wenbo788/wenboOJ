"""题目 Markdown 题面解析与导入功能测试。"""

import uuid
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.problem_markdown import (
    export_problem_markdown,
    parse_problem_markdown,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def _make_user(ac: AsyncClient) -> dict[str, str]:
    uid = uuid.uuid4().hex[:6]
    name = f"md_user_{uid}"
    pwd = "password123"
    r = await ac.post("/users", json={"username": name, "email": f"{name}@ex.com", "password": pwd})
    assert r.status_code == 201
    r = await ac.post("/tokens", data={"username": name, "password": pwd})
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_parse_yaml_front_matter():
    content = """---
title: "A+B Problem"
difficulty: 入门
time_limit: 1000ms
memory_limit: 128MB
tags:
  - 基础
  - 模拟
source: "洛谷"
---

## 题目描述
计算两个数的和。

## 输入格式
一行两个整数 $a, b$。

## 输出格式
一个整数。

## 样例 #1
### 样例输入 #1
```
1 2
```
### 样例输出 #1
```
3
```
"""
    parsed = parse_problem_markdown(content)
    assert parsed["title"] == "A+B Problem"
    assert parsed["difficulty"] == "入门"
    assert parsed["time_limit"] == 1000
    assert parsed["memory_limit"] == 128
    assert parsed["tags"] == ["基础", "模拟"]
    assert parsed["source"] == "洛谷"
    assert parsed["description"] == "计算两个数的和。"
    assert parsed["input_format"] == "一行两个整数 $a, b$。"
    assert parsed["output_format"] == "一个整数。"
    assert len(parsed["samples"]) == 1
    assert parsed["samples"][0]["input"] == "1 2"
    assert parsed["samples"][0]["output"] == "3"


def test_parse_luogu_style():
    content = """
# P1001 A+B Problem

## 题目背景
这是背景介绍。

## 题目描述
输入两个整数 $a, b$，输出它们的和。

## 输入格式
两个以空格分开的整数 $a, b$。

## 输出格式
一个整数。

## 样例 #1
### 样例输入 #1
```
1 2
```
### 样例输出 #1
```
3
```

## 样例 #2
### 样例输入 #2
```
10 20
```
### 样例输出 #2
```
30
```

## 提示说明
$0 \\le a, b \\le 10^9$
"""
    parsed = parse_problem_markdown(content)
    assert parsed["title"] == "A+B Problem"
    assert parsed["background"] == "这是背景介绍。"
    assert parsed["description"] == "输入两个整数 $a, b$，输出它们的和。"
    assert parsed["input_format"] == "两个以空格分开的整数 $a, b$。"
    assert parsed["output_format"] == "一个整数。"
    assert parsed["hint"] == "$0 \\le a, b \\le 10^9$"
    assert len(parsed["samples"]) == 2
    assert parsed["samples"][0] == {"input": "1 2", "output": "3"}
    assert parsed["samples"][1] == {"input": "10 20", "output": "30"}


def test_parse_in_text_metadata_and_brackets():
    content = """
# 【模板】单源最短路径

**时间限制**：1.00s | **空间限制**：128MB
**难度**：普及+/提高-
**来源**：洛谷
**标签**：图论, 最短路, Dijkstra

【题目描述】
给出有向图，求最短路径。

【输入格式】
第一行包含四个正整数 $N, M, S$。

【输出格式】
输出一行包含 $N$ 个整数。

【输入样例 1】
```
4 6 1
```
【输出样例 1】
```
0 2 5 6
```

【说明/提示】
$1 \\le N \\le 10^4$
"""
    parsed = parse_problem_markdown(content)
    assert parsed["title"] == "【模板】单源最短路径"
    assert parsed["time_limit"] == 1000
    assert parsed["memory_limit"] == 128
    assert parsed["difficulty"] == "普及+/提高-"
    assert parsed["source"] == "洛谷"
    assert parsed["tags"] == ["图论", "最短路", "Dijkstra"]
    assert parsed["description"] == "给出有向图，求最短路径。"
    assert parsed["input_format"] == "第一行包含四个正整数 $N, M, S$。"
    assert parsed["output_format"] == "输出一行包含 $N$ 个整数。"
    assert parsed["hint"] == "$1 \\le N \\le 10^4$"
    assert len(parsed["samples"]) == 1
    assert parsed["samples"][0] == {"input": "4 6 1", "output": "0 2 5 6"}


def test_legacy_difficulty_alias_normalizes_to_new_name():
    """旧档位名「普及+/提高」应归一化到新档位「普及+/提高-」。

    改名后映射表**保留旧名作为历史别名**，历史题面 md（以及从旧数据导出的 md）
    导入时才能落到正确档位；否则取不到键 → difficulty 为 None，难度直接丢失。
    """
    from app.services.problem_markdown import normalize_difficulty

    # 旧名 → 新名
    assert normalize_difficulty("普及+/提高") == "普及+/提高-"
    # 新名自身保持稳定
    assert normalize_difficulty("普及+/提高-") == "普及+/提高-"
    # 同档位的其余别名也指向新名
    for alias in ("中等", "普及加", "green"):
        assert normalize_difficulty(alias) == "普及+/提高-", alias


def test_parse_markdown_with_legacy_difficulty_name():
    """端到端：题面里仍写旧名时，解析出来的难度是新的规范档位名。"""
    content = """
# 旧名难度题面

**难度**：普及+/提高

【题目描述】
内容。
"""
    parsed = parse_problem_markdown(content)
    assert parsed["difficulty"] == "普及+/提高-", parsed


def test_legacy_difficulty_still_matches_value_tables():
    """旧难度串在经验/贡献/排序表里仍能取到与新名相同的值。

    守住的回归：``adjust_experience_on_difficulty_change`` 直接用 DB 里的
    ``old_difficulty`` 查表（迁移未执行的存量数据、或部署窗口期内仍是旧串）。
    若表里没有旧串，``.get(old, 0)`` 会取到 0，delta 变成「凭空增发一整份经验」，
    且贡献值同样错算。
    """
    from app.services.judge import CONTRIBUTION_BY_DIFFICULTY, XP_BY_DIFFICULTY
    from app.services.problem import DIFFICULTY_RANKS

    old, new = "普及+/提高", "普及+/提高-"
    assert XP_BY_DIFFICULTY[old] == XP_BY_DIFFICULTY[new]
    assert CONTRIBUTION_BY_DIFFICULTY[old] == CONTRIBUTION_BY_DIFFICULTY[new]
    assert DIFFICULTY_RANKS[old] == DIFFICULTY_RANKS[new]


def test_write_side_difficulty_alias_is_normalized():
    """写侧（创建/更新 schema）也接受旧档位名，并归一化成规范名。

    守住的回归：滚动发布窗口期旧客户端仍提交旧串——若只在读侧保留别名、
    写侧直接走 pattern 校验，这些请求会被 422 拒掉；即便放行也会把旧串写进库，
    形成查表查不到的「幽灵档位」。
    """
    from app.schemas.problem import ProblemCreate, ProblemUpdate

    assert ProblemCreate(title="t", difficulty="普及+/提高").difficulty == "普及+/提高-"
    assert ProblemUpdate(difficulty="普及+/提高").difficulty == "普及+/提高-"
    # 规范名保持稳定
    assert ProblemCreate(title="t", difficulty="普及+/提高-").difficulty == "普及+/提高-"
    # 其余同档别名也归一化
    assert ProblemCreate(title="t", difficulty="中等").difficulty == "普及+/提高-"


def test_battle_tier_keeps_legacy_difficulty_alias():
    """对战段位题池保留旧档位名：部署窗口期内存量旧串题目不会被漏选。"""
    from app.services.battle import TIER_DIFFICULTIES, TIER_GOLD, TIER_PLATINUM

    assert "普及+/提高" in TIER_DIFFICULTIES[TIER_GOLD]
    assert "普及+/提高" in TIER_DIFFICULTIES[TIER_PLATINUM]
    assert "普及+/提高-" in TIER_DIFFICULTIES[TIER_GOLD]


def test_parse_hydro_polygon_tagged_samples():
    content = """
# A+B Problem

## Description
Calculate A + B.

## Input
Two numbers.

## Output
Sum.

## Samples
```input1
1 2
```
```output1
3
```
```input2
4 5
```
```output2
9
```
"""
    parsed = parse_problem_markdown(content)
    assert parsed["title"] == "A+B Problem"
    assert parsed["description"] == "Calculate A + B."
    assert parsed["input_format"] == "Two numbers."
    assert parsed["output_format"] == "Sum."
    assert len(parsed["samples"]) == 2
    assert parsed["samples"][0] == {"input": "1 2", "output": "3"}
    assert parsed["samples"][1] == {"input": "4 5", "output": "9"}


def test_parse_plain_text_fallback():
    content = """# 简单的加法
编写程序计算两个整数的和。
输入两个正整数，输出其和。"""
    parsed = parse_problem_markdown(content)
    assert parsed["title"] == "简单的加法"
    assert "编写程序计算两个整数的和。" in parsed["description"]


def test_export_and_reparse_roundtrip():
    original = {
        "title": "回文数判定",
        "difficulty": "入门",
        "time_limit": 1000,
        "memory_limit": 128,
        "source": "自拟",
        "tags": ["模拟", "字符串"],
        "background": "背景文本",
        "description": "判断一个整数是否为回文数。",
        "input_format": "一行一个整数。",
        "output_format": "YES 或 NO。",
        "hint": "注意负数不是回文数。",
        "samples": [
            {"input": "121", "output": "YES"},
            {"input": "-121", "output": "NO"},
        ],
    }
    exported = export_problem_markdown(original)
    re_parsed = parse_problem_markdown(exported)
    assert re_parsed["title"] == original["title"]
    assert re_parsed["difficulty"] == original["difficulty"]
    assert re_parsed["time_limit"] == original["time_limit"]
    assert re_parsed["memory_limit"] == original["memory_limit"]
    assert re_parsed["source"] == original["source"]
    assert re_parsed["tags"] == original["tags"]
    assert re_parsed["background"] == original["background"]
    assert re_parsed["description"] == original["description"]
    assert re_parsed["input_format"] == original["input_format"]
    assert re_parsed["output_format"] == original["output_format"]
    assert re_parsed["hint"] == original["hint"]
    assert re_parsed["samples"] == original["samples"]


@pytest.mark.asyncio
async def test_parse_markdown_api_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        auth_h = await _make_user(ac)

        # 未登录请求
        r = await ac.post("/problems/parse-markdown", json={"content": "# Test"})
        assert r.status_code == 401

        # 登录用户请求
        md = """---
title: "API测试题目"
difficulty: "普及-"
---
## 题目描述
测试API解析功能
"""
        r = await ac.post("/problems/parse-markdown", json={"content": md}, headers=auth_h)
        assert r.status_code == 200
        data = r.json()
        assert data["title"] == "API测试题目"
        assert data["difficulty"] == "普及-"
        assert data["description"] == "测试API解析功能"
