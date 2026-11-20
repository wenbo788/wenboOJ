import type { ProblemDifficulty, ProblemSample } from '@/types'

export interface ParsedProblemMarkdown {
  title?: string
  difficulty?: ProblemDifficulty
  source?: string
  tags?: string[]
  time_limit?: number
  memory_limit?: number
  background?: string
  description?: string
  input_format?: string
  output_format?: string
  hint?: string
  samples?: ProblemSample[]
}

const DIFFICULTY_MAP: Record<string, ProblemDifficulty> = {
  暂无评定: '暂无评定',
  暂无: '暂无评定',
  none: '暂无评定',
  入门: '入门',
  red: '入门',
  easy: '入门',
  简单: '入门',
  '普及-': '普及-',
  普及减: '普及-',
  orange: '普及-',
  普及: '普及',
  '普及/提高-': '普及',
  yellow: '普及',
  中等: '普及+/提高-',
  '普及+/提高-': '普及+/提高-',
  // 历史别名：改名前的老档位名（旧 md 可能仍是这个串）
  '普及+/提高': '普及+/提高-',
  普及加: '普及+/提高-',
  green: '普及+/提高-',
  提高: '提高',
  '提高-': '提高',
  blue: '提高',
  '提高+/省选-': '提高+/省选-',
  提高加: '提高+/省选-',
  '省选-': '提高+/省选-',
  purple: '提高+/省选-',
  困难: '提高+/省选-',
  '省选/NOI-': '省选/NOI-',
  省选: '省选/NOI-',
  black: '省选/NOI-',
  'NOI/NOI+/CTSC': 'NOI/NOI+/CTSC',
  noi: 'NOI/NOI+/CTSC',
  ctsc: 'NOI/NOI+/CTSC',
}

export function normalizeDifficulty(val: string): ProblemDifficulty | undefined {
  if (!val) return undefined
  const cleaned = val.trim().toLowerCase()
  return DIFFICULTY_MAP[val.trim()] ?? DIFFICULTY_MAP[cleaned]
}

export function parseTimeLimit(val: unknown): number | undefined {
  if (typeof val === 'number' && Number.isFinite(val) && val > 0) {
    return Math.max(100, Math.min(60000, Math.round(val)))
  }
  if (typeof val !== 'string') return undefined
  const s = val.trim().toLowerCase()
  const m = s.match(/^([0-9.]+)\s*(ms|s|秒|毫秒)?$/i)
  if (!m) return undefined
  let num = parseFloat(m[1])
  if (isNaN(num) || num <= 0) return undefined
  const unit = m[2] ? m[2].toLowerCase() : 'ms'
  if (unit === 's' || unit === '秒') {
    num *= 1000
  }
  return Math.max(100, Math.min(60000, Math.round(num)))
}

export function parseMemoryLimit(val: unknown): number | undefined {
  if (typeof val === 'number' && Number.isFinite(val) && val > 0) {
    return Math.max(16, Math.min(1024, Math.round(val)))
  }
  if (typeof val !== 'string') return undefined
  const s = val.trim().toLowerCase()
  const m = s.match(/^([0-9.]+)\s*(mb|m|gb|g|kb|k)?$/i)
  if (!m) return undefined
  let num = parseFloat(m[1])
  if (isNaN(num) || num <= 0) return undefined
  const unit = m[2] ? m[2].toLowerCase() : 'mb'
  if (unit === 'gb' || unit === 'g') {
    num *= 1024
  } else if (unit === 'kb' || unit === 'k') {
    num /= 1024
  }
  return Math.max(16, Math.min(1024, Math.round(num)))
}

export function parseTags(val: unknown): string[] | undefined {
  if (Array.isArray(val)) {
    const list = val.map((v) => String(v).trim()).filter(Boolean)
    return list.length ? list : undefined
  }
  if (typeof val === 'string') {
    const cleaned = val.replace(/^\[|\]$/g, '')
    const list = cleaned
      .split(/[,，\s]+/)
      .map((t) => t.trim())
      .filter(Boolean)
    return list.length ? list : undefined
  }
  return undefined
}

