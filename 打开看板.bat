@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 中铁元湾 - 数据看板
echo.
echo ========================================
echo   中铁元湾篮球队 - 数据看板
echo ========================================
echo.
echo 正在启动，浏览器将自动打开...
echo 地址: http://127.0.0.1:8899/index.html
echo.
echo 【重要】请保持此窗口打开，关闭后看板无法访问
echo.
python open_dashboard.py --regen
echo.
pause
