"""Database migration helper to ensure battle tables and columns exist in SQLite/Postgres."""

import asyncio
from sqlalchemy import text
from app.core.database import engine
from app.models.base import Base

async def init_battle_schema():
    async with engine.begin() as conn:
        # Create tables that are newly registered on Base.metadata
        await conn.run_sync(Base.metadata.create_all)

        # Check and add battle_id to submissions if missing (SQLite specific alter table)
        try:
            res = await conn.execute(text("PRAGMA table_info(submissions)"))
            columns = [row[1] for row in res.fetchall()]
            if "battle_id" not in columns:
                await conn.execute(text("ALTER TABLE submissions ADD COLUMN battle_id INTEGER REFERENCES battles(id) ON DELETE SET NULL"))
                print("Added column battle_id to submissions table")
            else:
                print("Column battle_id already exists in submissions table")
        except Exception as e:
            print(f"Schema check error (ignored on non-sqlite): {e}")

    print("Battle schema initialization completed!")

if __name__ == "__main__":
    asyncio.run(init_battle_schema())
