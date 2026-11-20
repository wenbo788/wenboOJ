"""提交查重：把两份代码「归一化 → 切成 k-gram 集合 → 算 Jaccard」。

思路和 MOSS 那类工具的最小版本一致：**不追求语义等价**，只抓
「结构上抄得太多」——把易变的部分（注释、空白、变量名、字面量）抹掉，
剩下的 token 序列如果大段相同，就是可疑。

刻意保守：
- 只看**同一题 + 同一语言**的提交（跨题/跨语言比没有意义，误报率还高）；
- 结果只是**提示**，不自动判罚；阈值可由管理员调；
- 太小/太短的代码不参与（`MIN_TOKENS`），避免「所有 A+B 题解都像」这种误报。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

# k-gram 的窗口大小：5 个 token 大约等价于一行短语句子，太短会误报、
# 太长会漏掉「改了一行」的抄袭。
SHINGLE_SIZE = 5

# 少于这么多 token 的提交直接跳过（Hello World 级别的代码没有查重价值，
# 而且会把「所有最短解」两两判成一样）。
MIN_TOKENS = 30

# C 系 / Java / JS 等的注释；Python、Shell、Ruby 用 #；SQL 用 --。
_C_LIKE = {
    "c", "cpp", "c++", "cxx", "cc", "objc",
    "java", "javascript", "typescript", "js", "ts",
    "csharp", "cs", "go", "rust", "php", "kotlin", "swift", "scala", "dart",
}
_HASH_COMMENT = {"python", "python3", "py", "pypy3", "ruby", "shell", "bash", "sh", "perl"}
_DASH_COMMENT = {"sql", "mysql", "pascal", "delphi"}

_STRING_RE = re.compile(r"""('(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*")""", re.S)
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")
_HASH_COMMENT_RE = re.compile(r"#[^\n]*")
_DASH_COMMENT_RE = re.compile(r"--[^\n]*")

_TOKEN_RE = re.compile(
    r"""
    (?P<str>'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*")   # 字符串字面量
    | (?P<num>\d+(?:\.\d+)?)                        # 数字
    | (?P<ident>[A-Za-z_][A-Za-z_0-9]*)             # 标识符 / 关键字
    | (?P<punct>\S)                                 # 其余非空白字符（运算符、括号…）
    """,
    re.X,
)


@dataclass(frozen=True)
class Fingerprint:
    """一份代码的指纹：k-gram 的哈希集合 + token 数。"""

    shingles: frozenset[int]
    token_count: int

    @property
    def usable(self) -> bool:
        return self.token_count >= MIN_TOKENS


def strip_comments(code: str, language: str) -> str:
    """去掉注释，保留字符串字面量（字面量里的 ``//`` ``#`` 不算注释）。"""
    lang = (language or "").strip().lower()

    # 先把字符串替换成占位符，避免把 "http://x" 里的 // 当注释。
    # 只在这一步处理带语言的注释，最后还要还原字面量。
    literals: list[str] = []

    def _stash(m: re.Match) -> str:
        literals.append(m.group(0))
        return f"\x00{len(literals) - 1}\x00"

    stashed = _STRING_RE.sub(_stash, code)

    if lang in _C_LIKE:
        stashed = _BLOCK_COMMENT_RE.sub(" ", stashed)
        stashed = _LINE_COMMENT_RE.sub(" ", stashed)
    elif lang in _HASH_COMMENT:
        stashed = _HASH_COMMENT_RE.sub(" ", stashed)
    elif lang in _DASH_COMMENT:
        stashed = _DASH_COMMENT_RE.sub(" ", stashed)
    else:
        # 未知语言：两种都去掉（宁可信其有；注释不影响 token 结构）
        stashed = _BLOCK_COMMENT_RE.sub(" ", stashed)
        stashed = _LINE_COMMENT_RE.sub(" ", stashed)
        stashed = _HASH_COMMENT_RE.sub(" ", stashed)

    def _restore(m: re.Match) -> str:
        return literals[int(m.group(1))]

    return re.sub(r"\x00(\d+)\x00", _restore, stashed)


def tokenize(code: str, language: str) -> list[str]:
    """归一化成 token 序列：标识符→V、数字→N、字符串→S，其余原样。"""
    text = strip_comments(code, language)
    tokens: list[str] = []
    for m in _TOKEN_RE.finditer(text):
        if m.group("str") is not None:
            tokens.append("S")
        elif m.group("num") is not None:
            tokens.append("N")
        elif m.group("ident") is not None:
            # 关键字也一视同仁地变成 V：查重看的是结构，
            # 而「把变量名全改一遍」正是最常见的伪装手段。
            tokens.append("V")
        else:
            tokens.append(m.group("punct"))
    return tokens


def fingerprint(code: str, language: str) -> Fingerprint:
    tokens = tokenize(code, language)
    if not tokens:
        return Fingerprint(frozenset(), 0)
    if len(tokens) < SHINGLE_SIZE:
        return Fingerprint(frozenset([_hash(tokens)]), len(tokens))
    shingles = {
        _hash(tokens[i:i + SHINGLE_SIZE])
        for i in range(len(tokens) - SHINGLE_SIZE + 1)
    }
    return Fingerprint(frozenset(shingles), len(tokens))


def _hash(chunk: list[str]) -> int:
    digest = hashlib.blake2b(" ".join(chunk).encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big")


def similarity(a: Fingerprint, b: Fingerprint) -> float:
    """两个指纹的 Jaccard 相似度（0..1）。"""
    if not a.shingles or not b.shingles:
        return 0.0
    inter = len(a.shingles & b.shingles)
    union = len(a.shingles | b.shingles)
    return inter / union if union else 0.0


def compare(code_a: str, lang_a: str, code_b: str, lang_b: str) -> float:
    """便捷入口：直接比两份源码（同语言才有意义，调用方负责过滤）。"""
    return similarity(fingerprint(code_a, lang_a), fingerprint(code_b, lang_b))


# ===================== 落库扫描（需要 DB） =====================
# 纯算法在上面；下面这部分把「范围内所有提交两两比对 + 结果落库」串起来。
# 为了让纯算法可单测，DB 相关的导入都放在函数内部。

DEFAULT_THRESHOLD = 0.8
# 同题同语言最多比这么多份提交：两两比较是 O(n²)，一份比赛题提交上百份就够翻一遍了，
# 再多会把这个接口自己拖成事故。
MAX_GROUP_SIZE = 300
# 一次扫描最多读这么多提交（防「按题目扫全站」把内存打满）
MAX_TOTAL_SUBMISSIONS = 2000


@dataclass
class SimilarPair:
    """扫描结果里的一对（尚未落库）。"""

    a_id: int
    b_id: int
    score: float
    detail: dict


async def scan_and_store(
    db,
    *,
    contest_id: int | None = None,
    problem_id: int | None = None,
    threshold: float = DEFAULT_THRESHOLD,
) -> dict:
    """扫描一个范围（比赛优先，否则单题）内同题同语言的提交两两比对，结果落库。

    覆盖写：同一范围的旧结果先删掉再写，避免阈值调小后残留过期命中。
    """
    from sqlalchemy import delete, select

    from app.models.plagiarism import SimilarSubmissionPair
    from app.models.submission import Submission

    if contest_id is None and problem_id is None:
        raise ValueError("必须指定 contest_id 或 problem_id")

    if threshold < 0.1 or threshold > 1.0:
        raise ValueError("阈值需在 0.1~1.0 之间")

    stmt = select(
        Submission.id, Submission.user_id, Submission.problem_id,
        Submission.language, Submission.code,
    )
    if contest_id is not None:
        stmt = stmt.where(Submission.contest_id == contest_id)
    elif problem_id is not None:
        stmt = stmt.where(Submission.problem_id == problem_id)
    rows = (await db.execute(
        stmt.order_by(Submission.id).limit(MAX_TOTAL_SUBMISSIONS)
    )).all()

    # 按 (题目, 语言) 分组 —— 跨题/跨语言比没有意义，误报率还高
    groups: dict[tuple[int, str], list] = {}
    for row in rows:
        key = (row.problem_id, (row.language or "").lower())
        groups.setdefault(key, []).append(row)

    pairs: list[SimilarPair] = []
    for (pid, _lang), members in groups.items():
        # 先按人只留一份（最早的那份），再按 MAX_GROUP_SIZE 截断：
        # 同一个人多份提交本来就不参与两两比较，但如果不先去重，一个刷提交的
        # 用户会把这 300 个名额占满，把别人的提交挤出去 → 漏检。
        seen_users: set[int] = set()
        deduped = []
        for m in members:
            if m.user_id in seen_users:
                continue
            seen_users.add(m.user_id)
            deduped.append(m)
        members = deduped[:MAX_GROUP_SIZE]
        fps = [
            (m, fingerprint(m.code or "", m.language or ""))
            for m in members
        ]
        for i in range(len(fps)):
            a, fa = fps[i]
            if not fa.usable:
                continue
            for j in range(i + 1, len(fps)):
                b, fb = fps[j]
                if not fb.usable or a.user_id == b.user_id:
                    continue
                score = similarity(fa, fb)
                if score < threshold:
                    continue
                a_id, b_id = (a.id, b.id) if a.id < b.id else (b.id, a.id)
                pairs.append(SimilarPair(
                    a_id=a_id, b_id=b_id, score=round(score, 4),
                    detail={
                        "problem_id": pid,
                        "language": a.language,
                        "shingles_a": len(fa.shingles),
                        "shingles_b": len(fb.shingles),
                        "tokens_a": fa.token_count,
                        "tokens_b": fb.token_count,
                        "threshold": threshold,
                        "k": SHINGLE_SIZE,
                    },
                ))

    # 覆盖写：先清掉这一范围的旧结果（scope 唯一标识「哪一次扫描范围」）。
    # 「删除 + 批量插入」必须是一个显式事务：中途任何异常都要回滚，别把这一
    # 范围的旧结果删了却只写进一半新结果（管理员会以为已经扫过了）。
    scope = f"contest:{contest_id}" if contest_id is not None else f"problem:{problem_id}"
    try:
        await db.execute(delete(SimilarSubmissionPair).where(
            SimilarSubmissionPair.scope == scope))

        for p in pairs:
            detail = dict(p.detail)
            detail.setdefault("contest_id", contest_id)
            db.add(SimilarSubmissionPair(
                scope=scope,
                contest_id=contest_id,
                problem_id=detail["problem_id"],
                submission_a_id=p.a_id,
                submission_b_id=p.b_id,
                score=p.score,
                detail=detail,
            ))
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return {
        "scanned": len(rows),
        # 提交总数超过上限时会被截断：告诉调用方「这次没扫全」，
        # 否则管理员会把「只扫了前 2000 份」当成全量结果。
        "truncated": len(rows) >= MAX_TOTAL_SUBMISSIONS,
        "groups": len(groups),
        "pairs": len(pairs),
        "threshold": threshold,
        "contest_id": contest_id,
        "problem_id": problem_id,
    }
