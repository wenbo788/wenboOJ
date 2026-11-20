"""评测服务：调用 go-judge 完成编译与逐测试点评测。

流程：提交创建后由 BackgroundTasks 触发 judge_submission()：
1. 状态置为 judging
2. 需要编译的语言先编译（copyOutCached 缓存二进制，复用于各测试点）
3. 逐测试点运行：stdin=测试点输入，stdout 与期望输出比对（忽略行尾空白与结尾换行）
4. 汇总状态 / 最大耗时 / 最大内存，回写提交行并更新题目统计
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from sqlalchemy import case, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.problem import Problem
from app.models.submission import Submission, TestCase
from app.models.user import User

logger = logging.getLogger(__name__)

_TESTLIB_PATH = Path(__file__).resolve().parent.parent / "resources" / "testlib.h"
_TESTLIB_CONTENT: str | None = None

def _get_testlib() -> str:
    global _TESTLIB_CONTENT
    if _TESTLIB_CONTENT is None:
        _TESTLIB_CONTENT = _TESTLIB_PATH.read_text(encoding="utf-8", errors="ignore") if _TESTLIB_PATH.exists() else ""
    return _TESTLIB_CONTENT

SPJ_LANGS: dict[str, dict[str, Any]] = {
    "cpp": {
        "source": "spj.cpp",
        "compile": ["g++", "-O2", "-std=c++17", "spj.cpp", "-o", "spj", "-lm"],
        "run": ["./spj", "in.txt", "out.txt", "ans.txt"],
        "binary": "spj",
    },
    "c": {
        "source": "spj.c",
        "compile": ["gcc", "-O2", "spj.c", "-o", "spj", "-lm"],
        "run": ["./spj", "in.txt", "out.txt", "ans.txt"],
        "binary": "spj",
    },
    "python3": {
        "source": "spj.py",
        "compile": None,
        "run": ["python3", "spj.py", "in.txt", "out.txt", "ans.txt"],
        "binary": None,
    },
}

LANGUAGES: dict[str, dict[str, Any]] = {
    "cpp": {
        "source": "main.cpp",
        "compile": ["g++", "-O2", "-std=c++14", "main.cpp", "-o", "main", "-lm"],
        "run": ["./main"],
        "binary": "main",
    },
    "c": {
        "source": "main.c",
        "compile": ["gcc", "-O2", "main.c", "-o", "main", "-lm"],
        "run": ["./main"],
        "binary": "main",
    },
    "python3": {
        "source": "main.py",
        "compile": None,
        "run": ["python3", "main.py"],
        "binary": None,
    },
}

_PLUGIN_PATH = Path("/usr/local/lib/oj/no_opt_pragma.so")


def _build_compile_cmd(base_args: list[str], language: str, *, with_plugin: bool = True) -> list[str]:
    """构建编译参数。若开启了插件支持且 with_plugin 为 True，则注入 -fplugin。"""
    cmd = list(base_args)
    if with_plugin and settings.ENABLE_NO_OPT_PRAGMA_PLUGIN and language in ("cpp", "c"):
        plugin_flag = f"-fplugin={_PLUGIN_PATH}"
        if plugin_flag not in cmd:
            # 插入在选项之后、源文件之前（倒数第四个参数前，倒数为: source, -o, binary, -lm）
            insert_idx = max(1, len(cmd) - 4)
            cmd.insert(insert_idx, plugin_flag)
    return cmd


# go-judge 状态 → 本站状态
SANDBOX_STATUS_MAP = {
    "Time Limit Exceeded": "time_limit_exceeded",
    "Memory Limit Exceeded": "memory_limit_exceeded",
    "Output Limit Exceeded": "runtime_error",
    "Runtime Error": "runtime_error",
    "Nonzero Exit Status": "runtime_error",
    "File Error": "runtime_error",
    "Internal Error": "system_error",
}

# go-judge 默认环境没有 PATH，g++ 会找不到 as/ld 链接器 → 必须显式提供
SANDBOX_ENV = ["PATH=/usr/local/bin:/usr/bin:/bin"]

# 汇总优先级：劣化方向（取整个提交的最差结果）
_SEVERITY = ["accepted", "wrong_answer", "runtime_error", "memory_limit_exceeded", "time_limit_exceeded"]

# 首次 AC 经验表（按难度等级递增，每题每用户仅一次）
XP_BY_DIFFICULTY = {
    "入门": 1,
    "普及-": 5,
    "普及": 10,
    "普及+/提高-": 100,
    # 历史别名：改名前的档位串。迁移未执行的存量数据、或部署窗口期内 DB 里
    # 仍可能是旧串——若表里没有它，adjust_experience_on_difficulty_change 的
    # `.get(old_difficulty, 0)` 会取到 0，delta 变成「凭空增发一整份经验」。
    # CONTRIBUTION_BY_DIFFICULTY 由本表派生，会自动继承该别名。
    "普及+/提高": 100,
    "提高": 200,
    "提高+/省选-": 500,
    "省选/NOI-": 900,
    "NOI/NOI+/CTSC": 1500,
    "暂无评定": 0,
}

async def adjust_experience_on_difficulty_change(
    db: AsyncSession, problem_id: int, old_difficulty: str, new_difficulty: str
) -> int:
    """题目难度变更时，重算所有首次 AC 该题用户的经验（返回受影响人数）。

    「每题每用户仅一次」——每个 AC 过该题的用户恰好拿过一次该难度的经验，
    故对差值 delta = XP(新) - XP(旧) 整体增减即可；难度多次改动的差值
    会自然抵消（A→B→A 净变化为 0）。
    """
    delta = (XP_BY_DIFFICULTY.get(new_difficulty, 0)
             - XP_BY_DIFFICULTY.get(old_difficulty, 0))
    if delta == 0:
        return 0
    prob = await db.get(Problem, problem_id)
    if prob and prob.team_id is not None:
        return 0
    ac_user_ids = (await db.execute(
        select(Submission.user_id).where(
            Submission.problem_id == problem_id,
            Submission.status == "accepted",
            # 虚拟参赛的 AC 不算「真通过」：难度调整补发/扣回经验时不该算他们
            Submission.virtual_contest_id.is_(None),
        ).distinct()
    )).scalars().all()
    if not ac_user_ids:
        return 0
    await db.execute(
        update(User)
        .where(User.id.in_(ac_user_ids))
        .values(experience=User.experience + delta)
    )
    await db.commit()
    logger.info("P%s 难度 %s → %s，%d 名 AC 用户经验 %+d",
                1000 + problem_id, old_difficulty, new_difficulty,
                len(ac_user_ids), delta)
    return len(ac_user_ids)


# 出题贡献表（经验表的 5 倍——出题比 AC 稀缺）。仅主题库题计入，
# 团队私有题的出题人可由团队管理员自行指派，计入会被自建团刷分。
CONTRIBUTION_BY_DIFFICULTY = {
    k: v * 5 for k, v in XP_BY_DIFFICULTY.items()
}

# 全站推荐专栏文章/题解奖励贡献值（相当于一道普及题的出题贡献）
RECOMMENDED_ARTICLE_CONTRIBUTION = 20


async def _add_contribution(db: AsyncSession, user_id: int, delta: int) -> None:
    """增减出题贡献，**下限为 0，不允许扣成负数**。

    为什么要有下限：用户拿到出题贡献后可能已经把它花掉了（贡献商店兑换
    Tag 卡、买用户名颜色），此后题目被删、换出题人、或难度调低，系统仍会
    按原难度把贡献扣回去，余额就被扣穿。贡献的语义是「出题攒了多少」，
    负余额既没意义，又会让人连最便宜的东西都兑换不了。

    下限用 CASE 写在 UPDATE 里（SQLite / MySQL 都支持），
    比「先查后写」少一次竞态。
    """
    if delta == 0:
        return
    new_value = case(
        (User.contribution + delta < 0, 0),
        else_=User.contribution + delta,
    )
    await db.execute(
        update(User).where(User.id == user_id).values(contribution=new_value)
    )


async def adjust_contribution_on_author_change(
    db: AsyncSession,
    old_author_id: int | None,
    new_author_id: int | None,
    old_difficulty: str,
    new_difficulty: str,
) -> None:
    """出题人变更时结清双方贡献：旧出题人按旧难度扣回，新出题人按新难度获得。

    新旧为同一人时不动（换难度走 adjust_contribution_on_difficulty_change）。
    """
    if new_author_id == old_author_id:
        return
    if old_author_id is not None:
        await _add_contribution(
            db, old_author_id, -CONTRIBUTION_BY_DIFFICULTY.get(old_difficulty, 0))
    if new_author_id is not None:
        await _add_contribution(
            db, new_author_id, CONTRIBUTION_BY_DIFFICULTY.get(new_difficulty, 0))
    await db.commit()


async def adjust_contribution_on_difficulty_change(
    db: AsyncSession, author_id: int | None,
    old_difficulty: str, new_difficulty: str,
) -> None:
    """题目难度变更时，同步调整出题人的贡献（差值增减，与经验同理）。"""
    if author_id is None:
        return
    delta = (CONTRIBUTION_BY_DIFFICULTY.get(new_difficulty, 0)
             - CONTRIBUTION_BY_DIFFICULTY.get(old_difficulty, 0))
    if delta == 0:
        return
    await _add_contribution(db, author_id, delta)
    await db.commit()


# 沙箱资源参数
COMPILE_CPU_NS = 30_000_000_000      # 编译 30s
COMPILE_MEMORY = 1_073_741_824       # 1GB
RUN_PROC_LIMIT = 64
STDOUT_MAX = 16 * 1024 * 1024        # 单点输出上限 16MB
STDERR_MAX = 1024 * 1024


def normalize_output(s: str) -> str:
    """比对前归一化：去掉每行行尾空白与结尾空行。"""
    lines = [line.rstrip() for line in s.replace("\r\n", "\n").split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def _worse(cur: str, new: str) -> str:
    """返回两者中更劣的状态。"""
    a = _SEVERITY.index(cur) if cur in _SEVERITY else len(_SEVERITY)
    b = _SEVERITY.index(new) if new in _SEVERITY else len(_SEVERITY)
    return new if b >= a else cur


class JudgeError(Exception):
    """评测致命错误（连接沙箱失败等）。"""


# ==================== 多评测机 / 故障切换 ====================
#
# 为什么切换粒度是「整次评测」而不是「每次请求挑一台」：
# 编译产物走 copyOutCached 拿到的 fileId 只存在于编译它的那台沙箱上，
# 后续每个测试点都靠这个 fileId 免去重复编译。若编译在 A 台、测试点跑在 B 台，
# B 台找不到 fileId，选手会收到莫名其妙的 Runtime Error / File Error。
# 所以主用那台连不上时，整份提交重跑一遍到备用那台。

# 端点 → 冷却截止时间（monotonic 秒）。挂掉的机器短时间内不再优先尝试，
# 免得主用瘫痪后每条提交都要先白等一次连接超时。
_ENDPOINT_DOWN_UNTIL: dict[str, float] = {}
# 端点 → 最近一次被判定故障的时刻。用来判断「本次成功」是否发生在故障之后：
# 两个协程并发时，A 刚把这台记为故障、B 的旧成功返回了，不能让它把故障抹掉。
_ENDPOINT_FAILED_AT: dict[str, float] = {}


def judge_endpoints() -> list[str]:
    """当前配置的全部评测机（主用在前）。"""
    return settings.go_judge_endpoints


def _ordered_endpoints() -> list[str]:
    """按「先健康的、再冷却中的」排序，各组内部保持配置顺序。"""
    now = time.monotonic()
    urls = judge_endpoints()
    healthy = [u for u in urls if _ENDPOINT_DOWN_UNTIL.get(u, 0.0) <= now]
    cooling = [u for u in urls if _ENDPOINT_DOWN_UNTIL.get(u, 0.0) > now]
    return healthy + cooling


def _mark_endpoint_down(url: str) -> None:
    cooldown = max(int(settings.GO_JUDGE_FAILOVER_COOLDOWN_SECONDS), 0)
    if cooldown <= 0:
        return
    now = time.monotonic()
    _ENDPOINT_FAILED_AT[url] = now
    _ENDPOINT_DOWN_UNTIL[url] = now + cooldown


def _mark_endpoint_up(url: str, *, started_at: float) -> None:
    """本次调用成功 → 解除冷却。

    ``started_at`` 是本次调用发起时刻：若期间**别的协程**刚把这台判为故障
    （失败时刻晚于本次发起），那是更新的信息，不能被这次成功抹掉。
    """
    if _ENDPOINT_FAILED_AT.get(url, 0.0) > started_at:
        return
    _ENDPOINT_DOWN_UNTIL.pop(url, None)
    _ENDPOINT_FAILED_AT.pop(url, None)


def reset_judge_health() -> None:
    """清空冷却记录（测试用；运维修好机器后也可据此立刻恢复优先顺序）。"""
    _ENDPOINT_DOWN_UNTIL.clear()
    _ENDPOINT_FAILED_AT.clear()


async def _with_failover(run, *, what: str, on_retry=None):
    """按「先健康、后冷却」的顺序依次尝试各评测机，第一台跑通即返回。

    ``run(base_url)`` 内部必须**整段只用传入的这一台**——编译产物 fileId 只
    存在于编译它的那台。连接类失败（JudgeError）会把这台打入冷却并换下一台；
    全部失败时抛出最后一个错误，由调用方决定怎么落库。

    ``on_retry`` 在「换下一台重跑之前」调用，供调用方清理自己的状态
    （评测路径用它把数据库会话退回干净事务，避免带着脏数据重跑）。
    """
    endpoints = _ordered_endpoints()
    last_error: JudgeError | None = None
    for idx, base in enumerate(endpoints):
        started_at = time.monotonic()
        try:
            result = await run(base)
        except JudgeError as exc:
            last_error = exc
            _mark_endpoint_down(base)
            nxt = endpoints[idx + 1] if idx + 1 < len(endpoints) else None
            if nxt is not None:
                logger.warning(
                    "%s：评测机 %s 不可用（%s），改用备用 %s", what, base, exc, nxt
                )
            else:
                logger.error(
                    "%s：全部评测机均不可用，最后一台 %s：%s", what, base, exc
                )
            if nxt is not None and on_retry is not None:
                await on_retry()
            continue
        _mark_endpoint_up(base, started_at=started_at)
        return result

    if last_error is None:  # 端点为空的配置错误
        raise JudgeError("未配置任何评测机（GO_JUDGE_URL 为空）")
    raise last_error


async def _run_cmd(client: httpx.AsyncClient, cmd: dict[str, Any]) -> dict[str, Any]:
    """在 ``client`` 绑定的那台评测机上执行一条命令。

    base_url 挂在 client 上（而不是每次拼 ``settings.GO_JUDGE_URL``），
    这样「一次提交固定用同一台」这件事由调用方建 client 时决定，
    也顺带让本函数不必关心到底配了几台评测机。
    """
    try:
        resp = await client.post("/run", json={"cmd": [cmd]})
        resp.raise_for_status()
        results = resp.json()
    except httpx.HTTPError as e:
        resp = getattr(e, "response", None)
        if resp is not None:
            logger.warning("Go-Judge 拒绝请求 (HTTP %s): %s", resp.status_code, resp.text)
        else:
            logger.warning("Go-Judge 连接异常: %s", e)
        raise JudgeError(f"无法连接评测沙箱: {e}") from e
    except Exception as e:
        logger.exception("Go-Judge 请求异常: %s", e)
        raise
    if not results:
        raise JudgeError("评测沙箱返回为空")
    return results[0]


async def _delete_file(client: httpx.AsyncClient, file_id: str) -> None:
    """删除编译缓存。必须删在「编译出它的那台」上，否则文件会一直留着。"""
    try:
        await client.delete(f"/file/{file_id}")
    except httpx.HTTPError:
        logger.warning("清理沙箱缓存文件失败: %s", file_id)


def _basic_files(input_data: str) -> list[dict[str, Any]]:
    """stdin = 测试点输入；stdout/stderr 用管道收集。"""
    safe_input = input_data if input_data is not None else ""
    return [
        {"content": safe_input},
        {"name": "stdout", "max": STDOUT_MAX},
        {"name": "stderr", "max": STDERR_MAX},
    ]


async def try_run(
    *,
    language: str,
    code: str,
    input_data: str,
    time_limit_ms: int,
    memory_mb: int,
) -> dict[str, Any]:
    """自测运行：编译（如需）+ 单次执行，返回沙箱状态与输出。

    与正式评测走同一 go-judge 沙箱、同一资源上限（按题目限制），
    供题目页「自测环境」端点调用。配了备用评测机时按序尝试，第一台跑通即返回；
    全部不可用才抛 JudgeError。
    """
    lang = LANGUAGES.get(language)
    if lang is None:
        raise JudgeError(f"不支持的语言: {language}")

    return await _with_failover(
        lambda base: _try_run_via(
            base, language=language, lang=lang, code=code, input_data=input_data,
            time_limit_ms=time_limit_ms, memory_mb=memory_mb,
        ),
        what="自测",
    )


async def _try_run_via(
    base_url: str,
    *,
    language: str,
    lang: dict[str, Any],
    code: str,
    input_data: str,
    time_limit_ms: int,
    memory_mb: int,
) -> dict[str, Any]:
    """在指定评测机上完成一次自测（编译 + 单次执行）。"""
    cpu_ns = max(int(time_limit_ms), 100) * 1_000_000
    mem_bytes = max(int(memory_mb), 16) * 1024 * 1024

    result: dict[str, Any] = {
        "status": "ok",
        "stdout": "",
        "stderr": "",
        "time_ms": None,
        "memory_kb": None,
        "detail": "",
    }
    # connect 单独收紧：主用是黑洞时（连不上也不 RST）不必等满 60s 才切备用
    async with httpx.AsyncClient(
        base_url=base_url, timeout=httpx.Timeout(60, connect=3)
    ) as client:
        binary_file_id: Optional[str] = None
        try:
            if lang["compile"]:
                compile_cmd = _build_compile_cmd(lang["compile"], language)
                res = await _run_cmd(client, {
                    "args": compile_cmd,
                    "env": SANDBOX_ENV,
                    "files": [{"content": ""}, {"name": "stdout", "max": STDERR_MAX},
                              {"name": "stderr", "max": STDERR_MAX}],
                    "copyIn": {lang["source"]: {"content": code}},
                    "copyOut": ["stdout", "stderr", lang["binary"]],
                    "copyOutCached": [lang["binary"]],
                    "cpuLimit": COMPILE_CPU_NS,
                    "memoryLimit": COMPILE_MEMORY,
                    "procLimit": RUN_PROC_LIMIT,
                })
                # 容错：若配置了插件但因环境缺失/版本不匹配导致报错，降级重试一次无插件编译
                if res.get("status") != "Accepted":
                    stderr_check = (res.get("files") or {}).get("stderr") or ""
                    if "-fplugin=" in " ".join(compile_cmd) and (
                        "no_opt_pragma.so" in stderr_check or "cannot load plugin" in stderr_check
                    ):
                        logger.warning("GCC 插件加载失败，自测环境自动降级为无插件编译: %s", stderr_check[:200])
                        fallback_cmd = _build_compile_cmd(lang["compile"], language, with_plugin=False)
                        res = await _run_cmd(client, {
                            "args": fallback_cmd,
                            "env": SANDBOX_ENV,
                            "files": [{"content": ""}, {"name": "stdout", "max": STDERR_MAX},
                                      {"name": "stderr", "max": STDERR_MAX}],
                            "copyIn": {lang["source"]: {"content": code}},
                            "copyOut": ["stdout", "stderr", lang["binary"]],
                            "copyOutCached": [lang["binary"]],
                            "cpuLimit": COMPILE_CPU_NS,
                            "memoryLimit": COMPILE_MEMORY,
                            "procLimit": RUN_PROC_LIMIT,
                        })

                if res.get("status") != "Accepted":
                    files = res.get("files") or {}
                    stderr = files.get("stderr") or ""
                    result["status"] = "compile_error"
                    if res.get("status") == "File Error" and not stderr.strip():
                        result["stderr"] = "编译器不可用：评测沙箱中找不到 g++/gcc"
                    else:
                        result["stderr"] = (stderr or files.get("stdout") or "编译失败")[:20_000]
                    return result
                binary_file_id = (res.get("fileIds") or {}).get(lang["binary"])

            copy_in: dict[str, Any] = (
                {lang["binary"]: {"fileId": binary_file_id}}
                if lang["binary"] and binary_file_id
                else {lang["source"]: {"content": code}}
            )
            res = await _run_cmd(client, {
                "args": lang["run"],
                "env": SANDBOX_ENV,
                "files": _basic_files(input_data),
                "copyIn": copy_in,
                "copyOut": ["stdout", "stderr"],
                "cpuLimit": cpu_ns,
                "memoryLimit": mem_bytes,
                "procLimit": RUN_PROC_LIMIT,
            })
            sb = res.get("status", "")
            files = res.get("files") or {}
            result["stdout"] = files.get("stdout") or ""
            result["stderr"] = files.get("stderr") or ""
            result["time_ms"] = int(res.get("time", 0) / 1_000_000)
            result["memory_kb"] = int(res.get("memory", 0) / 1024)
            if sb == "Accepted":
                result["status"] = "ok"
            else:
                result["status"] = SANDBOX_STATUS_MAP.get(sb, "runtime_error")
                result["detail"] = sb
            return result
        finally:
            if binary_file_id:
                await _delete_file(client, binary_file_id)


async def judge_submission(submission_id: int, *, is_rejudge: bool = False) -> None:
    """后台评测入口（自带数据库会话，由 BackgroundTasks 调用）。"""
    async with AsyncSessionLocal() as db:
        try:
            await _judge(db, submission_id, is_rejudge=is_rejudge)
        except Exception:
            logger.exception("评测提交 %s 失败", submission_id)
            # 兜底：先把会话退回干净事务再查库（异常可能把 session 留在需回滚状态，
            # 否则这一查就会抛 PendingRollbackError，提交永远停在 judging）
            await db.rollback()
            sub = (await db.execute(
                select(Submission).where(Submission.id == submission_id)
            )).scalar_one_or_none()
            if sub is not None and sub.status in ("pending", "judging"):
                sub.status = "system_error"
                sub.error_message = "评测系统内部错误，请稍后重试"
                await db.commit()


async def judge_submissions(
    submission_ids: list[int], *, is_rejudge: bool = False
) -> None:
    for submission_id in submission_ids:
        await judge_submission(submission_id, is_rejudge=is_rejudge)


async def _eval_case(
    client: httpx.AsyncClient,
    tc: TestCase,
    sub_code: str,
    lang: dict[str, Any],
    cpu_ns: int,
    mem_bytes: int,
    binary_file_id: Optional[str],
    is_spj: bool,
    spj_cfg: Optional[dict[str, Any]],
    spj_bin_id: Optional[str],
    spj_code: Optional[str],
) -> tuple[str, int, int, Optional[str]]:
    """运行单个测试点，返回 (case_status, case_time_ms, case_mem_kb, error_message)。"""
    safe_code = sub_code or ""
    copy_in: dict[str, Any] = (
        {lang["binary"]: {"fileId": binary_file_id}}
        if lang["binary"] else {lang["source"]: {"content": safe_code}}
    )
    res = await _run_cmd(client, {
        "args": lang["run"],
        "env": SANDBOX_ENV,
        "files": _basic_files(tc.input_data),
        "copyIn": copy_in,
        "copyOut": ["stdout", "stderr"],
        "cpuLimit": cpu_ns,
        "memoryLimit": mem_bytes,
        "procLimit": RUN_PROC_LIMIT,
    })

    sb_status = res.get("status", "")
    case_status = SANDBOX_STATUS_MAP.get(sb_status, "accepted")
    err_msg: Optional[str] = None

    if case_status == "accepted":
        stdout = (res.get("files") or {}).get("stdout") or ""
        if is_spj and spj_cfg:
            sin: dict[str, Any] = {
                "in.txt": {"content": tc.input_data or ""},
                "out.txt": {"content": stdout},
                "ans.txt": {"content": tc.expected_output or ""},
            }
            if spj_cfg["binary"]:
                sin[spj_cfg["binary"]] = {"fileId": spj_bin_id}
            else:
                sin[spj_cfg["source"]] = {"content": spj_code or ""}
            sres = await _run_cmd(client, {
                "args": spj_cfg["run"],
                "env": SANDBOX_ENV,
                "files": [
                    {"content": tc.input_data or ""},
                    {"name": "stdout", "max": 1024 * 1024},
                    {"name": "stderr", "max": 1024 * 1024},
                ],
                "copyIn": sin,
                "copyOut": ["stdout", "stderr"],
                "cpuLimit": 5_000_000_000,
                "memoryLimit": 512 * 1024 * 1024,
                "procLimit": RUN_PROC_LIMIT,
            })
            sst = sres.get("status", "")
            if sst != "Accepted":
                case_status = "wrong_answer"
                serr = (sres.get("files") or {}).get("stderr") or (sres.get("files") or {}).get("stdout") or ""
                if not serr.strip() and sst != "Nonzero Exit Status":
                    serr = f"Special Judge {sst}"
                if serr.strip():
                    err_msg = serr.strip()[:2000]
        elif normalize_output(stdout) != normalize_output(tc.expected_output):
            case_status = "wrong_answer"

    case_time_ms = int(res.get("time", 0) / 1_000_000)
    case_mem_kb = int(res.get("memory", 0) / 1024)

    if case_status == "runtime_error" and not err_msg:
        err = (res.get("files") or {}).get("stderr") or ""
        if err.strip():
            err_msg = err[:2000]

    return case_status, case_time_ms, case_mem_kb, err_msg


async def apply_submission_stats(
    db: AsyncSession, sub: Submission, problem: Problem, *, is_rejudge: bool = False
) -> None:
    """判题完成后的统计回写：提交数、首次 AC（题目通过数 + 经验）。

    **虚拟参赛整段跳过**：那是个人练习，不能白送经验、也不能把题目通过数抬高
    —— 否则真打比赛时反而不发「首次 AC」奖励。
    """
    if not is_rejudge and sub.virtual_contest_id is None:
        # 虚拟提交整段跳过统计（个人练习，不送经验、不抬题目通过数）
        # 统计回写：提交数 +1；首次 AC（该用户该题此前无 AC）则通过数 +1 并加经验
        problem.submit_count = (problem.submit_count or 0) + 1
        if sub.status == "accepted":
            prior_ac = (await db.execute(
                select(Submission.id).where(
                    Submission.problem_id == sub.problem_id,
                    Submission.user_id == sub.user_id,
                    Submission.status == "accepted",
                    Submission.id != sub.id,
                    Submission.virtual_contest_id.is_(None),
                ).limit(1)
            )).scalar_one_or_none()
            if prior_ac is None:
                problem.solved_count = (problem.solved_count or 0) + 1
                # 首次 AC 发经验（仅限主题库题目）
                if problem.team_id is None:
                    xp = XP_BY_DIFFICULTY.get(problem.difficulty, 0)
                    if xp > 0:
                        ac_user = await db.get(User, sub.user_id)
                        if ac_user is not None:
                            # 原子累加：并发「首次 AC」时读-改-写会丢更新，交给
                            # 数据库做 experience = experience + xp；
                            # synchronize_session="fetch" 让会话里的实例同步新值
                            await db.execute(
                                update(User)
                                .where(User.id == sub.user_id)
                                .values(experience=User.experience + xp)
                                .execution_options(synchronize_session="fetch")
                            )
                            logger.info("用户 %s 首次 AC P%s(%s) +%d 经验",
                                        ac_user.username, 1000 + sub.problem_id,
                                        problem.difficulty, xp)


async def _judge(
    db: AsyncSession, submission_id: int, *, is_rejudge: bool = False
) -> None:
    """评测一份提交；配了备用评测机时做故障切换（整份重跑，见 _with_failover）。"""

    async def _rollback_before_retry() -> None:
        """上一次尝试可能已改过 ORM 对象或把事务留在失败态，
        不清干净就重跑会撞 PendingRollbackError，或者带着上一台的脏改动继续。"""
        await db.rollback()

    try:
        await _with_failover(
            lambda base: _judge_via(
                db, submission_id, base, is_rejudge=is_rejudge
            ),
            what=f"评测提交 {submission_id}",
            on_retry=_rollback_before_retry,
        )
    except JudgeError as exc:
        # 先把会话退回干净事务，再查库落 system_error：
        # 前面的失败可能让 session 处于需回滚状态，不 rollback 会连查询都抛
        await db.rollback()
        sub = (await db.execute(
            select(Submission).where(Submission.id == submission_id)
        )).scalar_one_or_none()
        if sub is not None and sub.status in ("pending", "judging"):
            sub.status = "system_error"
            # 不要把评测机地址写进用户可见的 error_message（会泄露内网拓扑），
            # 具体是哪台、报了什么，留在服务端日志里（_with_failover 已记录）
            sub.error_message = (
                f"所有评测机均不可用（已尝试 {len(judge_endpoints())} 台），请稍后重试"
            )
            sub.judged_at = datetime.now(timezone.utc)
            await db.commit()


async def _judge_via(
    db: AsyncSession, submission_id: int, base_url: str, *, is_rejudge: bool = False
) -> None:
    """在指定评测机上完成整份评测（编译 + 全部测试点 + SPJ）。

    沙箱连不上时抛 JudgeError 交给上层切换；而编译错误 / SPJ 编译失败 /
    测试点 TLE 等都是**正常结果**，照常落库返回，不触发切换。
    """
    sub = (await db.execute(
        select(Submission).where(Submission.id == submission_id)
    )).scalar_one_or_none()
    if sub is None or sub.status not in ("pending", "judging"):
        return
    problem = (await db.execute(
        select(Problem).where(Problem.id == sub.problem_id)
    )).scalar_one_or_none()
    cases = (await db.execute(
        select(TestCase).where(TestCase.problem_id == sub.problem_id)
        .order_by(TestCase.sort_order.asc(), TestCase.id.asc())
    )).scalars().all()

    if problem is None or not cases:
        sub.status = "system_error"
        sub.error_message = "该题目暂无测试数据"
        await db.commit()
        return

    lang = LANGUAGES.get(sub.language)
    if lang is None:
        sub.status = "system_error"
        sub.error_message = f"不支持的语言: {sub.language}"
        await db.commit()
        return

    sub.status = "judging"
    await db.commit()

    spj_bin_id: Optional[str] = None
    spj_cfg = None
    if problem.is_spj:
        spj_key = problem.spj_language or "cpp"
        spj_cfg = SPJ_LANGS.get(spj_key)
        if spj_cfg is None:
            sub.status = "system_error"
            sub.error_message = f"不支持的 SPJ 语言: {spj_key}"
            sub.judged_at = datetime.now(timezone.utc)
            await db.commit()
            return
        if not (problem.spj_code or "").strip():
            sub.status = "system_error"
            sub.error_message = "该题目开启了 Special Judge 但未配置评测代码"
            sub.judged_at = datetime.now(timezone.utc)
            await db.commit()
            return

    cpu_ns = problem.time_limit * 1_000_000          # ms → ns
    mem_bytes = problem.memory_limit * 1024 * 1024   # MB → bytes

    results: list[dict[str, Any]] = []
    overall: str = "accepted"
    time_used = 0
    memory_used = 0
    error_message: Optional[str] = None
    binary_file_id: Optional[str] = None
    spj_bin_id: Optional[str] = None
    subtask_results: list[dict[str, Any]] | None = None

    try:
        # connect 单独收紧：主用是黑洞时（连不上也不 RST）不必等满 60s 才切备用
        async with httpx.AsyncClient(
            base_url=base_url, timeout=httpx.Timeout(60, connect=3)
        ) as client:
            # ---- 编译 ----
            if lang["compile"]:
                compile_cmd = _build_compile_cmd(lang["compile"], sub.language)
                res = await _run_cmd(client, {
                    "args": compile_cmd,
                    "env": SANDBOX_ENV,
                    "files": [{"content": ""}, {"name": "stdout", "max": STDERR_MAX},
                              {"name": "stderr", "max": STDERR_MAX}],
                    "copyIn": {lang["source"]: {"content": sub.code}},
                    "copyOut": ["stdout", "stderr", lang["binary"]],
                    "copyOutCached": [lang["binary"]],
                    "cpuLimit": COMPILE_CPU_NS,
                    "memoryLimit": COMPILE_MEMORY,
                    "procLimit": RUN_PROC_LIMIT,
                })
                # 容错：若配置了插件但因环境缺失/版本不匹配导致报错，降级重试一次无插件编译
                if res.get("status") != "Accepted":
                    stderr_check = (res.get("files") or {}).get("stderr") or ""
                    if "-fplugin=" in " ".join(compile_cmd) and (
                        "no_opt_pragma.so" in stderr_check or "cannot load plugin" in stderr_check
                    ):
                        logger.warning("GCC 插件加载失败，正式评测自动降级为无插件编译: %s", stderr_check[:200])
                        fallback_cmd = _build_compile_cmd(lang["compile"], sub.language, with_plugin=False)
                        res = await _run_cmd(client, {
                            "args": fallback_cmd,
                            "env": SANDBOX_ENV,
                            "files": [{"content": ""}, {"name": "stdout", "max": STDERR_MAX},
                                      {"name": "stderr", "max": STDERR_MAX}],
                            "copyIn": {lang["source"]: {"content": sub.code}},
                            "copyOut": ["stdout", "stderr", lang["binary"]],
                            "copyOutCached": [lang["binary"]],
                            "cpuLimit": COMPILE_CPU_NS,
                            "memoryLimit": COMPILE_MEMORY,
                            "procLimit": RUN_PROC_LIMIT,
                        })

                if res.get("status") != "Accepted":
                    sub.status = "compile_error"
                    stderr = (res.get("files") or {}).get("stderr") or ""
                    if res.get("status") == "File Error" and not stderr.strip():
                        # 沙箱里找不到编译器可执行文件 → 宿主机没装 g++/gcc
                        sub.error_message = (
                            "编译器不可用：评测沙箱中找不到 g++/gcc，"
                            "请联系管理员在宿主机安装编译器"
                        )
                    else:
                        sub.error_message = (stderr
                                             or (res.get("files") or {}).get("stdout")
                                             or "编译失败")[:20_000]
                    sub.judged_at = datetime.now(timezone.utc)
                    await db.commit()
                    return
                binary_file_id = (res.get("fileIds") or {}).get(lang["binary"])

            if problem.is_spj and spj_cfg and spj_cfg["compile"]:
                cin = {spj_cfg["source"]: {"content": problem.spj_code or ""}}
                tlib = _get_testlib()
                if tlib:
                    cin["testlib.h"] = {"content": tlib}
                sres = await _run_cmd(client, {
                    "args": spj_cfg["compile"],
                    "env": SANDBOX_ENV,
                    "files": [{"content": ""}, {"name": "stdout", "max": STDERR_MAX},
                              {"name": "stderr", "max": STDERR_MAX}],
                    "copyIn": cin,
                    "copyOut": ["stdout", "stderr", spj_cfg["binary"]],
                    "copyOutCached": [spj_cfg["binary"]],
                    "cpuLimit": COMPILE_CPU_NS,
                    "memoryLimit": COMPILE_MEMORY,
                    "procLimit": RUN_PROC_LIMIT,
                })
                if sres.get("status") != "Accepted":
                    sub.status = "system_error"
                    serr = (sres.get("files") or {}).get("stderr") or (sres.get("files") or {}).get("stdout") or "SPJ 编译失败"
                    sub.error_message = f"Special Judge 编译失败:\n{serr[:2000]}"
                    sub.judged_at = datetime.now(timezone.utc)
                    await db.commit()
                    return
                spj_bin_id = (sres.get("fileIds") or {}).get(spj_cfg["binary"])

            # ---- 逐测试点运行 ----
            has_subtasks = any(tc.subtask_id is not None for tc in cases) or bool(problem.subtask_config)
            subtask_results: list[dict[str, Any]] | None = None

            if not has_subtasks:
                for i, tc in enumerate(cases, start=1):
                    c_status, c_time, c_mem, c_err = await _eval_case(
                        client, tc, sub.code, lang, cpu_ns, mem_bytes,
                        binary_file_id, problem.is_spj, spj_cfg, spj_bin_id, problem.spj_code
                    )
                    results.append({
                        "case": i,
                        "status": c_status,
                        "time": c_time,
                        "memory": c_mem,
                    })
                    overall = _worse(overall, c_status)
                    time_used = max(time_used, c_time)
                    memory_used = max(memory_used, c_mem)
                    if c_err and not error_message:
                        error_message = c_err
                    if overall == "time_limit_exceeded":
                        break
                sub.status = overall
                sub.score = 100 if overall == "accepted" else 0
            else:
                # 子任务（捆绑测试）评测
                cfg_map: dict[int, dict[str, Any]] = {}
                ordered_st_ids: list[int] = []
                if problem.subtask_config and isinstance(problem.subtask_config, list):
                    for item in problem.subtask_config:
                        if isinstance(item, dict) and "id" in item:
                            sid = int(item["id"])
                            cfg_map[sid] = item
                            if sid not in ordered_st_ids:
                                ordered_st_ids.append(sid)

                for tc in cases:
                    sid = tc.subtask_id if tc.subtask_id is not None else 1
                    if sid not in ordered_st_ids:
                        ordered_st_ids.append(sid)

                st_cases_map: dict[int, list[TestCase]] = {sid: [] for sid in ordered_st_ids}
                for tc in cases:
                    sid = tc.subtask_id if tc.subtask_id is not None else (ordered_st_ids[0] if ordered_st_ids else 1)
                    if sid not in st_cases_map:
                        st_cases_map[sid] = []
                    st_cases_map[sid].append(tc)

                n_st = len(ordered_st_ids)
                default_score_per_st = 100 // n_st if n_st > 0 else 0
                st_scores: dict[int, int] = {}
                for idx, sid in enumerate(ordered_st_ids):
                    cfg = cfg_map.get(sid, {})
                    if "score" in cfg and cfg["score"] is not None:
                        st_scores[sid] = int(cfg["score"])
                    else:
                        tc_score = next((tc.subtask_score for tc in st_cases_map[sid] if tc.subtask_score is not None), None)
                        if tc_score is not None:
                            st_scores[sid] = int(tc_score)
                        else:
                            if idx == n_st - 1:
                                st_scores[sid] = max(0, 100 - sum(st_scores.values()))
                            else:
                                st_scores[sid] = default_score_per_st

                subtask_results = []
                total_score = 0
                overall = "accepted"
                global_case_i = 1

                for sid in ordered_st_ids:
                    cur_cases = st_cases_map.get(sid, [])
                    st_name = cfg_map.get(sid, {}).get("name") or f"Subtask #{sid}"
                    st_max_score = st_scores.get(sid, 0)
                    st_status = "accepted"
                    st_time = 0
                    st_mem = 0
                    st_case_results = []
                    subtask_tle = False

                    for tc in cur_cases:
                        if subtask_tle:
                            case_res = {
                                "case": global_case_i,
                                "subtask_id": sid,
                                "status": "skipped",
                                "time": 0,
                                "memory": 0,
                            }
                            results.append(case_res)
                            st_case_results.append(case_res)
                            global_case_i += 1
                            continue

                        c_status, c_time, c_mem, c_err = await _eval_case(
                            client, tc, sub.code, lang, cpu_ns, mem_bytes,
                            binary_file_id, problem.is_spj, spj_cfg, spj_bin_id, problem.spj_code
                        )
                        case_res = {
                            "case": global_case_i,
                            "subtask_id": sid,
                            "status": c_status,
                            "time": c_time,
                            "memory": c_mem,
                        }
                        results.append(case_res)
                        st_case_results.append(case_res)
                        global_case_i += 1

                        st_status = _worse(st_status, c_status)
                        overall = _worse(overall, c_status)
                        st_time = max(st_time, c_time)
                        st_mem = max(st_mem, c_mem)
                        time_used = max(time_used, c_time)
                        memory_used = max(memory_used, c_mem)
                        if c_err and not error_message:
                            error_message = c_err
                        if c_status == "time_limit_exceeded":
                            subtask_tle = True

                    st_earned = st_max_score if (st_status == "accepted" and cur_cases) else 0
                    total_score += st_earned
                    subtask_results.append({
                        "subtask_id": sid,
                        "name": st_name,
                        "score": st_earned,
                        "total_score": st_max_score,
                        "status": st_status if cur_cases else "accepted",
                        "time": st_time,
                        "memory": st_mem,
                        "cases": st_case_results,
                    })

                all_passed = all(st["status"] == "accepted" for st in subtask_results) if subtask_results else False
                if all_passed:
                    sub.status = "accepted"
                    sub.score = total_score
                elif total_score > 0:
                    sub.status = "partially_correct"
                    sub.score = total_score
                else:
                    sub.status = overall if overall != "accepted" else "wrong_answer"
                    sub.score = 0
    except JudgeError:
        # 不在这一层吞掉：交给 _with_failover 换下一台重跑整份提交。
        # finally 里的缓存清理仍会执行，且用的是同一台 base_url。
        raise
    finally:
        async with httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(10)) as c:
            if binary_file_id:
                await _delete_file(c, binary_file_id)
            if spj_bin_id:
                await _delete_file(c, spj_bin_id)

    sub.time_used = time_used or None
    sub.memory_used = memory_used or None
    sub.error_message = error_message
    sub.test_results = results
    sub.subtask_results = subtask_results
    sub.judged_at = datetime.now(timezone.utc)

    await apply_submission_stats(db, sub, problem, is_rejudge=is_rejudge)

    # 1v1 对战联动：若此提交属于进行中的对战且率先 AC，触发结算获胜。
    # 必须只在**非重判**时执行 —— 重判会把同一场的胜负再结算一遍。
    if not is_rejudge:
        try:
            from app.services.battle import check_submission_for_battle
            await check_submission_for_battle(db, sub)
        except Exception as e:
            logger.warning("对战判题状态联动触发异常: %s", e)

    await db.commit()
