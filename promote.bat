@echo off
REM ============================================================
REM  CowAgent promote 脚本: 灰度验证通过后, A 切新码 + 关闭 B
REM  功能: 前置断言 -> 杀 A -> 重启 A(新码) -> 健康检查 -> 关 B
REM  用法: 在 http://127.0.0.1:9900/ 验证通过后运行
REM  位置: C:\Users\Admin\projects\CowAgent\promote.bat
REM ============================================================
chcp 65001 >nul
setlocal
cd /d "c:\Users\Admin\projects\CowAgent"

echo [1/6] 前置断言检查...

REM --- a. B must be alive: b.pid exists and process running ---
powershell -NoProfile -Command "$bId = Get-Content 'C:\Users\Admin\projects\CowAgent\gray_state\b.pid' -ErrorAction SilentlyContinue; if (-not $bId) { Write-Host '   [FAIL] gray_state\b.pid missing'; exit 1 }; if (-not (Get-Process -Id $bId -ErrorAction SilentlyContinue)) { Write-Host ('   [FAIL] B process not alive (PID ' + $bId + ')'); exit 1 }; Write-Host ('   [PASS] B alive (PID ' + $bId + ')')"
if errorlevel 1 (
    echo   [断言失败] B 实例未在运行, 中止 promote.
    exit /b 1
)

REM --- b. 9900 must be listening (B web) ---
powershell -NoProfile -Command "if (-not (Get-NetTCPConnection -LocalPort 9900 -State Listen -ErrorAction SilentlyContinue)) { Write-Host '   [FAIL] port 9900 not listening'; exit 1 }; Write-Host '   [PASS] port 9900 listening (B web)'"
if errorlevel 1 (
    echo   [断言失败] B 的 web 9900 未监听, 中止 promote.
    exit /b 1
)

REM --- c. 9899 must be listening (A running) ---
powershell -NoProfile -Command "if (-not (Get-NetTCPConnection -LocalPort 9899 -State Listen -ErrorAction SilentlyContinue)) { Write-Host '   [FAIL] port 9899 not listening (A down?)'; exit 1 }; Write-Host '   [PASS] port 9899 listening (A running)'"
if errorlevel 1 (
    echo   [断言失败] A 实例 [9899] 未在运行, 中止 promote.
    exit /b 1
)

REM --- d. current HEAD must equal post_head.txt ---
for /f "delims=" %%h in ('git rev-parse HEAD') do set CUR_HEAD=%%h
set /p POST_HEAD=<"gray_state\post_head.txt"
if not "%CUR_HEAD%"=="%POST_HEAD%" (
    echo   [断言失败] 当前 HEAD 与灰度验证代码不一致:
    echo     current: %CUR_HEAD%
    echo     expected: %POST_HEAD%
    exit /b 1
)
echo   [PASS] HEAD matches post_head (%POST_HEAD%)

REM --- e. A must NOT have been restarted inside the gray window ---
powershell -NoProfile -Command "$state = 'C:\Users\Admin\projects\CowAgent\gray_state'; $aId = Get-Content ($state + '\a.pid') -ErrorAction SilentlyContinue; if (-not $aId) { Write-Host '   [WARN] a.pid missing, skip A-restart check'; exit 0 }; $t = Get-Content ($state + '\update_time.txt') -ErrorAction SilentlyContinue; if (-not $t) { Write-Host '   [WARN] update_time.txt missing, skip A-restart check'; exit 0 }; $proc = Get-Process -Id $aId -ErrorAction SilentlyContinue; if (-not $proc) { Write-Host ('   [FAIL] a.pid process not found (PID ' + $aId + ')'); exit 1 }; $upd = [DateTime]::ParseExact($t.Trim(), 'yyyyMMddHHmmss', $null); if ($proc.StartTime -ge $upd) { Write-Host ('   [FAIL] A restarted after update_time (StartTime ' + $proc.StartTime.ToString('yyyyMMddHHmmss') + ' >= ' + $t.Trim() + ')'); exit 1 }; Write-Host '   [PASS] A not restarted in gray window'"
if errorlevel 1 (
    echo   [断言失败] A 在灰度窗口内被重启过, 可能已加载未验证代码, 中止 promote.
    exit /b 1
)

