' ============================================================
'  CowAgent 一键更新 (隐藏执行 update.bat, 双击无黑窗口)
'  功能: 拉取远程代码 + 重启服务, 全程后台静默
' ============================================================
Set ws = CreateObject("Wscript.Shell")
ws.Run "c:\Users\Admin\projects\CowAgent\update.bat", 0, False
