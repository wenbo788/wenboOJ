import katex from 'katex'
import DOMPurify from 'dompurify'
import { parseBilibiliRef, renderBilibiliEmbed } from './bilibili'
import { parseNeteaseRef, renderNeteaseEmbed } from './netease'
import { staticUrl, withBase } from './base'
import { marked } from 'marked'
import hljs from 'highlight.js/lib/core'
import cpp from 'highlight.js/lib/languages/cpp'
import c from 'highlight.js/lib/languages/c'
import python from 'highlight.js/lib/languages/python'
import java from 'highlight.js/lib/languages/java'
import javascript from 'highlight.js/lib/languages/javascript'
import bash from 'highlight.js/lib/languages/bash'
import plaintext from 'highlight.js/lib/languages/plaintext'
import 'katex/dist/katex.min.css'

// 按需注册语言，避免把 highlight.js 的全量语言包打进来
hljs.registerLanguage('cpp', cpp)
hljs.registerLanguage('c', c)
hljs.registerLanguage('python', python)
hljs.registerLanguage('java', java)
hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('bash', bash)
hljs.registerLanguage('plaintext', plaintext)

// 换行即换行（与聊天/犇犇的书写习惯一致），启用 GFM（表格/删除线/任务列表）
marked.setOptions({ breaks: true, gfm: true })

/**
 * 用户 Markdown 转成 HTML 后使用的严格白名单。
 *
 * 这里不能只依赖 DOMPurify 的默认配置：默认配置允许 style/class/id，
 * 恶意用户可以借此插入 fixed/absolute 的大尺寸遮罩，即使没有脚本也能
 * 覆盖首页。代码块和公式使用占位符保护，因此这里处理的只有用户内容。
 */
