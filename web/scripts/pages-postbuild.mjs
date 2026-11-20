/**
 * GitHub Pages 构建后处理：
 * 1. 复制 index.html 为 404.html —— Pages 没有 SPA 回退，
 *    刷新 /problems/1 这类 history 路由时靠它把请求交回前端；
 * 2. 写入 .nojekyll —— 避免以 "分支 + 根目录" 方式发布时被 Jekyll 处理。
 */
import { copyFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const dist = path.join(webRoot, 'dist')

await copyFile(path.join(dist, 'index.html'), path.join(dist, '404.html'))
await writeFile(path.join(dist, '.nojekyll'), '')

console.log('[pages] dist/404.html + dist/.nojekyll ready')
