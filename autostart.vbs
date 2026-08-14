' ============================================================
' CowAgent autostart - SINGLE SOURCE of startup logic.
' Waits for network, then starts the service hidden (no window).
' The launcher in the Startup folder points here.
' To change boot behavior, edit ONLY this file.
' ============================================================
Set ws = CreateObject("Wscript.Shell")

' Wait 10s for network to be ready after boot
WScript.Sleep 10000

' Start service hidden (wechat credentials persisted, no QR needed)
ws.CurrentDirectory = "c:\Users\Admin\projects\CowAgent"
ws.Run """C:\Program Files\Python312\python.exe"" app.py", 0, False
