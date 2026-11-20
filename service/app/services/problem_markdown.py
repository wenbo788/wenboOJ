"""题目 Markdown 题面解析与导出服务。

支持：
- YAML Front Matter 头部元数据提取（title, difficulty, time_limit, memory_limit, tags, source 等）
- 题目名称自动提取（# 标题、P1001 编号过滤、**题目名称**等）
- 正文前置元数据提取（时间限制、空间限制、难度、标签、来源）
- 题面分节提取（题目背景、题目描述、输入格式、输出格式、提示说明、样例说明等）
- 样例组智能识别（洛谷标准样例、分块输入输出、Hydro/Polygon tagged 代码块、成对代码块等）
- 纯文本未分节 Markdown 全文保全（回退填入题目描述）
"""

from __future__ import annotations

import re
from typing import Any

try:
    import yaml
except ImportError:
    # PyYAML 是硬依赖（已在 pyproject 声明）。这里不再静默降级：
    # 静默 None 会让 YAML Front Matter 整块失效（title/difficulty 解析为 None），
    # 表现为「解析不出标题」而非报错，极难排查。
    yaml = None  # type: ignore[assignment]

DIFFICULTY_MAP: dict[str, str] = {
    "暂无评定": "暂无评定",
    "暂无": "暂无评定",
    "none": "暂无评定",
    "入门": "入门",
    "red": "入门",
    "easy": "入门",
    "简单": "入门",
    "普及-": "普及-",
    "普及减": "普及-",
    "orange": "普及-",
    "普及": "普及",
    "普及/提高-": "普及",
    "yellow": "普及",
    "中等": "普及+/提高-",
    "普及+/提高-": "普及+/提高-",
    # 历史别名：改名前的老档位名（旧 md / 存量数据可能仍是这个串），
    # 保留映射以保证导入时能正确归一化到新档位
    "普及+/提高": "普及+/提高-",
    "普及加": "普及+/提高-",
    "green": "普及+/提高-",
    "提高": "提高",
    "提高-": "提高",
    "blue": "提高",
    "提高+/省选-": "提高+/省选-",
    "提高加": "提高+/省选-",
    "省选-": "提高+/省选-",
    "purple": "提高+/省选-",
    "困难": "提高+/省选-",
    "省选/NOI-": "省选/NOI-",
    "省选": "省选/NOI-",
    "black": "省选/NOI-",
    "NOI/NOI+/CTSC": "NOI/NOI+/CTSC",
    "noi": "NOI/NOI+/CTSC",
    "ctsc": "NOI/NOI+/CTSC",
}


def normalize_difficulty(val: Any) -> str | None:
    if not val:
        return None
    s = str(val).strip()
    return DIFFICULTY_MAP.get(s) or DIFFICULTY_MAP.get(s.lower())


def parse_time_limit(val: Any) -> int | None:
    if isinstance(val, (int, float)) and val > 0:
        return max(100, min(60000, round(float(val))))
    if not isinstance(val, str):
        return None
    s = val.strip().lower()
    m = re.match(r"^([0-9.]+)\s*(ms|s|秒|毫秒)?$", s, re.IGNORECASE)
    if not m:
        return None
    try:
        num = float(m.group(1))
    except ValueError:
        return None
    if num <= 0:
        return None
    unit = (m.group(2) or "ms").lower()
    if unit in ("s", "秒"):
        num *= 1000
    return max(100, min(60000, round(num)))


def parse_memory_limit(val: Any) -> int | None:
    if isinstance(val, (int, float)) and val > 0:
        return max(16, min(1024, round(float(val))))
    if not isinstance(val, str):
        return None
    s = val.strip().lower()
    m = re.match(r"^([0-9.]+)\s*(mb|m|gb|g|kb|k)?$", s, re.IGNORECASE)
    if not m:
        return None
    try:
        num = float(m.group(1))
    except ValueError:
        return None
    if num <= 0:
        return None
    unit = (m.group(2) or "mb").lower()
    if unit in ("gb", "g"):
        num *= 1024
    elif unit in ("kb", "k"):
        num /= 1024
    return max(16, min(1024, round(num)))


