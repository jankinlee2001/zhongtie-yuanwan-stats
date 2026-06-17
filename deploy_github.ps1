# 一键部署到 GitHub Pages（需先完成 gh 登录或手动创建空仓库）
param(
  [string]$Repo = "zhongtie-yuanwan-stats",
  [string]$Owner = "jankinlee2001"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$gh = @(
  "$env:TEMP\gh-cli2\bin\gh.exe",
  "$env:ProgramFiles\GitHub CLI\gh.exe",
  "gh"
) | Where-Object { Test-Path $_ -or $_ -eq "gh" } | Select-Object -First 1

Write-Host "==> 生成最新看板 ..."
python publish_dashboard.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

git add -A
$dirty = git status --porcelain
if ($dirty) {
  git commit -m "chore: 更新看板数据"
}

$remote = "git@github.com:${Owner}/${Repo}.git"
if (-not (git remote get-url origin 2>$null)) {
  git remote add origin $remote
} else {
  git remote set-url origin $remote
}

if ($gh -and (Get-Command $gh -ErrorAction SilentlyContinue)) {
  $authed = & $gh auth status 2>$null
  if ($LASTEXITCODE -eq 0) {
    Write-Host "==> 创建/同步 GitHub 仓库 ..."
    & $gh repo view "${Owner}/${Repo}" 2>$null
    if ($LASTEXITCODE -ne 0) {
      & $gh repo create "${Owner}/${Repo}" --public --source=. --remote=origin --push
    } else {
      git push -u origin main
    }
    Write-Host "==> 触发 Actions 更新 ..."
    & $gh workflow run "更新数据看板"
    Write-Host ""
    Write-Host "公网地址（Actions 跑完约 1-2 分钟后生效）："
    Write-Host "  https://${Owner}.github.io/${Repo}/"
    Write-Host ""
    Write-Host "若首次部署，请到仓库 Settings -> Pages，Branch 选 gh-pages。"
    exit 0
  }
}

Write-Host "==> 推送到 $remote ..."
git branch -M main
git push -u origin main
Write-Host ""
Write-Host "已推送。请到 GitHub 仓库 Actions 手动 Run workflow，并在 Settings -> Pages 开启 gh-pages 分支。"
Write-Host "公网地址: https://${Owner}.github.io/${Repo}/"
