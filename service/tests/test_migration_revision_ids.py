"""迁移 revision id 必须塞得进 alembic_version.version_num（VARCHAR 32）。

alembic 把当前版本号写进 alembic_version.version_num，该列是 VARCHAR(32)
（alembic 的官方约定）。revision id 超过 32 字符时：

  - PostgreSQL 严格截断 → 写版本号报 StringDataRightTruncationError，
    迁移整体回滚，oj-up 停在第 3 步；
  - SQLite 不强制 VARCHAR 长度 → 本地验证一路放行。

add_column_interactions_updated_at（34 字符）就是这么在生产炸掉后改名成
add_likes_stars_updated_at（26 字符）的 —— 这条测试把教训钉死。
"""

import re
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

VERSIONS_DIR = Path(__file__).resolve().parent.parent / "alembic" / "versions"
LIMIT = 32

# 兼容 `revision = "x"` 与 `revision: str = "x"` 两种写法
_REVISION_RE = re.compile(r'^revision(?::\s*str)?\s*=\s*["\']([^"\']+)["\']', re.M)


def test_revision_ids_fit_varchar32():
    too_long = []
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        match = _REVISION_RE.search(path.read_text(encoding="utf-8"))
        if match and len(match.group(1)) > LIMIT:
            too_long.append((path.name, match.group(1), len(match.group(1))))
    assert not too_long, (
        f"revision id 超过 {LIMIT} 字符，生产 alembic_version 会写入失败：{too_long}"
    )


def test_single_revision_head():
    """迁移链必须只有一个链头。

    多链头时 `alembic upgrade head` 直接拒绝执行并报
    “Multiple head revisions are present”，oj-up 第 3 步（对齐数据库）
    必挂、站点不敢继续部署。踩过两次（双链头 → 三链头），这条把教训钉死：
    新迁移的 down_revision 要指向现有链头；已有并列链头时用元组合流。
    """
    ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
    script = ScriptDirectory.from_config(Config(str(ini_path)))
    heads = script.get_heads()
    assert len(heads) == 1, (
        f"存在多个 alembic 链头：{heads}。新迁移的 down_revision 应指向"
        "现有链头，或用元组同时挂在多个并列链头之后把链收成单头。"
    )