def parse_tags(val: Any) -> list[str]:
    if isinstance(val, list):
        return [str(v).strip() for v in val if str(v).strip()]
    if isinstance(val, str):
        cleaned = re.sub(r"^\[|\]$", "", val.strip())
        return [t.strip() for t in re.split(r"[,，\s]+", cleaned) if t.strip()]
    return []


def _apply_fm_dict(data: dict[str, Any], result: dict[str, Any]) -> None:
    for k, v in data.items():
        norm_key = re.sub(r"[-_\s]", "", str(k).lower())
        if norm_key in ("title", "name", "题目", "标题", "题目名称"):
            result["title"] = str(v).strip()
        elif norm_key in ("difficulty", "diff", "难度"):
            diff = normalize_difficulty(v)
            if diff:
                result["difficulty"] = diff
        elif norm_key in ("timelimit", "time", "时间限制", "时限"):
            tl = parse_time_limit(v)
            if tl:
                result["time_limit"] = tl
        elif norm_key in ("memorylimit", "memory", "内存限制", "空间限制", "空限"):
            ml = parse_memory_limit(v)
            if ml:
                result["memory_limit"] = ml
        elif norm_key in ("source", "来源", "出处"):
            result["source"] = str(v).strip()
        elif norm_key in ("tags", "tag", "标签", "算法标签"):
            tags = parse_tags(v)
            if tags:
                result["tags"] = tags
        elif norm_key in ("background", "背景", "题目背景"):
            result["background"] = str(v).strip()
        elif norm_key in ("description", "描述", "题目描述"):
            result["description"] = str(v).strip()
        elif norm_key in ("inputformat", "input", "输入格式", "输入说明", "输入"):
            result["input_format"] = str(v).strip()
        elif norm_key in ("outputformat", "output", "输出格式", "输出说明", "输出"):
            result["output_format"] = str(v).strip()
        elif norm_key in ("hint", "hints", "note", "notes", "提示", "说明", "提示说明", "说明提示"):
            result["hint"] = str(v).strip()
        elif norm_key in ("subtaskconfig", "subtasks", "subtask", "子任务配置", "子任务"):
            if isinstance(v, list):
                result["subtask_config"] = v


def _extract_body_title(body: str, result: dict[str, Any]) -> str:
    lines = body.split("\n")
    new_lines = []
    found = False

    for line in lines:
        trimmed = line.strip()
        h1_match = re.match(r"^#\s+(.+)$", trimmed)
        if not found and h1_match:
            raw_title = h1_match.group(1).strip()
            pnum_match = re.match(r"^(?:[PT]\d+|\d+)[\s.、:：\-—]+(.*)$", raw_title)
            if pnum_match and pnum_match.group(1).strip():
                raw_title = pnum_match.group(1).strip()
            src_match = re.match(r"^\[(.*?)\]\s*(.*)$", raw_title)
            if src_match and not result.get("source"):
                result["source"] = src_match.group(1).strip()
                if src_match.group(2).strip():
                    raw_title = src_match.group(2).strip()
            if not result.get("title"):
                result["title"] = raw_title
            found = True
            continue

        title_match = re.match(
            r"^(?:\*\*)?(?:题目名称|题目|Title)(?:\*\*)?\s*[:：]\s*(.+)$",
            trimmed,
            re.IGNORECASE,
        )
        if not found and title_match:
            if not result.get("title"):
                result["title"] = re.sub(r"^\*\*|\*\*$", "", title_match.group(1)).strip()
            found = True
            continue

        new_lines.append(line)

    return "\n".join(new_lines)