const USER_HTML_CONFIG = {
  ALLOWED_TAGS: [
    'a', 'b', 'blockquote', 'br', 'code', 'del', 'em', 'h1', 'h2', 'h3',
    'h4', 'h5', 'h6', 'hr', 'i', 'img', 'li', 'ol', 'p', 'pre', 's',
    'strong', 'table', 'tbody', 'td', 'tfoot', 'th', 'thead', 'tr', 'u',
    'ul',
  ],
  ALLOWED_ATTR: ['alt', 'href', 'rel', 'src', 'target', 'title'],
  ALLOW_DATA_ATTR: false,
  FORBID_ATTR: ['class', 'id', 'style'],
  FORBID_TAGS: [
    'embed', 'form', 'iframe', 'input', 'link', 'meta', 'object', 'script',
    'style', 'svg', 'template', 'textarea', 'video', 'audio',
  ],
  // 只允许普通网页链接和站内相对链接，拒绝 javascript:/data: 等协议。
  ALLOWED_URI_REGEXP: /^(?:(?:https?|mailto):|\/|#)/i,
}

/** 代码围栏的语言标记 → highlight.js 语言名 */
const FENCE_LANG: Record<string, string> = {
  cpp: 'cpp', 'c++': 'cpp', cc: 'cpp', cxx: 'cpp', 'c++14': 'cpp', 'c++17': 'cpp', 'c++20': 'cpp',
  c: 'c',
  python: 'python', py: 'python', python3: 'python', py3: 'python',
  java: 'java',
  javascript: 'javascript', js: 'javascript', node: 'javascript', ts: 'javascript', typescript: 'javascript',
  bash: 'bash', sh: 'bash', shell: 'bash', zsh: 'bash',
  text: 'plaintext', txt: 'plaintext', plaintext: 'plaintext',
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

// 用户名 3-50 位：ASCII 字母/数字/下划线，另兼容 CJK 汉字
// （注册限制 ASCII，但管理员/资料更新不校验字符集，站内存在中文用户名）
// 前面不能是 ASCII 单词字符、点或斜杠：
//   - 单词字符/点：避开邮箱（a@b.com）
//   - 斜杠：避开链接路径（https://x.com/@foo）
// 这里刻意写 ASCII 字符集而非 \w：中文正文「回复@张三」里 @ 前面是汉字，
// 用 \w 会把正常提及挡掉。后端 app/services/notification.py 用同一条规则
const MENTION_CHARS = 'A-Za-z0-9_\\u3400-\\u4dbf\\u4e00-\\u9fff\\uf900-\\ufaff'
const MENTION_G = new RegExp(`(?<![A-Za-z0-9_./])@([${MENTION_CHARS}]{3,50})`, 'g')
const MENTION_T = new RegExp(`(?<![A-Za-z0-9_./])@[${MENTION_CHARS}]{3,50}`)

/**
 * 把 @username 变成指向用户主页的链接。
 *
 * 走 DOM 文本节点而不是字符串替换：
 *   1. 字符串替换会把 `[x](https://a.com/@foo)` 这类链接地址里的 @ 也换掉；
 *   2. 无法避开 <a> / <code> / <pre> 内部（a 里再套 a 是非法结构）；
 *   3. 属性值必须原样不动。
 */
function linkifyMentions(html: string): string {
  if (!MENTION_T.test(html)) return html
  const root = document.createElement('div')
  root.innerHTML = html

  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  const targets: Text[] = []
  let node = walker.nextNode() as Text | null
  while (node) {
    const parent = node.parentElement
    if (parent && MENTION_T.test(node.nodeValue || '') && !parent.closest('a, code, pre')) {
      targets.push(node)
    }
    node = walker.nextNode() as Text | null
  }

  for (const textNode of targets) {
    const text = textNode.nodeValue || ''
    const frag = document.createDocumentFragment()
    let last = 0
    let m: RegExpExecArray | null
    MENTION_G.lastIndex = 0
    while ((m = MENTION_G.exec(text)) !== null) {
      if (m.index > last) {
        frag.appendChild(document.createTextNode(text.slice(last, m.index)))
      }
      const a = document.createElement('a')
      a.className = 'mention'
      // 中文用户名要编码，否则部分浏览器解析相对路径时行为不一致
      a.setAttribute('href', `/user/${encodeURIComponent(m[1])}`)
      a.textContent = '@' + m[1]
      frag.appendChild(a)
      last = m.index + m[0].length
    }
    if (last < text.length) {
      frag.appendChild(document.createTextNode(text.slice(last)))
    }
    textNode.parentNode?.replaceChild(frag, textNode)
  }

  return root.innerHTML
}

/**
 * 纯文本场景（工单回复、通知文案）的 @提及 渲染：转义后只把 @名字 变成链接。
 * 通知文案里写的就是 `@solver 回复了你的帖子`，这样用户名也能点。
 */
export function renderMentionText(content: string | null | undefined): string {
  if (!content) return ''
  return linkifyMentions(escapeHtml(content).replace(/\n/g, '<br>'))
}

/**
 * 渲染一个围栏代码块：语法高亮 + 右上角复制按钮。
 * 未标注语言或语言不在注册表内时按纯文本处理（不做自动检测，
 * 因为实时预览会频繁重渲染，highlightAuto 太慢）。
 *
 * 复制按钮的点击由 utils/codeCopy.ts 的全局委托处理 —— v-html 内容无法绑定事件。
 */
function renderCodeBlock(info: string, body: string): string {
  const raw = body.replace(/^\n/, '').replace(/\r?\n$/, '')
  const key = info.trim().toLowerCase()
  const lang = FENCE_LANG[key]
  let inner = escapeHtml(raw)
  if (lang) {
    try {
      inner = hljs.highlight(raw, { language: lang, ignoreIllegals: true }).value
    } catch {
      inner = escapeHtml(raw)
    }
  }
  const cls = lang ? `hljs language-${lang}` : 'hljs'
  // 语言标签展示作者写的原始标记（如 c++14）；截断长度避免撑破布局
  const label = key ? `<span class="code-lang">${escapeHtml(key.slice(0, 16))}</span>` : ''
  return (
    '<div class="code-block">' +
    `<div class="code-tools">${label}` +
    '<button type="button" class="code-copy" data-copy>' +
    '<i class="fa-solid fa-copy"></i><span data-copy-label>复制</span>' +
    '</button></div>' +
    `<pre><code class="${cls}">${inner}</code></pre>` +
    '</div>'
  )
}

function katexHtml(tex: string, displayMode: boolean): string {
  try {
    return katex.renderToString(tex.trim(), { throwOnError: false, displayMode })
  } catch {
    return escapeHtml(tex)
  }
}

interface ExtractedBlock {
  info: string
  body: string
}

/**
 * 结构化提取围栏代码块，并替换为独立块级占位符。
 *
 * 为什么用行扫描而不用简单正则：
 * 1. 实时预览中用户正在输入代码块（未闭合）时，简单正则会贪婪跨越到后续代码块，
 *    导致后续内容与代码块被完全吞掉；
 * 2. 支持 3 个及以上 ` 或 ~ 的围栏，且闭合围栏必须与起始字符和长度一致；
 * 3. 兼容围栏行前置 0-3 空格的合法 GFM 缩进与尾部空格；
 * 4. 占位符前后注入空行，保证 marked 解析为独立块级段落，避免被 <p>...<br> 嵌套。
 */
function extractFencedCodeBlocks(
  content: string,
  placeholderPrefix: string,
): { text: string; blocks: ExtractedBlock[] } {
  const lines = content.split('\n')
  const resultLines: string[] = []
  const blocks: ExtractedBlock[] = []

  let inBlock = false
  let fenceChar = ''
  let fenceLen = 0
  let blockInfo = ''
  let blockBodyLines: string[] = []

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    if (!inBlock) {
      // 匹配围栏代码块起始：允许 0-3 个空格缩进，至少 3 个 ` 或 ~
      const match = line.match(/^[ \t]{0,3}(`{3,}|~{3,})([^`~]*)$/)
      if (match) {
        inBlock = true
        fenceChar = match[1][0]
        fenceLen = match[1].length
        blockInfo = match[2].trim()
        blockBodyLines = []
      } else {
        resultLines.push(line)
      }
    } else {
      // 检查闭合围栏：同一字符且长度 >= 起始围栏长度，允许后置空白
      const closeMatch = line.match(/^[ \t]{0,3}(`{3,}|~{3,})[ \t]*$/)
      if (closeMatch && closeMatch[1][0] === fenceChar && closeMatch[1].length >= fenceLen) {
        inBlock = false
        const idx = blocks.length
        blocks.push({ info: blockInfo, body: blockBodyLines.join('\n') })
        // 前后各留空行，确保 marked 解析为独立块级段落
        resultLines.push('')
        resultLines.push(placeholderPrefix + idx + placeholderPrefix)
        resultLines.push('')
      } else {
        // 容错：如果用户输入过程中未闭合，但遇到了明显的新代码块起始标记，自动结束上一块
        const newOpenMatch = line.match(/^[ \t]{0,3}(`{3,}|~{3,})([a-zA-Z0-9_-]+)[ \t]*$/)
        if (newOpenMatch) {
          const idx = blocks.length
          blocks.push({ info: blockInfo, body: blockBodyLines.join('\n') })
          resultLines.push('')
          resultLines.push(placeholderPrefix + idx + placeholderPrefix)
          resultLines.push('')

          fenceChar = newOpenMatch[1][0]
          fenceLen = newOpenMatch[1].length
          blockInfo = newOpenMatch[2].trim()
          blockBodyLines = []
        } else {
          blockBodyLines.push(line)
        }
      }
    }
  }

  // 实时预览阶段：如果代码块处于未闭合状态（如正在键入），在末尾仍将其闭合渲染，避免内容完全吞没消失
  if (inBlock) {
    const idx = blocks.length
    blocks.push({ info: blockInfo, body: blockBodyLines.join('\n') })
    resultLines.push('')
    resultLines.push(placeholderPrefix + idx + placeholderPrefix)
    resultLines.push('')
  }

  return { text: resultLines.join('\n'), blocks }
}

