"""校验数据库表结构是否与模型对齐（逐表逐列）。

正常部署用不着单独跑它 —— oj-up 第 4 步会执行。它先跑
`alembic upgrade head`（幂等），再把模型 metadata 里的每张表与库里
实际结构比对：缺表或缺列一律打 ✗ 并以非 0 退出。

为什么从「只查 follows」扩到全表：follows 缺列、users.color_tier 漏迁移
（b9f6648 没写迁移文件）这两次事故都是「oj-up 全程说成功、接口却成片
500」—— 校验只盯一张表时，别的表照样裸奔。现在模型里有的列，库里
少一个都别想部署过关。

顺带一提，老版本这里手写的 SQLite 方言 DDL（INTEGER PRIMARY KEY
AUTOINCREMENT）在 Postgres 上会直接语法报错，所以建表修复一律交给
迁移，脚本只做校验，不自己动表。

它做两件事：
  1. alembic upgrade head（幂等，已在 head 就空跑；失败只告警，不掩盖第 2 步）
  2. 按模型逐表逐列比对，缺表/缺列打 ✗ 并以非 0 退出

用法：
    cd service
    uv run python -m scripts.init_follows_table
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.core.database import engine
# 关键：from app.models import ... 会执行 app/models/__init__，
# 从而把所有模型模块跑一遍 —— 每个 Base 子类都注册进 metadata，
# 下面的逐表比对才有完整的表清单（漏 import 的模型 = 漏检的表）。
from app.models import Base

SERVICE_DIR = Path(__file__).resolve().parent.parent


def upgrade_to_head() -> None:
    """把迁移链推到最新。

    alembic 的 env.py 内部自己 asyncio.run，必须在事件循环外面调，
    所以这一步是同步的，和后面的异步校验分开。
    """
    command.upgrade(Config(str(SERVICE_DIR / "alembic.ini")), "head")


async def check_schema() -> bool:
    """按模型口径逐表比对，返回是否全部对齐。

    只看「模型有、库没有」这个方向：库里多出的列和历史遗留表是无害的，
    不拦部署；模型里有而库里没有的，相关接口一查就是 500，必须拦。
    """
    # 取 .name：迭代 columns 得到 Column 对象，直接当字符串比会在报错分支炸。
    expected = {
        t.name: [c.name for c in t.columns] for t in Base.metadata.sorted_tables
    }

    def _inspect(sync_conn):
        insp = inspect(sync_conn)
        existing = set(insp.get_table_names())
        return {
            name: [c["name"] for c in insp.get_columns(name)]
            for name in expected
            if name in existing
        }

    async with engine.connect() as conn:
        actual = await conn.run_sync(_inspect)

    problems: list[str] = []
    for name, want in expected.items():
        if name not in actual:
            problems.append(f"✗ 表 {name} 不存在 —— 迁移没跟上模型")
            continue
        missing = [c for c in want if c not in actual[name]]
        if missing:
            problems.append(f"✗ {name} 缺列：{', '.join(missing)} —— 相关接口会 500")

    if problems:
        for line in problems:
            print(line)
        return False

    print(f"✅ 全部 {len(expected)} 张表与模型对齐")
    return True


def main() -> int:
    try:
        upgrade_to_head()
    except Exception as exc:  # noqa: BLE001 —— CLI 兜底，迁移动静要给人看
        # 迁移失败不能掩盖「表结构到底对没对」这个核心问题：
        # 本地 oj.db 这种由 create_all 建起来的库，跑迁移本来就会撞已存在的表。
        print(f"⚠ alembic upgrade head 失败：{type(exc).__name__}: {exc}")
        print("   下面照样做结构校验，最终结果以校验为准。")
    return 0 if asyncio.run(check_schema()) else 1


if __name__ == "__main__":
    sys.exit(main())