def _extract_body_metadata(body: str, result: dict[str, Any]) -> str:
    lines = body.split("\n")
    new_lines = []
    in_meta_prefix = True

    for line in lines:
        trimmed = line.strip()
        if trimmed.startswith("#") or trimmed.startswith("【") or trimmed.startswith("```"):
            in_meta_prefix = False

        if in_meta_prefix and trimmed:
            is_meta_line = False

            time_match = re.search(
                r"(?:\*{1,2})?(?:时间限制|时限|Time\s*Limit)(?:\*{1,2})?\s*[:：]\s*([0-9.]+\s*(?:ms|s|秒|毫秒)?)",
                trimmed,
                re.IGNORECASE,
            )
            if time_match:
                is_meta_line = True
                if result.get("time_limit") is None:
                    result["time_limit"] = parse_time_limit(time_match.group(1))

            mem_match = re.search(
                r"(?:\*{1,2})?(?:内存限制|空间限制|空限|Memory\s*Limit)(?:\*{1,2})?\s*[:：]\s*([0-9.]+\s*(?:mb|m|gb|g|kb|k)?)",
                trimmed,
                re.IGNORECASE,
            )
            if mem_match:
                is_meta_line = True
                if result.get("memory_limit") is None:
                    result["memory_limit"] = parse_memory_limit(mem_match.group(1))

            diff_match = re.search(
                r"(?:\*{1,2})?(?:题目难度|难度)(?:\*{1,2})?\s*[:：]\s*([^\n|*，,]+)",
                trimmed,
                re.IGNORECASE,
            )
            if diff_match:
                diff = normalize_difficulty(diff_match.group(1).strip())
                if diff:
                    is_meta_line = True
                    if not result.get("difficulty"):
                        result["difficulty"] = diff

            src_match = re.search(
                r"(?:\*{1,2})?(?:题目来源|来源|出处|Source)(?:\*{1,2})?\s*[:：]\s*([^\n,|，|/|*]+)",
                trimmed,
                re.IGNORECASE,
            )
            if src_match:
                is_meta_line = True
                if not result.get("source"):
                    result["source"] = src_match.group(1).strip()

            tag_match = re.search(
                r"(?:\*{1,2})?(?:算法标签|标签|Tags)(?:\*{1,2})?\s*[:：]\s*([^\n|*]+)",
                trimmed,
                re.IGNORECASE,
            )
            if tag_match:
                is_meta_line = True
                if not result.get("tags"):
                    result["tags"] = parse_tags(tag_match.group(1).strip())

            if is_meta_line:
                continue

        new_lines.append(line)

    return "\n".join(new_lines)


def _categorize_heading(raw_text: str) -> dict[str, Any] | None:
    s = re.sub(r"^[:：\s#*【】[\]]+|[:：\s#*【】[\]]+$", "", raw_text.strip()).strip()

    if re.match(r"^(?:题目)?背景(?:说明)?$|^background$", s, re.IGNORECASE):
        return {"type": "background"}

    if re.match(r"^(?:题目|问题)?描述$|^(?:题目)?叙述$|^题面$|^description$|^problem\s*description$", s, re.IGNORECASE):
        return {"type": "description"}

    if re.match(r"^输入(?:格式|说明|数据|要求)?$|^input(?:\s*format)?$", s, re.IGNORECASE):
        return {"type": "input_format"}

    if re.match(r"^输出(?:格式|说明|数据|要求)?$|^output(?:\s*format)?$", s, re.IGNORECASE):
        return {"type": "output_format"}

    if re.match(
        r"^(?:说明\s*[/／]\s*提示|提示\s*[/／]\s*说明|提示说明|说明|提示|数据范围(?:与提示|及提示|与约定|及约定)?|数据规模(?:与约定)?|子任务|subtasks?|备注|hints?|notes?|explanation)$",
        s,
        re.IGNORECASE,
    ):
        return {"type": "hint"}

    if re.match(r"^样例(?:说明|解释)$|^sample\s*explanation$", s, re.IGNORECASE):
        return {"type": "sample_explanation"}

    in_match = (
        re.match(r"^(?:样例输入|输入样例)\s*(?:#|组|编号)?\s*(\d+)?$", s, re.IGNORECASE)
        or re.match(r"^样例\s*(?:#|组|编号)?\s*(\d+)\s*输入$", s, re.IGNORECASE)
        or re.match(r"^sample\s*input\s*#?(\d+)?$", s, re.IGNORECASE)
    )
    if in_match:
        idx = int(in_match.group(1)) if in_match.group(1) else None
        return {"type": "sample_input", "index": idx}

    out_match = (
        re.match(r"^(?:样例输出|输出样例)\s*(?:#|组|编号)?\s*(\d+)?$", s, re.IGNORECASE)
        or re.match(r"^样例\s*(?:#|组|编号)?\s*(\d+)\s*输出$", s, re.IGNORECASE)
        or re.match(r"^sample\s*output\s*#?(\d+)?$", s, re.IGNORECASE)
    )
    if out_match:
        idx = int(out_match.group(1)) if out_match.group(1) else None
        return {"type": "sample_output", "index": idx}

    group_match = (
        re.match(r"^样例\s*(?:#|组|编号)?\s*(\d+)$", s, re.IGNORECASE)
        or re.match(r"^sample\s*#?(\d+)$", s, re.IGNORECASE)
    )
    if group_match:
        return {"type": "sample_group", "index": int(group_match.group(1))}

    if re.match(r"^(?:输入输出)?样例(?:数据|组|输入输出)?$|^samples?$|^examples?$", s, re.IGNORECASE):
        return {"type": "samples_section"}

    return None


