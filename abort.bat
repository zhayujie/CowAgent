@echo off
REM ============================================================
REM  CowAgent abort 脚本: 灰度验证失败后回滚
REM  功能: 关 B + git 回滚到 pre_head + 条件重启 A
REM  用法: 验证失败后运行
REM  位置: C:\Users\Admin\projects\CowAgent\abort.bat
REM ============================================================
chcp 65001 >nul
setlocal
cd /d "c:\Users\Admin\projects\CowAgent"

echo [1/4] 停止灰度实例 B...
powershell -NoProfile -Command "$bId = Get-Content 'C:\Users\Admin\projects\CowAgent\gray_state\b.pid' -ErrorAction SilentlyContinue; if ($bId) { Stop-Process -Id $bId -Force -ErrorAction SilentlyContinue; Write-Host ('   > Stopped B via b.pid (PID ' + $bId + ')') }; $conn = Get-NetTCPConnection -LocalPort 9900 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if ($conn) { Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue; Write-Host ('   > Stopped B via port 9900 (PID ' + $conn.OwningProcess + ')') }; $deadline = (Get-Date).AddSeconds(30); while (Get-NetTCPConnection -LocalPort 9900 -State Listen -ErrorAction SilentlyContinue) { if ((Get-Date) -gt $deadline) { Write-Host '   [WARN] port 9900 still listening after 30s, kill manually'; break }; Start-Sleep -Seconds 1 }; Remove-Item 'C:\Users\Admin\projects\CowAgent\gray_state\b.pid' -ErrorAction SilentlyContinue; Write-Host '   [PASS] B stopped, b.pid removed'"

echo [2/4] 回滚代码到灰度前 HEAD...
set /p PRE_HEAD=<"gray_state\pre_head.txt"
if "%PRE_HEAD%"=="" (
    echo   [失败] gray_state\pre_head.txt 缺失或为空, 无法回滚.
    exit /b 1
)
echo   ^> git reset --hard %PRE_HEAD%
git reset --hard %PRE_HEAD%
if errorlevel 1 (
    echo   [失败] git reset 失败, 请手动处理.
    exit /b 1
)
for /f "delims=" %%s in ('git stash list') do set HAS_STASH=1
if defined HAS_STASH (
    echo   ^> 发现 stash, 执行 git stash pop...
    git stash pop
    if errorlevel 1 (
        echo   [警告] stash pop 冲突, 请手动处理 [git stash list / git stash drop].
    )
) else (
    echo   ^> 无 stash 需要恢复
)

echo [3/4] 检查 A 是否在灰度窗口内被重启过...
powershell -NoProfile -Command "$state = 'C:\Users\Admin\projects\CowAgent\gray_state'; $aId = Get-Content ($state + '\a.pid') -ErrorAction SilentlyContinue; $t = Get-Content ($state + '\update_time.txt') -ErrorAction SilentlyContinue; if (-not $aId -or -not $t) { Write-Host '   [WARN] a.pid/update_time.txt missing, skip A restart'; exit 0 }; $proc = Get-Process -Id $aId -ErrorAction SilentlyContinue; if (-not $proc) { Write-Host ('   [WARN] A process not found (PID ' + $aId + '), skip A restart'); exit 0 }; $upd = [DateTime]::ParseExact($t.Trim(), 'yyyyMMddHHmmss', $null); if ($proc.StartTime -gt $upd) { Write-Host ('   > A restarted after update_time (' + $proc.StartTime.ToString('yyyyMMddHHmmss') + ' > ' + $t.Trim() + '), restarting A on old code'); Stop-Process -Id $aId -Force -ErrorAction SilentlyContinue; $deadline = (Get-Date).AddSeconds(30); while (Get-NetTCPConnection -LocalPort 9899 -State Listen -ErrorAction SilentlyContinue) { if ((Get-Date) -gt $deadline) { Write-Host '   [WARN] port 9899 still listening, manual kill needed'; break }; Start-Sleep -Seconds 1 }; Remove-Item Env:COW_DATA_DIR -ErrorAction SilentlyContinue; $p = Start-Process -FilePath 'C:\Program Files\Python312\python.exe' -ArgumentList 'app.py' -WorkingDirectory 'C:\Users\Admin\projects\CowAgent' -WindowStyle Hidden -PassThru; if ($p) { $p.Id | Out-File -FilePath ($state + '\a.pid') -Encoding ascii; Write-Host ('   > A restarted on old code, PID ' + $p.Id + ' -> gray_state\a.pid') } else { Write-Host '   [FAIL] A restart failed, start manually: cd C:\Users\Admin\projects\CowAgent && C:\Program Files\Python312\python.exe app.py' } } else { Write-Host '   [PASS] A not restarted in gray window (still old code in memory), no action needed' }"

echo [4/4] 回滚完成
echo.
echo   ================================================
echo    回滚结果:
echo    - B 灰度实例已关闭
echo    - 代码已回到灰度前版本 (pre_head: %PRE_HEAD%)
echo    - A: 若灰度窗口内未被重启, 仍运行旧码内存态, 无需操作;
echo       若已被重启, 已按旧码重新启动
echo    建议:
echo    - 确认 A 微信通道正常 (http://127.0.0.1:9899/)
echo    - 检查 run.log 无异常
echo    - 修复问题后重新运行 update.bat
echo   ================================================
pause
exit /b 0
