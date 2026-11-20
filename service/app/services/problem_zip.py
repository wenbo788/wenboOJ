"""题目 ZIP 压缩包解析服务。

支持导入包含题面 Markdown 与测试数据文件夹的 ZIP 压缩包：
1. 自动寻找题面 Markdown（如 problem.md / README.md / 根目录下 .md 文件）
2. 提取并使用 parse_problem_markdown 解析题面各分节及元数据
3. 自动识别并提取测试点（.in 与 .out / .ans 成对文件），兼容各类命名规范：
   - 扁平目录：1.in/1.out, data1.in/data1.out, test1.in/test1.ans 等
   - 文件夹组织：testdata/1.in, testcases/1.in, data/1.in 等
   - 子任务目录：subtask1/1.in, sub1/1.in, st1/1.in, 1/1.in 等
   - 包含子任务命名的文件名：subtask1_1.in, 1-1.in 等
   - 非数字命名兼容：sample.in/sample.out 等
   - 智能成对匹配（针对 input1.in 与 output1.out 等）
4. 自动检测子任务并计算分值分配（subtask_config）
5. 支持从压缩包提取内嵌图片资源并重写题面相对路径
"""

from __future__ import annotations

import io
import os
import re
import uuid
import zipfile as zf
from pathlib import Path
from typing import Any, Optional

from app.services.problem_markdown import parse_problem_markdown

ZIP_MAX_UPLOAD = 50 * 1024 * 1024       # 50 MB 上传大小限制
ZIP_MAX_FILE = 50 * 1024 * 1024         # 单文件解压后不超过 50 MB
ZIP_MAX_TOTAL = 100 * 1024 * 1024       # 100 MB 解压后总大小限制
MAX_TEST_CASES = 100                    # 最多 100 个测试点


class ZipDecompressTracker:
    """跟踪 ZIP 解压过程中的文件大小与累计解压量，防范 Zip Bomb。"""

    def __init__(self, max_file: int = ZIP_MAX_FILE, max_total: int = ZIP_MAX_TOTAL):
        self.max_file = max_file
        self.max_total = max_total
        self.total_uncompressed = 0

    def read_member(self, archive: zf.ZipFile, info: zf.ZipInfo) -> bytes:
        raw = archive.read(info)
        if len(raw) > self.max_file:
            raise ValueError(f"文件 {info.filename} 解压后过大")
        self.total_uncompressed += len(raw)
        if self.total_uncompressed > self.max_total:
            raise ValueError("解压后总大小不能超过 100MB")
        return raw

_NAME_RE = re.compile(r"^([^0-9]*)([0-9]+)$")
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "uploads" / "images"


def is_ignored_path(path_str: str) -> bool:
    """检查文件是否为操作系统临时文件或隐藏文件。"""
    name = path_str.replace("\\", "/").strip("/")
    if not name or "/." in name or name.startswith(".") or "__MACOSX" in name:
        return True
    if name.endswith(".DS_Store"):
        return True
    return False