def _extract_all_code_blocks(text: str) -> list[tuple[str, str]]:
    pattern = re.compile(r"```([a-zA-Z0-9_-]*)\r?\n([\s\S]*?)```|~~~([a-zA-Z0-9_-]*)\r?\n([\s\S]*?)~~~")
    blocks = []
    for m in pattern.finditer(text):
        lang = (m.group(1) or m.group(3) or "").strip().lower()
        code = (m.group(2) or m.group(4) or "").replace("\r\n", "\n").rstrip("\n")
        blocks.append((lang, code))
    return blocks


def _extract_first_code_block(text: str) -> str:
    m = re.search(r"```[a-zA-Z0-9_-]*\r?\n([\s\S]*?)```|~~~[a-zA-Z0-9_-]*\r?\n([\s\S]*?)~~~", text)
    if m:
        return (m.group(1) or m.group(2) or "").replace("\r\n", "\n").rstrip("\n")
    return re.sub(r"^(?:(?:样例)?(?:输入|输出)[：:\s]*)", "", text, flags=re.IGNORECASE).strip()


def _append_text(curr: str | None, addition: str) -> str:
    trimmed = addition.strip()
    if not trimmed:
        return curr or ""
    if not curr or not curr.strip():
        return trimmed
    return f"{curr.strip()}\n\n{trimmed}"


def _parse_samples(sample_chunks: list[dict[str, Any]]) -> list[dict[str, str]]:
    all_sample_text = "\n\n".join(
        (f"{c['raw_heading']}\n" if c.get("raw_heading") else "") + "\n".join(c["lines"])
        for c in sample_chunks
    )
    code_blocks = _extract_all_code_blocks(all_sample_text)
    tagged_map: dict[int, dict[str, str]] = {}

    has_tagged = False
    for lang, code in code_blocks:
        m_in = re.match(r"^input(\d*)$", lang)
        m_out = re.match(r"^output(\d*)$", lang)
        if m_in:
            has_tagged = True
            idx = int(m_in.group(1)) if m_in.group(1) else 1
            tagged_map.setdefault(idx, {})["input"] = code
        elif m_out:
            has_tagged = True
            idx = int(m_out.group(1)) if m_out.group(1) else 1
            tagged_map.setdefault(idx, {})["output"] = code

    if has_tagged and tagged_map:
        return [
            {"input": tagged_map[k].get("input", ""), "output": tagged_map[k].get("output", "")}
            for k in sorted(tagged_map.keys())
        ]

    sample_map: dict[int, dict[str, str]] = {}
    current_group_idx = 1
    auto_in_idx = 1
    auto_out_idx = 1

    for chunk in sample_chunks:
        meta = chunk.get("meta")
        if not meta:
            continue
        mtype = meta.get("type")
        if mtype == "sample_group":
            if meta.get("index") is not None:
                current_group_idx = meta["index"]
            blocks = _extract_all_code_blocks("\n".join(chunk["lines"]))
            if len(blocks) >= 2:
                sample_map.setdefault(current_group_idx, {})["input"] = blocks[0][1]
                sample_map[current_group_idx]["output"] = blocks[1][1]
            elif len(blocks) == 1:
                item = sample_map.setdefault(current_group_idx, {})
                if "input" not in item:
                    item["input"] = blocks[0][1]
                else:
                    item["output"] = blocks[0][1]
            current_group_idx += 1
        elif mtype == "sample_input":
            idx = meta.get("index") or auto_in_idx
            if meta.get("index") is None:
                auto_in_idx += 1
            code = _extract_first_code_block("\n".join(chunk["lines"]))
            sample_map.setdefault(idx, {})["input"] = code
        elif mtype == "sample_output":
            idx = meta.get("index") or auto_out_idx
            if meta.get("index") is None:
                auto_out_idx += 1
            code = _extract_first_code_block("\n".join(chunk["lines"]))
            sample_map.setdefault(idx, {})["output"] = code

    if sample_map:
        return [
            {"input": sample_map[k].get("input", ""), "output": sample_map[k].get("output", "")}
            for k in sorted(sample_map.keys())
        ]

    # Fallback: pairwise
    if code_blocks:
        result = []
        for i in range(0, len(code_blocks), 2):
            inp = code_blocks[i][1] if i < len(code_blocks) else ""
            out = code_blocks[i + 1][1] if i + 1 < len(code_blocks) else ""
            result.append({"input": inp, "output": out})
        return result

    return []