function applyFmKey(key: string, val: unknown, result: ParsedProblemMarkdown) {
  const normKey = key.toLowerCase().replace(/[-_\s]/g, '')
  if (['title', 'name', '题目', '标题', '题目名称'].includes(normKey)) {
    result.title = String(val).trim()
  } else if (['difficulty', 'diff', '难度'].includes(normKey)) {
    const diff = normalizeDifficulty(String(val))
    if (diff) result.difficulty = diff
  } else if (['timelimit', 'time', '时间限制', '时限'].includes(normKey)) {
    const tl = parseTimeLimit(val)
    if (tl) result.time_limit = tl
  } else if (['memorylimit', 'memory', '内存限制', '空间限制', '空限'].includes(normKey)) {
    const ml = parseMemoryLimit(val)
    if (ml) result.memory_limit = ml
  } else if (['source', '来源', '出处'].includes(normKey)) {
    result.source = String(val).trim()
  } else if (['tags', 'tag', '标签', '算法标签'].includes(normKey)) {
    const tags = parseTags(val)
    if (tags) result.tags = tags
  } else if (['background', '背景', '题目背景'].includes(normKey)) {
    result.background = String(val).trim()
  } else if (['description', '描述', '题目描述'].includes(normKey)) {
    result.description = String(val).trim()
  } else if (['inputformat', 'input', '输入格式', '输入说明', '输入'].includes(normKey)) {
    result.input_format = String(val).trim()
  } else if (['outputformat', 'output', '输出格式', '输出说明', '输出'].includes(normKey)) {
    result.output_format = String(val).trim()
  } else if (['hint', 'hints', 'note', 'notes', '提示', '说明', '提示说明', '说明提示'].includes(normKey)) {
    result.hint = String(val).trim()
  }
}