/**
 * 富文本渲染：完整 Markdown（marked + DOMPurify）+ KaTeX 数学公式
 * - 行内公式：$E = mc^2$
 * - 块级公式：$$\int_0^1 x\,dx$$
 * - 标题 / 列表 / 表格 / 引用 / 代码块 / 行内代码 / 链接 / 图片 / 删除线 / @提及
 */
export function renderRichText(content: string): string {
  if (!content) return ''

  try {
    // 0. 规范化换行符（CRLF/CR → LF），杜绝 Windows 剪贴板换行带来的正则匹配异常
    let text = content.replace(/\r\n/g, '\n').replace(/\r/g, '\n')

    // 每次渲染生成随机标记（正文不可能自然出现，杜绝占位符与内容冲突）
    const uid = Math.random().toString(36).slice(2, 10)
    const BLOCK_CODE_MARK = 'K' + uid + 'b'
    const INLINE_CODE_MARK = 'K' + uid + 'c'
    const MATH_MARK = 'K' + uid + 'm'
    const MENTION_MARK = 'K' + uid + 'a'

    // 1. 块级代码先结构化提取（保护内部的 $ 与 Markdown 符号，避免吞没或误解析）
    const { text: textWithoutBlocks, blocks } = extractFencedCodeBlocks(text, BLOCK_CODE_MARK)
    text = textWithoutBlocks
    const codeBlocks = blocks.map((b) => renderCodeBlock(b.info, b.body))

    // 1.5 行内代码占位（与块级代码分离，避免行内代码脱落段落）
    const inlineCodes: string[] = []
    text = text.replace(/`([^`\n]+)`/g, (_, code: string) => {
      const idx = inlineCodes.length
      inlineCodes.push('<code>' + escapeHtml(code) + '</code>')
      return INLINE_CODE_MARK + idx + INLINE_CODE_MARK
    })

    // 2. LaTeX 公式占位（块级 $$...$$ 与行内 $...$）
    const displayMath: string[] = []
    text = text.replace(/\$\$([\s\S]+?)\$\$/g, (_, tex: string) => {
      const idx = displayMath.length
      displayMath.push(katexHtml(tex, true))
      return MATH_MARK + idx + MATH_MARK
    })
    text = text.replace(/\$([^$\n]+?)\$/g, (_, tex: string) => {
      const idx = displayMath.length
      displayMath.push(katexHtml(tex, false))
      return MATH_MARK + idx + MATH_MARK
    })

    // 2.5 @提及占位：用户名可能含下划线，先占位避免 marked 把下划线拆开为强调
    const mentions: string[] = []
    MENTION_G.lastIndex = 0
    text = text.replace(MENTION_G, (_m, name: string) => {
      const idx = mentions.length
      mentions.push(name)
      return MENTION_MARK + idx + MENTION_MARK
    })

    // 2.7 B 站视频占位：分享代码 / 独立一行的链接 / 裸 BV·av 号。
    //     消毒器会剥掉 iframe，所以这里先占位，消毒完再用我们构造的播放器还原。
    const biliRefs: string[] = []

    function stashBilibili(ref: ReturnType<typeof parseBilibiliRef>): string {
      const idx = biliRefs.length
      biliRefs.push(renderBilibiliEmbed(ref!))
      return 'KB' + uid + 'v' + idx + 'KB' + uid + 'v'
    }

    // 2.7.1 分享代码可能跨行，整段先处理
    text = text.replace(/<iframe\b[^>]*>(?:[\s\S]*?<\/iframe>)?/gi, (m: string) => {
      const ref = parseBilibiliRef(m)
      return ref ? stashBilibili(ref) : m
    })
    // 2.7.2 独立一行的链接 / 裸编号
    text = text.replace(/^[ \t]*(\S(?:.*?\S)?)[ \t]*$/gm, (line: string) => {
      const ref = parseBilibiliRef(line)
      return ref ? stashBilibili(ref) : line
    })

    // 2.8 网易云音乐占位：与 B 站同机制（分享代码 / 独立一行的链接）。
    //     2.7.1/2.7.2 已放过非 B 站的 iframe 与链接行，这里接着筛网易云。
    const neteaseRefs: string[] = []

    function stashNetease(ref: ReturnType<typeof parseNeteaseRef>): string {
      const idx = neteaseRefs.length
      neteaseRefs.push(renderNeteaseEmbed(ref!))
      return 'KN' + uid + 'n' + idx + 'KN' + uid + 'n'
    }

    // 2.8.1 分享代码可能跨行，整段先处理
    text = text.replace(/<iframe\b[^>]*>(?:[\s\S]*?<\/iframe>)?/gi, (m: string) => {
      const ref = parseNeteaseRef(m)
      return ref ? stashNetease(ref) : m
    })
    // 2.8.2 独立一行的链接
    text = text.replace(/^[ \t]*(\S(?:.*?\S)?)[ \t]*$/gm, (line: string) => {
      const ref = parseNeteaseRef(line)
      return ref ? stashNetease(ref) : line
    })

    // 3. marked 解析标准 Markdown
    let html = marked.parse(text) as string

    // 4. 先严格消毒用户可控的 HTML
    html = DOMPurify.sanitize(html, USER_HTML_CONFIG)

    // 4.1 题面/文章里的 /static/... 图片与附件：跨域部署（GitHub Pages）时
    //     浏览器会按前端域解析，这里补上 API origin。同源部署时 staticUrl 原样返回。
    html = html.replace(
      /(src|href)="(\/static\/[^"]*)"/g,
      (_m, attr: string, url: string) => `${attr}="${staticUrl(url)}"`,
    )

    // 4.4 还原 B 站播放器占位（我们构造的 iframe，不经过用户输入）
    const BILI_RE = new RegExp('KB' + uid + 'v(\\d+)KB' + uid + 'v', 'g')
    html = html.replace(
      new RegExp('<p>\\s*KB' + uid + 'v(\\d+)KB' + uid + 'v\\s*</p>', 'g'),
      (_, i: string) => biliRefs[+i] ?? '',
    )
    html = html.replace(BILI_RE, (_, i: string) => '</p>' + (biliRefs[+i] ?? '') + '<p>')

    // 4.4.5 还原网易云播放器占位（我们构造的 iframe，不经过用户输入）
    html = html.replace(
      new RegExp('<p>\\s*KN' + uid + 'n(\\d+)KN' + uid + 'n\\s*</p>', 'g'),
      (_, i: string) => neteaseRefs[+i] ?? '',
    )
    html = html.replace(
      new RegExp('KN' + uid + 'n(\\d+)KN' + uid + 'n', 'g'),
      (_, i: string) => '</p>' + (neteaseRefs[+i] ?? '') + '<p>',
    )

    // 4.5 还原 @提及占位为用户主页链接
    html = html.replace(
      new RegExp(MENTION_MARK + '(\\d+)' + MENTION_MARK, 'g'),
      (_, i: string) => {
        const name = mentions[+i]
        if (!name) return ''
        return `<a class="mention" href="${withBase('/user/' + name)}">@${name}</a>`
      },
    )

    // 5. 还原公式占位（KaTeX 输出自身安全）
    html = html.replace(new RegExp(MATH_MARK + '(\\d+)' + MATH_MARK, 'g'), (_, i: string) => displayMath[+i] ?? '')

    // 5.5 还原行内代码占位
    html = html.replace(new RegExp(INLINE_CODE_MARK + '(\\d+)' + INLINE_CODE_MARK, 'g'), (_, i: string) => inlineCodes[+i] ?? '')

    // 6. 还原块级代码占位
    // 6.1 优先还原整段独立占位（marked 解析出的标准段落）
    html = html.replace(
      new RegExp('<p>\\s*' + BLOCK_CODE_MARK + '(\\d+)' + BLOCK_CODE_MARK + '\\s*</p>', 'g'),
      (_, i: string) => codeBlocks[+i] ?? '',
    )
    // 6.2 容错：若因粘连被标记进含 <br> 的段落，拆解出块级 div，避免非法嵌套到 <p> 内
    html = html.replace(
      new RegExp('(?:<br>\\s*)?' + BLOCK_CODE_MARK + '(\\d+)' + BLOCK_CODE_MARK + '(?:\\s*<br>)?', 'g'),
      (_, i: string) => '</p>' + (codeBlocks[+i] ?? '') + '<p>',
    )
    // 6.3 兜底直接替换
    html = html.replace(new RegExp(BLOCK_CODE_MARK + '(\\d+)' + BLOCK_CODE_MARK, 'g'), (_, i: string) => codeBlocks[+i] ?? '')
    // 清理拆解可能残留的空段落
    html = html.replace(/<p>\s*<\/p>/g, '')

    return html
  } catch (err) {
    console.error('[renderRichText] Failed to render rich text:', err)
    return '<p>' + escapeHtml(content).replace(/\n/g, '<br>') + '</p>'
  }
}