def parse_problem_markdown(content: str) -> dict[str, Any]:
    """解析 Markdown 题面文本，自动提取题目基础属性、各分节内容及样例组。"""
    result: dict[str, Any] = {
        "title": None,
        "difficulty": None,
        "time_limit": None,
        "memory_limit": None,
        "source": None,
        "tags": [],
        "background": "",
        "description": "",
        "input_format": "",
        "output_format": "",
        "hint": "",
        "samples": [],
    }

    if not content or not content.strip():
        return result

    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    body = normalized

    # 1. YAML Front Matter
    fm_match = re.match(r"^---\n([\s\S]*?)\n---\n?([\s\S]*)$", normalized)
    if fm_match:
        fm_content = fm_match.group(1)
        body = fm_match.group(2)
        if yaml is None:
            # 依赖缺失属于部署问题，必须让调用方看见，而不是静默丢弃元数据
            raise RuntimeError(
                "解析 YAML Front Matter 需要 PyYAML，但当前环境未安装。"
                "请执行 `pip install pyyaml`（或 `uv sync`）。"
            )
        try:
            fm_data = yaml.safe_load(fm_content)
            if isinstance(fm_data, dict):
                _apply_fm_dict(fm_data, result)
        except Exception:
            # Front Matter 语法错误不应让整篇题面解析失败，交给正文提取兜底
            pass

    # 2. 标题提取
    body = _extract_body_title(body, result)

    # 3. 前置元数据提取
    body = _extract_body_metadata(body, result)

    # 4. 扫描分块
    lines = body.split("\n")
    chunks: list[dict[str, Any]] = []
    current_chunk: dict[str, Any] = {"meta": None, "raw_heading": "", "lines": []}

    for line in lines:
        trimmed = line.strip()
        is_md = re.match(r"^#{1,6}\s+(.+)$", trimmed)
        is_bold = re.match(r"^\*\*([^\n*]+)\*\*\s*$", trimmed)
        is_bracket = re.match(r"^【([^\n【】]+)】\s*$", trimmed)
        is_html = re.match(r"^<h[1-6]>(.*?)</h[1-6]>", trimmed, re.IGNORECASE)

        heading_text = None
        if is_md:
            heading_text = is_md.group(1)
        elif is_bold:
            heading_text = is_bold.group(1)
        elif is_bracket:
            heading_text = is_bracket.group(1)
        elif is_html:
            heading_text = is_html.group(1)

        if heading_text is not None:
            cat = _categorize_heading(heading_text)
            if cat is not None:
                chunks.append(current_chunk)
                current_chunk = {"meta": cat, "raw_heading": trimmed, "lines": []}
                continue

        current_chunk["lines"].append(line)

    chunks.append(current_chunk)

    # 5. 整合各分节
    sample_chunks: list[dict[str, Any]] = []
    has_explicit_description = any(c.get("meta", {}).get("type") == "description" for c in chunks if c.get("meta"))
    has_explicit_background = any(c.get("meta", {}).get("type") == "background" for c in chunks if c.get("meta"))

    for chunk in chunks:
        meta = chunk.get("meta")
        if not meta:
            text = "\n".join(chunk["lines"]).strip()
            if text:
                if not has_explicit_description:
                    result["description"] = _append_text(result["description"], text)
                elif not has_explicit_background and not result["background"]:
                    result["background"] = _append_text(result["background"], text)
            continue

        mtype = meta["type"]
        text = "\n".join(chunk["lines"])
        if mtype == "background":
            result["background"] = _append_text(result["background"], text)
        elif mtype == "description":
            result["description"] = _append_text(result["description"], text)
        elif mtype == "input_format":
            result["input_format"] = _append_text(result["input_format"], text)
        elif mtype == "output_format":
            result["output_format"] = _append_text(result["output_format"], text)
        elif mtype == "hint":
            prefix = f"{chunk['raw_heading']}\n\n" if result["hint"] and chunk.get("raw_heading") else ""
            result["hint"] = _append_text(result["hint"], prefix + text)
        elif mtype == "sample_explanation":
            prefix = chunk.get("raw_heading") or "### 样例说明"
            result["hint"] = _append_text(result["hint"], f"{prefix}\n\n{text}")
        elif mtype in ("samples_section", "sample_group", "sample_input", "sample_output"):
            sample_chunks.append(chunk)

    # 6. 解析样例
    if sample_chunks:
        parsed_samples = _parse_samples(sample_chunks)
        if parsed_samples:
            result["samples"] = parsed_samples

    return result


