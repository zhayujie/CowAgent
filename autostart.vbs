' ============================================================
' CowAgent autostart - SINGLE SOURCE of startup logic.
' Waits for network, then starts instance A hidden (no window).
'   Instance A: default data dir (project root, web port 9899)
'   The B instance is started only temporarily during gray
'   rollout (update.bat / promote.bat / abort.bat).
' The launcher in the Startup folder points here.
' To change boot behavior, edit ONLY this file.
' ============================================================
Set ws = CreateObject("Wscript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' Wait 10s for network to be ready after boot
WScript.Sleep 10000

' --- Instance A (wechat credentials persisted, no QR needed) ---
ws.CurrentDirectory = "c:\Users\Admin\projects\CowAgent"
ws.Run """C:\Program Files\Python312\python.exe"" app.py", 0, False

' Persist A's PID for the gray rollout scripts (promote.bat/abort.bat).
' NOTE: Run() returns 0 for async launches (not a process handle), so the
' PID is resolved via WMI instead. The query matches a command line that
' ENDS with the bare "app.py" (the desktop dev backend passes a full path
' and does not match).
grayDir = "c:\Users\Admin\projects\CowAgent\gray_state"
If Not fso.FolderExists(grayDir) Then fso.CreateFolder(grayDir)

Set wmi = GetObject("winmgmts:\\.\root\cimv2")
pid = 0
For attempt = 1 To 20
    Set procs = wmi.ExecQuery("SELECT ProcessId FROM Win32_Process WHERE Name = 'python.exe' AND CommandLine LIKE '%app.py'")
    For Each p In procs
        pid = p.ProcessId
        Exit For
    Next
    If pid <> 0 Then Exit For
    WScript.Sleep 500
Next

If pid <> 0 Then
    Set f = fso.CreateTextFile(grayDir & "\a.pid", True)
    f.Write CStr(pid)
    f.Close
End If
