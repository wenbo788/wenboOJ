<#
.SYNOPSIS
    NLNOJ 全量测试脚本（后端 pytest + 前端 vue-tsc）。

.DESCRIPTION
    在仓库根目录执行即可。脚本会自动定位 service/ 与 web/，分别运行：
      1) 后端全量 pytest（含异步用例）
      2) 前端 TypeScript 类型检查（vue-tsc --noEmit）
    任一环节失败，脚本以非 0 退出码结束。

.PARAMETER Only
    只跑指定环节：backend / frontend / quick（默认跑全部）。
    quick = 只跑后端最近一次受影响的核心测试集合（快速自检）。

.PARAMETER Keyword
    传给 pytest 的 -k 关键字过滤，例如 -Keyword "privacy"。

.EXAMPLE
    .\test.ps1
    .\test.ps1 -Only backend
    .\test.ps1 -Keyword "attachment or privacy"
    .\test.ps1 -Only quick
#>
[CmdletBinding()]
param(
    [ValidateSet('all', 'backend', 'frontend', 'quick')]
    [string]$Only = 'all',
    [string]$Keyword = ''
)

$ErrorActionPreference = 'Continue'
$root = $PSScriptRoot
$serviceDir = Join-Path $root 'service'
$webDir = Join-Path $root 'web'
$py = Join-Path $serviceDir '.venv\Scripts\python.exe'

$script:failed = $false

function Write-Header($text) {
    Write-Host ''
    Write-Host ('=' * 60) -ForegroundColor DarkCyan
    Write-Host "  $text" -ForegroundColor Cyan
    Write-Host ('=' * 60) -ForegroundColor DarkCyan
}

function Invoke-Backend([string[]]$extraArgs) {
    Write-Header '后端：pytest 全量测试'
    if (-not (Test-Path $py)) {
        Write-Host "[!] 未找到虚拟环境解释器：$py" -ForegroundColor Red
        Write-Host '    请先在 service/ 下创建 .venv 并安装依赖。' -ForegroundColor Yellow
        $script:failed = $true
        return
    }
    Push-Location $serviceDir
    try {
        $args = @('-m', 'pytest', '-q', '--tb=short') + $extraArgs
        & $py @args
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[x] 后端测试失败（退出码 $LASTEXITCODE）" -ForegroundColor Red
            $script:failed = $true
        } else {
            Write-Host '[√] 后端测试通过' -ForegroundColor Green
        }
    } finally {
        Pop-Location
    }
}

function Invoke-Frontend {
    Write-Header '前端：vue-tsc 类型检查'
    if (-not (Test-Path $webDir)) {
        Write-Host "[!] 未找到前端目录：$webDir" -ForegroundColor Red
        $script:failed = $true
        return
    }
    if (-not (Test-Path (Join-Path $webDir 'node_modules'))) {
        Write-Host '[!] web/node_modules 不存在，请先执行 npm install' -ForegroundColor Yellow
        $script:failed = $true
        return
    }
    Push-Location $webDir
    try {
        npx vue-tsc --noEmit
        if ($LASTEXITCODE -ne 0) {
            Write-Host '[x] 前端类型检查失败' -ForegroundColor Red
            $script:failed = $true
        } else {
            Write-Host '[√] 前端类型检查通过' -ForegroundColor Green
        }
    } finally {
        Pop-Location
    }
}

# ---- 调度 ----
switch ($Only) {
    'backend' {
        $extra = if ($Keyword) { @('-k', $Keyword) } else { @() }
        Invoke-Backend $extra
    }
    'frontend' {
        Invoke-Frontend
    }
    'quick' {
        # 快速自检：只跑与本次改动最相关的核心回归集
        Invoke-Backend @(
            'tests/test_public_user_privacy.py',
            'tests/test_team_ban.py',
            'tests/test_admin_reason.py',
            'tests/test_migration_revision_ids.py'
        )
    }
    default {
        $extra = if ($Keyword) { @('-k', $Keyword) } else { @() }
        Invoke-Backend $extra
        Invoke-Frontend
    }
}

Write-Host ''
if ($script:failed) {
    Write-Host ('=' * 60) -ForegroundColor Red
    Write-Host '  结果：存在失败项 ✗' -ForegroundColor Red
    Write-Host ('=' * 60) -ForegroundColor Red
    exit 1
} else {
    Write-Host ('=' * 60) -ForegroundColor Green
    Write-Host '  结果：全部通过 ✓' -ForegroundColor Green
    Write-Host ('=' * 60) -ForegroundColor Green
    exit 0
}