def export_problem_markdown(problem: dict[str, Any]) -> str:
    """将题目字典导出为标准 Markdown 格式题面文本。"""
    parts = []

    # Front Matter
    title = str(problem.get("title") or "").replace('"', '\\"')
    parts.append("---")
    parts.append(f'title: "{title}"')
    parts.append(f"difficulty: {problem.get('difficulty') or '暂无评定'}")
    parts.append(f"time_limit: {problem.get('time_limit') or 1000}ms")
    parts.append(f"memory_limit: {problem.get('memory_limit') or 128}MB")
    if problem.get("source"):
        src = str(problem["source"]).replace('"', '\\"')
        parts.append(f'source: "{src}"')
    tags = problem.get("tags") or []
    if tags:
        tag_str = ", ".join(f'"{t}"' for t in tags)
        parts.append(f"tags: [{tag_str}]")
    parts.append("---\n")

    parts.append(f"# {problem.get('title') or '题目名称'}\n")

    if problem.get("background") and str(problem["background"]).strip():
        parts.append("## 题目背景\n")
        parts.append(f"{str(problem['background']).strip()}\n")

    if problem.get("description") and str(problem["description"]).strip():
        parts.append("## 题目描述\n")
        parts.append(f"{str(problem['description']).strip()}\n")

    if problem.get("input_format") and str(problem["input_format"]).strip():
        parts.append("## 输入格式\n")
        parts.append(f"{str(problem['input_format']).strip()}\n")

    if problem.get("output_format") and str(problem["output_format"]).strip():
        parts.append("## 输出格式\n")
        parts.append(f"{str(problem['output_format']).strip()}\n")

    samples = problem.get("samples") or []
    if samples:
        for idx, s in enumerate(samples, 1):
            parts.append(f"## 样例 #{idx}\n")
            parts.append(f"### 样例输入 #{idx}\n")
            parts.append("```")
            parts.append(s.get("input", ""))
            parts.append("```\n")
            parts.append(f"### 样例输出 #{idx}\n")
            parts.append("```")
            parts.append(s.get("output", ""))
            parts.append("```\n")

    if problem.get("hint") and str(problem["hint"]).strip():
        parts.append("## 提示说明\n")
        parts.append(f"{str(problem['hint']).strip()}\n")

    return "\n".join(parts)