echo.
echo [2/6] 停止 A (9899)...
powershell -NoProfile -Command "$conn = Get-NetTCPConnection -LocalPort 9899 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if ($conn) { Write-Host ('   > Stopping A (PID ' + $conn.OwningProcess + ')'); Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue } else { Write-Host '   [WARN] port 9899 not listening, nothing to stop' }; $deadline = (Get-Date).AddSeconds(30); while (Get-NetTCPConnection -LocalPort 9899 -State Listen -ErrorAction SilentlyContinue) { if ((Get-Date) -gt $deadline) { Write-Host '   [FAIL] port 9899 still listening after 30s'; exit 1 }; Start-Sleep -Seconds 1 }; Write-Host '   [PASS] port 9899 released'"
if errorlevel 1 (
    echo   [失败] 无法停止 A, 中止 promote.
    exit /b 1
)

echo [3/6] 重启 A (新代码)...
if not exist "gray_state\" mkdir "gray_state"
powershell -NoProfile -Command "Remove-Item Env:COW_DATA_DIR -ErrorAction SilentlyContinue; $p = Start-Process -FilePath 'C:\Program Files\Python312\python.exe' -ArgumentList 'app.py' -WorkingDirectory 'C:\Users\Admin\projects\CowAgent' -WindowStyle Hidden -PassThru; if (-not $p) { Write-Host '   [FAIL] failed to start A'; exit 1 }; $p.Id | Out-File -FilePath 'C:\Users\Admin\projects\CowAgent\gray_state\a.pid' -Encoding ascii; Write-Host ('   > A started, PID ' + $p.Id + ' -> gray_state\a.pid')"
if errorlevel 1 (
    echo   [失败] A 启动失败, 请运行 abort.bat 回滚.
    exit /b 1
)

echo [4/6] 健康检查 (web 9899 + run.log, 最多 60s)...
powershell -NoProfile -Command "$deadline = (Get-Date).AddSeconds(60); $webOk = $false; while ((Get-Date) -lt $deadline) { try { $r = Invoke-WebRequest 'http://127.0.0.1:9899/' -TimeoutSec 3 -UseBasicParsing; if ($r.StatusCode -eq 200) { $webOk = $true; break } } catch { }; Start-Sleep -Seconds 2 }; if (-not $webOk) { Write-Host '   [FAIL] web 9899 not reachable within 60s'; exit 1 }; Write-Host '   [PASS] web 9899 reachable'; $log = 'C:\Users\Admin\projects\CowAgent\run.log'; if (Test-Path $log) { $bad = Get-Content $log -Tail 200 -ErrorAction SilentlyContinue | Where-Object { $_ -match 'Traceback|Unhandled exception' }; if ($bad) { Write-Host '   [FAIL] run.log tail contains Traceback/Unhandled exception'; exit 1 }; Write-Host '   [PASS] run.log clean (last 200 lines)' } else { Write-Host '   [WARN] run.log not found, skip log check' }"
if errorlevel 1 (
    echo   [失败] A 启动失败或日志异常!
    echo   请运行 abort.bat 回滚 [B 仍在运行, 可供复现问题].
    exit /b 1
)

echo [5/6] 关闭灰度实例 B 并清理...
powershell -NoProfile -Command "$bId = Get-Content 'C:\Users\Admin\projects\CowAgent\gray_state\b.pid' -ErrorAction SilentlyContinue; if ($bId) { Stop-Process -Id $bId -Force -ErrorAction SilentlyContinue; Write-Host ('   > Stopped B via b.pid (PID ' + $bId + ')') }; $conn = Get-NetTCPConnection -LocalPort 9900 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if ($conn) { Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue; Write-Host ('   > Stopped B via port 9900 (PID ' + $conn.OwningProcess + ')') }; $deadline = (Get-Date).AddSeconds(30); while (Get-NetTCPConnection -LocalPort 9900 -State Listen -ErrorAction SilentlyContinue) { if ((Get-Date) -gt $deadline) { Write-Host '   [WARN] port 9900 still listening after 30s, kill manually'; exit 0 }; Start-Sleep -Seconds 1 }; Remove-Item 'C:\Users\Admin\projects\CowAgent\gray_state\b.pid' -ErrorAction SilentlyContinue; Write-Host '   [PASS] B stopped, port 9900 released, b.pid removed'"

echo.
echo [6/6] Promote 完成
echo   ================================================
echo    Promote 成功! A 已切换到新代码 (http://127.0.0.1:9899/)
echo    B 灰度实例已关闭, 灰度验证完成
echo   ================================================
pause
exit /b 0