def decode_zip_text(data: bytes) -> str:
    """安全解码 zip 内的文本文件，优先 utf-8，回退 gbk / cp936 / utf-16。"""
    for enc in ("utf-8", "gbk", "cp936", "utf-16"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def parse_zip_case_entry(filename: str) -> tuple[Optional[int], tuple, str, str] | None:
    """解析 zip 内的测试点路径，返回 (subtask_id, sort_key, ext, display_name) 或 None。"""
    if is_ignored_path(filename):
        return None
    name = filename.replace("\\", "/").strip("/")
    base = name.split("/")[-1]
    if not base or "." not in base:
        return None
    ext = base.rsplit(".", 1)[-1].lower()
    if ext not in ("in", "out", "ans"):
        return None
    normalized_ext = "out" if ext == "ans" else ext
    stem = base.rsplit(".", 1)[0].strip()

    # 1. 检查目录是否有 subtask 标识（例如 subtask1/1.in, 1/1.in）
    dirs = [d for d in name.split("/")[:-1] if d]
    subtask_id: Optional[int] = None
    if dirs:
        last_dir = dirs[-1]
        m_dir = re.fullmatch(r"(?:subtask|sub|st)?_?([0-9]+)", last_dir, re.IGNORECASE)
        if m_dir:
            subtask_id = int(m_dir.group(1))

    # 2. 检查文件名 stem（形如 subtask1_1, 1-1, 1_1, sub1-2）
    m_stem_sub = re.fullmatch(r"(?:subtask|sub|st)?_?([0-9]+)[-_.]\s*([0-9]+)", stem, re.IGNORECASE)
    if m_stem_sub:
        if subtask_id is None:
            subtask_id = int(m_stem_sub.group(1))
        sort_key = (subtask_id or 0, "", int(m_stem_sub.group(2)))
        return (subtask_id, sort_key, normalized_ext, f"subtask{subtask_id}_{m_stem_sub.group(2)}")

    # 3. 形如 subtask1_data2
    m_stem_sub2 = re.fullmatch(r"(?:subtask|sub|st)_?([0-9]+)[-_](.*?)([0-9]+)", stem, re.IGNORECASE)
    if m_stem_sub2:
        if subtask_id is None:
            subtask_id = int(m_stem_sub2.group(1))
        sort_key = (subtask_id or 0, m_stem_sub2.group(2), int(m_stem_sub2.group(3)))
        return (subtask_id, sort_key, normalized_ext, f"subtask{subtask_id}_{m_stem_sub2.group(2)}{m_stem_sub2.group(3)}")

    # 4. 普通命名：1, data1, test_1
    m_norm = _NAME_RE.fullmatch(stem)
    if m_norm:
        sort_key = (subtask_id or 0, m_norm.group(1), int(m_norm.group(2)))
        raw_prefix = f"subtask{subtask_id}/" if subtask_id is not None else ""
        return (subtask_id, sort_key, normalized_ext, f"{raw_prefix}{m_norm.group(1)}{m_norm.group(2)}")

    # 5. 回退命名：包含尾部数字，如 a1b2 或纯字母 sample
    m_any_num = re.search(r"(\d+)$", stem)
    if m_any_num:
        prefix = stem[:m_any_num.start()]
        num = int(m_any_num.group(1))
        sort_key = (subtask_id or 0, prefix, num)
    else:
        sort_key = (subtask_id or 0, stem, 0)
    raw_prefix = f"subtask{subtask_id}/" if subtask_id is not None else ""
    return (subtask_id, sort_key, normalized_ext, f"{raw_prefix}{stem}")


def locate_problem_markdown(archive: zf.ZipFile, infos: list[zf.ZipInfo]) -> zf.ZipInfo:
    """在压缩包中查找最符合条件的 Markdown 题面文件。"""
    md_candidates: list[zf.ZipInfo] = []
    for info in infos:
        if is_ignored_path(info.filename) or info.is_dir():
            continue
        norm_name = info.filename.replace("\\", "/").strip("/")
        base = norm_name.split("/")[-1].lower()
        if base.endswith((".md", ".markdown")):
            md_candidates.append(info)

    if not md_candidates:
        raise ValueError("压缩包内未找到题目 Markdown 题面文件（.md）")

    def _priority(info: zf.ZipInfo) -> tuple[int, int, int]:
        norm_name = info.filename.replace("\\", "/").strip("/")
        base = norm_name.split("/")[-1].lower()
        depth = norm_name.count("/")
        length = len(norm_name)

        if base == "problem.md":
            rank = 1
        elif base == "readme.md":
            rank = 2
        elif base in ("statement.md", "题面.md"):
            rank = 3
        elif base == "index.md":
            rank = 4
        else:
            rank = 5

        return (rank, depth, length)

    md_candidates.sort(key=_priority)
    return md_candidates[0]


def _extract_images_from_zip(
    archive: zf.ZipFile,
    infos: list[zf.ZipInfo],
    tracker: ZipDecompressTracker | None = None,
) -> dict[str, str]:
    """提取压缩包内的图片并保存到静态资源目录，返回相对路径到静态 URL 的映射字典。"""
    active_tracker = tracker or ZipDecompressTracker()
    image_map: dict[str, str] = {}
    for info in infos:
        if is_ignored_path(info.filename) or info.is_dir():
            continue
        norm_name = info.filename.replace("\\", "/").strip("/")
        _, ext = os.path.splitext(norm_name)
        if ext.lower() in _IMAGE_EXTENSIONS:
            try:
                img_bytes = active_tracker.read_member(archive, info)
                # 单个图片限制最大 10MB
                if len(img_bytes) <= 10 * 1024 * 1024:
                    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
                    clean_basename = re.sub(r"[^\w.\-]", "_", os.path.basename(norm_name))
                    saved_filename = f"{uuid.uuid4().hex[:12]}_{clean_basename}"
                    target_path = _UPLOAD_DIR / saved_filename
                    target_path.write_bytes(img_bytes)
                    url = f"/static/uploads/images/{saved_filename}"

                    image_map[norm_name] = url
                    image_map[os.path.basename(norm_name)] = url
                    parts = norm_name.split("/")
                    if len(parts) > 1:
                        rel = "/".join(parts[1:])
                        if rel:
                            image_map[rel] = url
            except ValueError:
                raise
            except Exception:
                continue
    return image_map


def _rewrite_markdown_images(text: str, img_map: dict[str, str]) -> str:
    """替换 Markdown 文本中的图片引用路径为静态文件 URL。"""
    if not text or not img_map:
        return text

    def _rep_md(m: re.Match) -> str:
        alt = m.group(1)
        src = m.group(2).strip()
        cleaned_src = src.lstrip("./")
        if cleaned_src in img_map:
            return f"![{alt}]({img_map[cleaned_src]})"
        base = os.path.basename(cleaned_src)
        if base in img_map:
            return f"![{alt}]({img_map[base]})"
        return m.group(0)

    def _rep_html(m: re.Match) -> str:
        prefix = m.group(1)
        src = m.group(2).strip()
        suffix = m.group(3)
        cleaned_src = src.lstrip("./")
        if cleaned_src in img_map:
            return f"{prefix}{img_map[cleaned_src]}{suffix}"
        base = os.path.basename(cleaned_src)
        if base in img_map:
            return f"{prefix}{img_map[base]}{suffix}"
        return m.group(0)

    text = re.sub(r"!\[(.*?)\]\((.*?)\)", _rep_md, text)
    text = re.sub(r'(<img\b[^>]*?\bsrc=["\'])(.*?)(["\'][^>]*?>)', _rep_html, text, flags=re.IGNORECASE)
    return text


def extract_test_cases_from_zip(
    archive: zf.ZipFile,
    infos: list[zf.ZipInfo],
    tracker: ZipDecompressTracker | None = None,
) -> tuple[list[dict[str, Any]], set[int]]:
    """提取压缩包中的测试数据，返回 (test_cases, detected_subtask_ids)。"""
    active_tracker = tracker or ZipDecompressTracker()
    entries: dict[tuple, dict[str, str]] = {}
    display_names: dict[tuple, str] = {}
    entry_subtasks: dict[tuple, Optional[int]] = {}

    for info in infos:
        parsed = parse_zip_case_entry(info.filename)
        if parsed is None:
            continue
        subtask_id, sort_key, ext, disp_name = parsed
        key = (subtask_id, sort_key)
        try:
            raw = active_tracker.read_member(archive, info)
            data = decode_zip_text(raw)
        except ValueError:
            raise
        except Exception:
            raise ValueError(f"测试数据文件 {info.filename} 读取失败")
        entries.setdefault(key, {})[ext] = data
        display_names[key] = disp_name
        entry_subtasks[key] = subtask_id

    # 针对 input1.in / output1.out 命名的成对修补
    unpaired_keys = [k for k, v in entries.items() if "in" not in v or "out" not in v]
    if unpaired_keys:
        in_unpaired = [k for k in unpaired_keys if "in" in entries[k] and "out" not in entries[k]]
        out_unpaired = [k for k in unpaired_keys if "out" in entries[k] and "in" not in entries[k]]

        for in_k in list(in_unpaired):
            in_name = display_names[in_k]
            clean_in = re.sub(r"^(?:input|in)[-_]?", "", in_name.split("/")[-1], flags=re.IGNORECASE)
            for out_k in list(out_unpaired):
                out_name = display_names[out_k]
                clean_out = re.sub(r"^(?:output|out|ans)[-_]?", "", out_name.split("/")[-1], flags=re.IGNORECASE)
                if clean_in and clean_in.lower() == clean_out.lower() and entry_subtasks[in_k] == entry_subtasks[out_k]:
                    entries[in_k]["out"] = entries[out_k]["out"]
                    del entries[out_k]
                    del display_names[out_k]
                    del entry_subtasks[out_k]
                    out_unpaired.remove(out_k)
                    break

    unpaired = [f"{display_names[k]}.in/.out" for k, v in entries.items()
                if "in" not in v or "out" not in v]
    if unpaired:
        raise ValueError("以下测试点缺少配对的输入/输出文件: " + ", ".join(unpaired[:5]))
    if not entries:
        raise ValueError("压缩包内未找到有效测试点（需成对包含形如 1.in/1.out 或 data1.in/data1.ans）")
    if len(entries) > MAX_TEST_CASES:
        raise ValueError(f"测试点最多 {MAX_TEST_CASES} 个（压缩包内包含 {len(entries)} 个）")

    # 按 subtask_id 与 sort_key 排序
    keys = sorted(entries.keys(), key=lambda k: k[1])
    test_cases = []
    detected_subtask_ids: set[int] = set()

    for idx, key in enumerate(keys):
        st_id = entry_subtasks.get(key)
        if st_id is not None:
            detected_subtask_ids.add(st_id)
        test_cases.append({
            "input": entries[key]["in"],
            "output": entries[key]["out"],
            "subtask_id": st_id,
            "sort_order": idx,
            "display_name": display_names[key],
        })

    return test_cases, detected_subtask_ids


def parse_problem_zip(zip_content: bytes, zip_filename: str = "") -> dict[str, Any]:
    """完整解析题目 zip 包，返回解析后的题面、测试点及子任务配置。"""
    if len(zip_content) > ZIP_MAX_UPLOAD:
        raise ValueError("压缩包大小不能超过 50MB")
    try:
        archive = zf.ZipFile(io.BytesIO(zip_content))
    except zf.BadZipFile:
        raise ValueError("无法解析压缩包，请确认是合法的 zip 格式")

    infos = archive.infolist()
    if sum(i.file_size for i in infos) > ZIP_MAX_TOTAL:
        raise ValueError("解压后总大小不能超过 100MB")

    tracker = ZipDecompressTracker()

    # 1. 查找并解析 Markdown 题面
    md_info = locate_problem_markdown(archive, infos)
    raw_md = tracker.read_member(archive, md_info)
    md_text = decode_zip_text(raw_md)

    # 2. 提取图片资源并重写 Markdown 中的图片链接
    img_map = _extract_images_from_zip(archive, infos, tracker=tracker)
    if img_map:
        md_text = _rewrite_markdown_images(md_text, img_map)

    parsed_problem = parse_problem_markdown(md_text)

    # 3. 题面缺失标题回退兜底
    md_stem = Path(md_info.filename).stem
    zip_stem = Path(zip_filename).stem if zip_filename else ""

    if not parsed_problem.get("title"):
        if md_stem.lower() not in ("problem", "readme", "statement", "index", "题面"):
            parsed_problem["title"] = md_stem
        elif zip_stem and zip_stem.lower() not in ("problem", "archive", "test", "testdata"):
            parsed_problem["title"] = zip_stem
        else:
            parsed_problem["title"] = "未命名题目"

    # 4. 提取测试点
    test_cases, detected_subtasks = extract_test_cases_from_zip(archive, infos, tracker=tracker)

    # 5. 子任务分值配置（优先使用 Front Matter 指定的配置，否则均分）
    subtask_config = parsed_problem.get("subtask_config")
    if not subtask_config and detected_subtasks:
        st_list = sorted(list(detected_subtasks))
        n_st = len(st_list)
        each_sc = 100 // n_st
        subtask_config = []
        for idx, sid in enumerate(st_list):
            sc = 100 - each_sc * (n_st - 1) if idx == n_st - 1 else each_sc
            subtask_config.append({"id": sid, "score": sc, "name": f"Subtask #{sid}"})

    if subtask_config:
        score_by_st = {item["id"]: item["score"] for item in subtask_config if isinstance(item, dict) and "id" in item and "score" in item}
        for tc in test_cases:
            if tc.get("subtask_id") in score_by_st:
                tc["subtask_score"] = score_by_st[tc["subtask_id"]]

    return {
        "problem_meta": parsed_problem,
        "test_cases": test_cases,
        "detected_subtasks": sorted(list(detected_subtasks)),
        "subtask_config": subtask_config,
        "markdown_filename": md_info.filename,
    }
