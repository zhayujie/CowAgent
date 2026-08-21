' ============================================================
' CowAgent autostart - SINGLE SOURCE of startup logic.
' Waits for network, then starts BOTH instances hidden (no window).
'   Instance A: default data dir (project root, web port 9899)
'   Instance B: COW_DATA_DIR isolated (cow-agent-2, web port 9900)
' The launcher in the Startup folder points here.
' To change boot behavior, edit ONLY this file.
' ============================================================
Set ws = CreateObject("Wscript.Shell")

' Wait 10s for network to be ready after boot
WScript.Sleep 10000

' --- Instance A (wechat credentials persisted, no QR needed) ---
ws.CurrentDirectory = "c:\Users\Admin\projects\CowAgent"
ws.Run """C:\Program Files\Python312\python.exe"" app.py", 0, False

' --- Instance B: give A a head start, then launch with isolated data dir ---
WScript.Sleep 3000
ws.Environment("PROCESS")("COW_DATA_DIR") = "C:\Users\Admin\cow-agent-2"
ws.CurrentDirectory = "c:\Users\Admin\projects\CowAgent"
ws.Run """C:\Program Files\Python312\python.exe"" app.py", 0, False