function parseFrontMatter(fmText: string, result: ParsedProblemMarkdown) {
  const lines = fmText.split('\n')
  let currentKey = ''
  let currentList: string[] = []

  const flushList = () => {
    if (currentKey && currentList.length) {
      applyFmKey(currentKey, currentList, result)
      currentList = []
      currentKey = ''
    }
  }

  for (const line of lines) {
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith('#')) continue

    const listMatch = line.match(/^\s*-\s+(.+)$/)
    if (listMatch && currentKey) {
      currentList.push(listMatch[1].replace(/^['"]|['"]$/g, '').trim())
      continue
    }

    flushList()

    const kvMatch = line.match(/^([a-zA-Z0-9_\u4e00-\u9fa5-]+)\s*:\s*(.*)$/)
    if (kvMatch) {
      const key = kvMatch[1].trim()
      const rawVal = kvMatch[2].trim()
      if (!rawVal) {
        currentKey = key
        currentList = []
      } else {
        const val = rawVal.replace(/^['"]|['"]$/g, '')
        applyFmKey(key, val, result)
      }
    }
  }
  flushList()
}

function extractBodyTitle(body: string, result: ParsedProblemMarkdown): string {
  const lines = body.split('\n')
  const newLines: string[] = []
  let found = false

  for (const line of lines) {
    const trimmed = line.trim()

    const h1Match = trimmed.match(/^#\s+(.+)$/)
    if (!found && h1Match) {
      let rawTitle = h1Match[1].trim()
      const pNumMatch = rawTitle.match(/^(?:[PT]\d+|\d+)[\s.、:：\-—]+(.*)$/)
      if (pNumMatch && pNumMatch[1].trim()) {
        rawTitle = pNumMatch[1].trim()
      }
      const srcMatch = rawTitle.match(/^\[(.*?)\]\s*(.*)$/)
      if (srcMatch && !result.source) {
        result.source = srcMatch[1].trim()
        if (srcMatch[2].trim()) {
          rawTitle = srcMatch[2].trim()
        }
      }
      if (!result.title) {
        result.title = rawTitle
      }
      found = true
      continue
    }

    const titleMatch = trimmed.match(/^(?:\*\*)?(?:题目名称|题目|Title)(?:\*\*)?\s*[:：]\s*(.+)$/i)
    if (!found && titleMatch) {
      if (!result.title) {
        result.title = titleMatch[1].replace(/^\*\*|\*\*$/g, '').trim()
      }
      found = true
      continue
    }

    newLines.push(line)
  }

  return newLines.join('\n')
}

function extractBodyMetadata(body: string, result: ParsedProblemMarkdown): string {
  const lines = body.split('\n')
  const newLines: string[] = []
  let inMetaPrefix = true

  for (const line of lines) {
    const trimmed = line.trim()

    if (trimmed.startsWith('#') || trimmed.startsWith('【') || trimmed.startsWith('```')) {
      inMetaPrefix = false
    }

    if (inMetaPrefix && trimmed) {
      let isMetaLine = false

      const timeMatch = trimmed.match(/(?:\*{1,2})?(?:时间限制|时限|Time\s*Limit)(?:\*{1,2})?\s*[:：]\s*([0-9.]+\s*(?:ms|s|秒|毫秒)?)/i)
      if (timeMatch) {
        isMetaLine = true
        if (result.time_limit === undefined) {
          result.time_limit = parseTimeLimit(timeMatch[1])
        }
      }

      const memMatch = trimmed.match(/(?:\*{1,2})?(?:内存限制|空间限制|空限|Memory\s*Limit)(?:\*{1,2})?\s*[:：]\s*([0-9.]+\s*(?:mb|m|gb|g|kb|k)?)/i)
      if (memMatch) {
        isMetaLine = true
        if (result.memory_limit === undefined) {
          result.memory_limit = parseMemoryLimit(memMatch[1])
        }
      }

      const diffMatch = trimmed.match(/(?:\*{1,2})?(?:题目难度|难度)(?:\*{1,2})?\s*[:：]\s*([^\n|*，,]+)/i)
      if (diffMatch) {
        const diff = normalizeDifficulty(diffMatch[1].trim())
        if (diff) {
          isMetaLine = true
          if (!result.difficulty) {
            result.difficulty = diff
          }
        }
      }

      const srcMatch = trimmed.match(/(?:\*{1,2})?(?:题目来源|来源|出处|Source)(?:\*{1,2})?\s*[:：]\s*([^\n,|，|/|*]+)/i)
      if (srcMatch) {
        isMetaLine = true
        if (!result.source) {
          result.source = srcMatch[1].trim()
        }
      }

      const tagMatch = trimmed.match(/(?:\*{1,2})?(?:算法标签|标签|Tags)(?:\*{1,2})?\s*[:：]\s*([^\n|*]+)/i)
      if (tagMatch) {
        isMetaLine = true
        if (!result.tags) {
          result.tags = parseTags(tagMatch[1].trim())
        }
      }

      if (isMetaLine) continue
    }

    newLines.push(line)
  }

  return newLines.join('\n')
}

interface HeadingMeta {
  type: string
  index?: number
}

function categorizeHeading(rawText: string): HeadingMeta | null {
  const s = rawText
    .trim()
    .replace(/^[:：\s#*【】[\]]+|[:：\s#*【】[\]]+$/g, '')
    .trim()

  if (/^(?:题目)?背景(?:说明)?$|^background$/i.test(s)) {
    return { type: 'background' }
  }

  if (/^(?:题目|问题)?描述$|^(?:题目)?叙述$|^题面$|^description$|^problem\s*description$/i.test(s)) {
    return { type: 'description' }
  }

  if (/^输入(?:格式|说明|数据|要求)?$|^input(?:\s*format)?$/i.test(s)) {
    return { type: 'input_format' }
  }

  if (/^输出(?:格式|说明|数据|要求)?$|^output(?:\s*format)?$/i.test(s)) {
    return { type: 'output_format' }
  }

  if (
    /^(?:说明\s*[/／]\s*提示|提示\s*[/／]\s*说明|提示说明|说明|提示|数据范围(?:与提示|及提示|与约定|及约定)?|数据规模(?:与约定)?|子任务|subtasks?|备注|hints?|notes?|explanation)$/i.test(
      s
    )
  ) {
    return { type: 'hint' }
  }

  if (/^样例(?:说明|解释)$|^sample\s*explanation$/i.test(s)) {
    return { type: 'sample_explanation' }
  }

  const inMatch =
    s.match(/^(?:样例输入|输入样例)\s*(?:#|组|编号)?\s*(\d+)?$/i) ||
    s.match(/^样例\s*(?:#|组|编号)?\s*(\d+)\s*输入$/i) ||
    s.match(/^sample\s*input\s*#?(\d+)?$/i)
  if (inMatch) {
    const idx = inMatch[1] ? parseInt(inMatch[1], 10) : undefined
    return { type: 'sample_input', index: idx }
  }

  const outMatch =
    s.match(/^(?:样例输出|输出样例)\s*(?:#|组|编号)?\s*(\d+)?$/i) ||
    s.match(/^样例\s*(?:#|组|编号)?\s*(\d+)\s*输出$/i) ||
    s.match(/^sample\s*output\s*#?(\d+)?$/i)
  if (outMatch) {
    const idx = outMatch[1] ? parseInt(outMatch[1], 10) : undefined
    return { type: 'sample_output', index: idx }
  }

  const groupMatch =
    s.match(/^样例\s*(?:#|组|编号)?\s*(\d+)$/i) ||
    s.match(/^sample\s*#?(\d+)$/i)
  if (groupMatch) {
    return { type: 'sample_group', index: parseInt(groupMatch[1], 10) }
  }

  if (/^(?:输入输出)?样例(?:数据|组|输入输出)?$|^samples?$|^examples?$/i.test(s)) {
    return { type: 'samples_section' }
  }

  return null
}

function extractFirstCodeBlock(text: string): string {
  const match =
    text.match(/```[a-zA-Z0-9_-]*\r?\n([\s\S]*?)```/) ||
    text.match(/~~~[a-zA-Z0-9_-]*\r?\n([\s\S]*?)~~~/)
  if (match) {
    return match[1].replace(/\r\n/g, '\n').replace(/\n$/, '')
  }
  return text.replace(/^(?:(?:样例)?(?:输入|输出)[：:\s]*)/i, '').trim()
}

function extractAllCodeBlocks(text: string): Array<{ lang: string; code: string }> {
  const regex = /```([a-zA-Z0-9_-]*)\r?\n([\s\S]*?)```|~~~([a-zA-Z0-9_-]*)\r?\n([\s\S]*?)~~~/g
  const list: Array<{ lang: string; code: string }> = []
  let m: RegExpExecArray | null
  while ((m = regex.exec(text)) !== null) {
    const lang = (m[1] || m[3] || '').trim().toLowerCase()
    const code = (m[2] || m[4] || '').replace(/\r\n/g, '\n').replace(/\n$/, '')
    list.push({ lang, code })
  }
  return list
}

interface SectionChunk {
  meta: HeadingMeta | null
  rawHeading: string
  lines: string[]
}

function appendText(curr: string | undefined, addition: string): string {
  const trimmed = addition.trim()
  if (!trimmed) return curr || ''
  if (!curr || !curr.trim()) return trimmed
  return `${curr.trim()}\n\n${trimmed}`
}

function parseSamples(sampleChunks: SectionChunk[]): ProblemSample[] {
  const allSampleText = sampleChunks
    .map((c) => (c.rawHeading ? `${c.rawHeading}\n` : '') + c.lines.join('\n'))
    .join('\n\n')

  const codeBlocks = extractAllCodeBlocks(allSampleText)
  const taggedMap = new Map<number, { input?: string; output?: string }>()

  // 1. Tag based: ```input1 / ```output1
  let hasTagged = false
  for (const b of codeBlocks) {
    const mIn = b.lang.match(/^input(\d*)$/)
    const mOut = b.lang.match(/^output(\d*)$/)
    if (mIn) {
      hasTagged = true
      const idx = mIn[1] ? parseInt(mIn[1], 10) : 1
      const item = taggedMap.get(idx) || {}
      item.input = b.code
      taggedMap.set(idx, item)
    } else if (mOut) {
      hasTagged = true
      const idx = mOut[1] ? parseInt(mOut[1], 10) : 1
      const item = taggedMap.get(idx) || {}
      item.output = b.code
      taggedMap.set(idx, item)
    }
  }
  if (hasTagged && taggedMap.size > 0) {
    const sortedKeys = Array.from(taggedMap.keys()).sort((a, b) => a - b)
    return sortedKeys.map((k) => ({
      input: taggedMap.get(k)?.input || '',
      output: taggedMap.get(k)?.output || '',
    }))
  }

  // 2. Chunks with explicit input/output meta
  const sampleMap = new Map<number, { input?: string; output?: string }>()
  let currentGroupIdx = 1
  let autoInIdx = 1
  let autoOutIdx = 1

  for (const chunk of sampleChunks) {
    if (!chunk.meta) continue

    if (chunk.meta.type === 'sample_group') {
      if (chunk.meta.index !== undefined) {
        currentGroupIdx = chunk.meta.index
      }
      const groupText = chunk.lines.join('\n')
      const blocks = extractAllCodeBlocks(groupText)
      if (blocks.length >= 2) {
        const item = sampleMap.get(currentGroupIdx) || {}
        item.input = blocks[0].code
        item.output = blocks[1].code
        sampleMap.set(currentGroupIdx, item)
      } else if (blocks.length === 1) {
        const item = sampleMap.get(currentGroupIdx) || {}
        if (!item.input) item.input = blocks[0].code
        else item.output = blocks[0].code
        sampleMap.set(currentGroupIdx, item)
      }
      currentGroupIdx++
    } else if (chunk.meta.type === 'sample_input') {
      const idx = chunk.meta.index ?? autoInIdx++
      const code = extractFirstCodeBlock(chunk.lines.join('\n'))
      const item = sampleMap.get(idx) || {}
      item.input = code
      sampleMap.set(idx, item)
    } else if (chunk.meta.type === 'sample_output') {
      const idx = chunk.meta.index ?? autoOutIdx++
      const code = extractFirstCodeBlock(chunk.lines.join('\n'))
      const item = sampleMap.get(idx) || {}
      item.output = code
      sampleMap.set(idx, item)
    }
  }

  if (sampleMap.size > 0) {
    const sorted = Array.from(sampleMap.keys()).sort((a, b) => a - b)
    return sorted.map((k) => ({
      input: sampleMap.get(k)?.input || '',
      output: sampleMap.get(k)?.output || '',
    }))
  }

  // 3. Fallback: Pair all code blocks (0->in, 1->out, 2->in, 3->out)
  if (codeBlocks.length > 0) {
    const res: ProblemSample[] = []
    for (let i = 0; i < codeBlocks.length; i += 2) {
      res.push({
        input: codeBlocks[i]?.code || '',
        output: codeBlocks[i + 1]?.code || '',
      })
    }
    return res
  }

  return []
}

/**
 * 解析 Markdown 文本，自动提取题目基本信息、分节内容与样例组。
 */
export function parseProblemMarkdown(content: string): ParsedProblemMarkdown {
  const result: ParsedProblemMarkdown = {}
  if (!content || !content.trim()) return result

  const normalized = content.replace(/\r\n/g, '\n').replace(/\r/g, '\n')
  let body = normalized

  // 1. 尝试解析 YAML Front Matter
  const fmMatch = normalized.match(/^---\n([\s\S]*?)\n---\n?([\s\S]*)$/)
  if (fmMatch) {
    parseFrontMatter(fmMatch[1], result)
    body = fmMatch[2]
  }

  // 2. 提取题目名称（若 Front Matter 未提供）
  body = extractBodyTitle(body, result)

  // 3. 提取前置元数据行（时空限制、难度、标签、来源）
  body = extractBodyMetadata(body, result)

  // 4. 分块扫描 headings
  const lines = body.split('\n')
  const chunks: SectionChunk[] = []
  let currentChunk: SectionChunk = { meta: null, rawHeading: '', lines: [] }

  for (const line of lines) {
    const trimmed = line.trim()

    // 检查是否为标题行
    const isMdHeading = trimmed.match(/^#{1,6}\s+(.+)$/)
    const isBoldHeading = trimmed.match(/^\*\*([^\n*]+)\*\*\s*$/)
    const isBracketHeading = trimmed.match(/^【([^\n【】]+)】\s*$/)
    const isHtmlHeading = trimmed.match(/^<h[1-6]>(.*?)<\/h[1-6]>/i)

    const headingText = isMdHeading
      ? isMdHeading[1]
      : isBoldHeading
        ? isBoldHeading[1]
        : isBracketHeading
          ? isBracketHeading[1]
          : isHtmlHeading
            ? isHtmlHeading[1]
            : null

    if (headingText !== null) {
      const cat = categorizeHeading(headingText)
      if (cat !== null) {
        chunks.push(currentChunk)
        currentChunk = { meta: cat, rawHeading: trimmed, lines: [] }
        continue
      }
    }

    currentChunk.lines.push(line)
  }
  chunks.push(currentChunk)

  // 5. 整合各分节
  const sampleChunks: SectionChunk[] = []
  const hasExplicitDescription = chunks.some((c) => c.meta?.type === 'description')
  const hasExplicitBackground = chunks.some((c) => c.meta?.type === 'background')

  for (let i = 0; i < chunks.length; i++) {
    const chunk = chunks[i]
    if (!chunk.meta) {
      // 头部未分节文本：若已有显式「题目描述」，前置文本若存在且没有显式「题目背景」则作为题目背景，否则如果无显式描述才作为描述
      const text = chunk.lines.join('\n').trim()
      if (text) {
        if (!hasExplicitDescription) {
          result.description = appendText(result.description, text)
        } else if (!hasExplicitBackground && !result.background) {
          result.background = appendText(result.background, text)
        }
      }
      continue
    }

    const type = chunk.meta.type
    if (type === 'background') {
      result.background = appendText(result.background, chunk.lines.join('\n'))
    } else if (type === 'description') {
      result.description = appendText(result.description, chunk.lines.join('\n'))
    } else if (type === 'input_format') {
      result.input_format = appendText(result.input_format, chunk.lines.join('\n'))
    } else if (type === 'output_format') {
      result.output_format = appendText(result.output_format, chunk.lines.join('\n'))
    } else if (type === 'hint') {
      const prefix = result.hint && chunk.rawHeading ? `${chunk.rawHeading}\n\n` : ''
      result.hint = appendText(result.hint, prefix + chunk.lines.join('\n'))
    } else if (type === 'sample_explanation') {
      const prefix = chunk.rawHeading || '### 样例说明'
      result.hint = appendText(result.hint, `${prefix}\n\n${chunk.lines.join('\n')}`)
    } else if (
      type === 'samples_section' ||
      type === 'sample_group' ||
      type === 'sample_input' ||
      type === 'sample_output'
    ) {
      sampleChunks.push(chunk)
    }
  }

  // 6. 解析样例
  if (sampleChunks.length > 0) {
    const parsedSamples = parseSamples(sampleChunks)
    if (parsedSamples.length > 0) {
      result.samples = parsedSamples
    }
  }

  return result
}

/**
 * 将题目对象导出为标准 Markdown 格式题面文本。
 */
export function exportProblemMarkdown(problem: {
  title?: string
  difficulty?: string
  source?: string | null
  tags?: string[]
  time_limit?: number
  memory_limit?: number
  background?: string
  description?: string
  input_format?: string
  output_format?: string
  hint?: string
  samples?: ProblemSample[]
}): string {
  const parts: string[] = []

  // Front Matter
  parts.push('---')
  parts.push(`title: "${(problem.title || '').replace(/"/g, '\\"')}"`)
  parts.push(`difficulty: ${problem.difficulty || '暂无评定'}`)
  parts.push(`time_limit: ${problem.time_limit || 1000}ms`)
  parts.push(`memory_limit: ${problem.memory_limit || 128}MB`)
  if (problem.source) {
    parts.push(`source: "${problem.source.replace(/"/g, '\\"')}"`)
  }
  if (problem.tags && problem.tags.length) {
    parts.push(`tags: [${problem.tags.map((t) => `"${t}"`).join(', ')}]`)
  }
  parts.push('---\n')

  // Title
  parts.push(`# ${problem.title || '题目名称'}\n`)

  if (problem.background && problem.background.trim()) {
    parts.push('## 题目背景\n')
    parts.push(`${problem.background.trim()}\n`)
  }

  if (problem.description && problem.description.trim()) {
    parts.push('## 题目描述\n')
    parts.push(`${problem.description.trim()}\n`)
  }

  if (problem.input_format && problem.input_format.trim()) {
    parts.push('## 输入格式\n')
    parts.push(`${problem.input_format.trim()}\n`)
  }

  if (problem.output_format && problem.output_format.trim()) {
    parts.push('## 输出格式\n')
    parts.push(`${problem.output_format.trim()}\n`)
  }

  if (problem.samples && problem.samples.length) {
    problem.samples.forEach((s, idx) => {
      parts.push(`## 样例 #${idx + 1}\n`)
      parts.push(`### 样例输入 #${idx + 1}\n`)
      parts.push('```')
      parts.push(s.input || '')
      parts.push('```\n')
      parts.push(`### 样例输出 #${idx + 1}\n`)
      parts.push('```')
      parts.push(s.output || '')
      parts.push('```\n')
    })
  }

  if (problem.hint && problem.hint.trim()) {
    parts.push('## 提示说明\n')
    parts.push(`${problem.hint.trim()}\n`)
  }

  return parts.join('\n')
}
