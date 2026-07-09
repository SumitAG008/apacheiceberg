# sync_and_push.ps1 -- Meldra AI GitHub Sync
# Usage: .\sync_and_push.ps1
#        .\sync_and_push.ps1 -Message "your message"
param(
    [string]$Message = "feat(dqe+ui): Query Lab tab, DQE REST endpoints, CI/CD upgrade",
    [switch]$DryRun  = $false
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoRoot

Write-Host "=== MELDRA - GitHub Sync ===" -ForegroundColor Magenta
Write-Host "Repo: $RepoRoot" -ForegroundColor Cyan

# 1. Check git
try { $null = git --version } catch { Write-Host "ERROR: git not found" -ForegroundColor Red; exit 1 }
Write-Host "OK: git found" -ForegroundColor Green

if (-not (Test-Path "$RepoRoot\.git")) {
    Write-Host "ERROR: Not a git repo" -ForegroundColor Red; exit 1
}

$RemoteUrl = git remote get-url origin 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: No origin remote set" -ForegroundColor Red; exit 1
}
Write-Host "OK: Remote = $RemoteUrl" -ForegroundColor Green

# 2. Show status
Write-Host "`nChanged files:" -ForegroundColor Yellow
git status --short

$Status = git status --short
if ([string]::IsNullOrWhiteSpace($Status)) {
    Write-Host "Nothing to commit. Already in sync." -ForegroundColor Yellow
    exit 0
}

# 3. Stage all changes
Write-Host "`nStaging all changes..." -ForegroundColor Yellow
git add -A
$Staged = git diff --cached --stat
if ([string]::IsNullOrWhiteSpace($Staged)) {
    Write-Host "Nothing staged." -ForegroundColor Yellow
    exit 0
}
Write-Host $Staged

# 4. Commit
if ($DryRun) {
    Write-Host "`nDRY RUN - would commit: $Message" -ForegroundColor Cyan
} else {
    Write-Host "`nCommitting..." -ForegroundColor Yellow
    git commit -m $Message
    if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: Commit failed" -ForegroundColor Red; exit 1 }
    Write-Host "OK: Committed" -ForegroundColor Green

    # 5. Push
    Write-Host "`nPushing to origin/main..." -ForegroundColor Yellow
    git push origin main
    if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: Push failed" -ForegroundColor Red; exit 1 }
    Write-Host "OK: Pushed successfully!" -ForegroundColor Green
}

# 6. Print links
Write-Host "`n=== MONITOR DEPLOYMENTS ===" -ForegroundColor Magenta
$GH_Repo = $RemoteUrl -replace "^https://github.com/","" -replace "^git@github.com:","" -replace "\.git$",""
Write-Host "GitHub Actions CI:  https://github.com/$GH_Repo/actions" -ForegroundColor Cyan
Write-Host "Railway (backend):  https://railway.app/dashboard" -ForegroundColor Cyan
Write-Host "Vercel (frontend):  https://vercel.com/dashboard" -ForegroundColor Cyan
Write-Host "`nDQE endpoints to test after deploy:" -ForegroundColor Yellow
Write-Host "  GET  /v1/query/modes" -ForegroundColor Gray
Write-Host "  POST /v1/query/submit  {mode:'sql', namespace:'default', table_name:'...', sql:'SELECT ...'}" -ForegroundColor Gray
Write-Host "  POST /v1/query/explain {mode:'sql', ...}" -ForegroundColor Gray
Write-Host "  GET  /v1/query/history" -ForegroundColor Gray
Write-Host "`nQuery Lab UI: click the [Flask] Query Lab tab in the nav bar" -ForegroundColor Yellow
Write-Host "`nDone!" -ForegroundColor Green
