@echo off
REM ============================================================
REM  CowAgent 一键更新脚本
REM  功能: 拉取远程最新代码 + 重启服务
REM  用法: 双击运行, 或让李大海说"更新代码"时自动执行 (精确指令, 防误触)
REM  位置: C:\Users\Admin\projects\CowAgent\update.bat
REM ============================================================
chcp 65001 >nul
setlocal
cd /d "c:\Users\Admin\projects\CowAgent"

echo [1/5] 检查本地未提交改动...
set DIRTY=0
for /f "delims=" %%i in ('git status --porcelain') do set DIRTY=1
if %DIRTY%==1 (
    echo   ^> 发现未提交改动, 自动 stash 保存...
    REM 排除 update.bat 自身, 防止脚本被 stash 导致中断 (已加入 .gitignore, 双保险)
    git stash push -u -m "auto-stash before update" -- . ':(exclude)update.bat'
) else (
    echo   ^> 工作区干净
)

echo [2/5] 拉取远程最新代码...
git fetch origin
if errorlevel 1 (
    echo   [失败] fetch 出错, 请检查网络.
    goto :FAIL
)

echo   ^> 合并 origin/master 到当前分支...
git merge origin/master --no-edit
if errorlevel 1 (
    echo   [失败] 合并冲突! 请手动解决后重启.
    goto :FAIL
)

if %DIRTY%==1 (
    echo [3/5] 恢复本地未提交改动...
    git stash pop
    if errorlevel 1 (
        echo   [警告] stash pop 冲突, 请手动处理 (git stash list).
    )
) else (
    echo [3/5] 无本地改动需要恢复
)

echo [4/5] 停止旧服务 (按命令行匹配 app.py + cmd /k 壳, 不影响其他 Python 程序)...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'python.exe' -and $_.CommandLine -like '*app.py*') -or ($_.Name -eq 'cmd.exe' -and $_.CommandLine -like '*cmd /k*app.py*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ('   ^> 已停止 PID ' + $_.ProcessId) }"

echo [5/5] 启动双实例 (后台静默, 无窗口)...
REM 实例 A: 默认数据目录 (项目根, web 端口 9899, 凭证 ~/.weixin_cow_credentials.json)
powershell -NoProfile -Command "Start-Process -FilePath 'C:\Program Files\Python312\python.exe' -ArgumentList 'app.py' -WorkingDirectory 'C:\Users\Admin\projects\CowAgent' -WindowStyle Hidden"
REM 实例 B: COW_DATA_DIR 隔离 (cow-agent-2, web 端口 9900, 凭证 cow-agent-2\weixin_credentials.json)
powershell -NoProfile -Command "$env:COW_DATA_DIR='C:\Users\Admin\cow-agent-2'; Start-Process -FilePath 'C:\Program Files\Python312\python.exe' -ArgumentList 'app.py' -WorkingDirectory 'C:\Users\Admin\projects\CowAgent' -WindowStyle Hidden"
echo.
echo   ========================================
echo    更新完成! 双实例已在后台运行.
echo    实例A日志: run.log (端口 9899)
echo    实例B日志: cow-agent-2\run.log (端口 9900, 首次需扫码)
echo   ========================================
exit /b 0

:FAIL
echo.
echo   更新中断, 请检查上方错误信息.
pause
exit /b 1
