@echo off
REM ============================================================
REM  CowAgent 灰度更新脚本 (update.bat)
REM  功能: 拉取远程最新代码 + 启动灰度验证实例 B (不重启 A)
REM  用法: 双击运行, 或让李大海说"更新代码"时自动执行 (精确指令, 防误触)
REM  位置: C:\Users\Admin\projects\CowAgent\update.bat
REM  灰度流程: 验证通过 -> promote.bat; 验证失败 -> abort.bat
REM ============================================================
chcp 65001 >nul
setlocal
cd /d "c:\Users\Admin\projects\CowAgent"

echo [1/6] 检查本地未提交改动...
set DIRTY=0
for /f "delims=" %%i in ('git status --porcelain') do set DIRTY=1
if %DIRTY%==1 (
    echo   ^> 发现未提交改动, 自动 stash 保存...
    REM 排除 update.bat 自身, 防止脚本被 stash 导致中断 (已加入 .gitignore, 双保险)
    git stash push -u -m "auto-stash before update" -- . ":(exclude)update.bat"
) else (
    echo   ^> 工作区干净
)

echo [2/6] 记录更新前 HEAD 并拉取远程最新代码...
if not exist "gray_state\" mkdir "gray_state"
for /f "delims=" %%h in ('git rev-parse HEAD') do > "gray_state\pre_head.txt" echo %%h
echo   ^> pre_head 已写入 gray_state\pre_head.txt
git fetch origin
if errorlevel 1 (
    echo   [失败] fetch 出错, 请检查网络.
    goto :FAIL
)

echo [3/6] 合并 origin/master 到当前分支...
git merge origin/master --no-edit
if errorlevel 1 (
    echo   [失败] 合并冲突! 请手动解决后重启.
    goto :FAIL
)

echo [4/6] 恢复本地改动并写入灰度状态...
if %DIRTY%==1 (
    git stash pop
    if errorlevel 1 (
        echo   [警告] stash pop 冲突, 请手动处理 [git stash list].
    )
) else (
    echo   ^> 无本地改动需要恢复
)
for /f "delims=" %%h in ('git rev-parse HEAD') do > "gray_state\post_head.txt" echo %%h
powershell -NoProfile -Command "(Get-Date).ToString('yyyyMMddHHmmss')" > "gray_state\update_time.txt"
echo   ^> post_head / update_time 已写入 gray_state\

echo [5/6] 启动灰度验证实例 B (COW_DATA_DIR 隔离, web 9900)...
echo   灰度验证中, 请勿重启 A
powershell -NoProfile -Command "$env:COW_DATA_DIR='C:\Users\Admin\cow-agent-2'; $p = Start-Process -FilePath 'C:\Program Files\Python312\python.exe' -ArgumentList 'app.py' -WorkingDirectory 'C:\Users\Admin\projects\CowAgent' -WindowStyle Hidden -PassThru; if ($p) { $p.Id | Out-File -FilePath 'C:\Users\Admin\projects\CowAgent\gray_state\b.pid' -Encoding ascii; Write-Host ('   > B started, PID ' + $p.Id + ' -> gray_state\b.pid') } else { Write-Host '   [FAIL] Failed to start B'; exit 1 }"
if errorlevel 1 (
    echo   [失败] B 启动失败, 请运行 abort.bat 回滚.
    goto :FAIL
)

echo.
echo [6/6] 灰度验证已就绪
echo   ============================================================
echo    灰度验证地址: http://127.0.0.1:9900/
echo    灰度验证中, 请勿重启 A
echo    验证通过后运行: promote.bat  (A 切新码 + 关闭 B)
echo    验证失败后运行: abort.bat    (关闭 B + git 回滚)
echo   ============================================================
exit /b 0

:FAIL
echo.
echo   更新中断, 请检查上方错误信息.
pause
exit /b 1
