@echo off
REM ============================================================
REM  CowAgent 开机自启脚本
REM  位置: 启动目录 (Shell:startup)
REM  功能: 开机后后台静默启动服务, 不留窗口
REM ============================================================

chcp 65001 >nul

REM 等待 10 秒, 确保开机后网络已就绪
ping -n 11 127.0.0.1 >nul

cd /d "c:\Users\Admin\projects\CowAgent"

REM 停止旧实例 (按命令行匹配 app.py + cmd /k 壳, 不影响其他 Python 程序)
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'python.exe' -and $_.CommandLine -like '*app.py*') -or ($_.Name -eq 'cmd.exe' -and $_.CommandLine -like '*cmd /k*app.py*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ('   > 已停止 PID ' + $_.ProcessId) }"

REM 等待进程退出, 释放端口
timeout /t 2 >nul

REM 后台静默启动 (微信登录凭证已持久化, 免扫码, 无需窗口)
powershell -NoProfile -Command "Start-Process -FilePath 'C:\Program Files\Python312\python.exe' -ArgumentList 'app.py' -WorkingDirectory 'C:\Users\Admin\projects\CowAgent' -WindowStyle Hidden"
