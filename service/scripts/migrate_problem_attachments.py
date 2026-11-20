"""迁移题目附件：从公开 static 目录搬到私密 storage/private 目录，
并把 DB 里的 stored_path 从 `/static/uploads/problems/{pid}/{uuid}.ext` 改成
仅存 `{uuid}.ext`（新下载接口按 problem_id + uuid 从私密目录取）。

用法：
  python scripts/migrate_problem_attachments.py --dry-run    # 仅打印不动任何东西
  python scripts/migrate_problem_attachments.py              # 实际执行

可重复跑：已经是新格式的行会自动跳过。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 让 scripts/ 下直接能 import app
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
import asyncio

from app.core.database import AsyncSessionLocal
from app.models.problem import ProblemAttachment

ROOT = Path(__file__).resolve().parent.parent
OLD_ROOT = ROOT / "static" / "uploads" / "problems"
# 目标目录直接复用运行时同一常量（_PRIVATE_ATTACH_DIR 内部按
# settings.ATTACHMENT_STORAGE_ROOT 解析），保证与 API 落盘目录一致，
# 生产用绝对路径挂载卷时也不会迁到错误目录
from app.api.problems import _PRIVATE_ATTACH_DIR as NEW_ROOT  # noqa: E402


async def run(dry_run: bool) -> None:
    moved = 0
    updated_rows = 0
    missing = 0
    skipped = 0

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(ProblemAttachment))).scalars().all()

        for att in rows:
            # 新格式：stored_path 已经是纯 uuid 文件名，跳过
            stored = (att.stored_path or "").strip()
            if not stored.startswith("/"):
                skipped += 1
                continue

            # 从旧路径里抽出 uuid 文件名
            fname = Path(stored).name
            if not fname:
                skipped += 1
                continue

            old_disk = OLD_ROOT / str(att.problem_id) / fname
            new_dir = NEW_ROOT / str(att.problem_id)
            new_disk = new_dir / fname

            if dry_run:
                print(
                    f"[dry-run] att#{att.id} problem#{att.problem_id} "
                    f"{stored} -> {new_disk}  exists={old_disk.is_file()}"
                )
                moved += 1
                continue

            # 迁移文件：存在才搬，新目录不存在就创建
            if old_disk.is_file() and not new_disk.is_file():
                new_dir.mkdir(parents=True, exist_ok=True)
                try:
                    old_disk.replace(new_disk)
                    moved += 1
                except OSError as e:
                    print(f"[warn] att#{att.id} 搬文件失败: {e}", file=sys.stderr)
                    missing += 1
                    continue
            elif old_disk.is_file() and new_disk.is_file():
                # 两边都有，老的直接删掉（已存在新位置）
                try:
                    old_disk.unlink(missing_ok=True)
                    moved += 1
                except OSError:
                    pass
            else:
                # 老位置也找不到，记一下但照样更新 DB（避免条目永远坏着）
                missing += 1

            att.stored_path = fname
            updated_rows += 1

        if updated_rows > 0:
            await db.commit()

    print(
        f"done. moved_files={moved} updated_rows={updated_rows} "
        f"skipped_new_format={skipped} missing_disk={missing} dry_run={dry_run}"
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    asyncio.run(run(dry_run=args.dry_run))
