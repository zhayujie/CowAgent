# Custom NSIS hooks, picked up automatically by electron-builder as
# <buildResources>/installer.nsh. Included in both the installer and the
# uninstaller script, so a macro only takes effect where it is inserted.

!include nsDialogs.nsh
!include WordFunc.nsh

# Workspace location page, shown after electron-builder's directory page.
#
# The Agent workspace goes into a "cow" folder inside the folder picked here,
# which defaults to the user profile (~/cow). Another choice is recorded in the
# pointer file the app reads at startup (src/main/workspace-location.ts); keep
# the path and format in sync. Config and credentials (~/.cow) never move.
!define COW_LOCATION_DIR "CowAgent"
!define COW_LOCATION_FILE "workspace-location.json"

!macro customPageAfterChangeDir
  Var cowWorkspaceRoot
  Var cowWorkspaceRootField

  Page custom cowWorkspaceLocationPageCreate cowWorkspaceLocationPageLeave

  Function cowWorkspaceLocationPageCreate
    # Only asked while there is no workspace yet. An existing one keeps its
    # location (choosing another here would not move the files); relocating it
    # is done from the app's Settings. Config and keys play no part in this.
    ${If} ${isUpdated}
      Abort
    ${EndIf}
    # The pointer is per user even for an all-users install.
    StrCpy $0 "0"
    SetShellVarContext current
    ${If} ${FileExists} "$APPDATA\${COW_LOCATION_DIR}\${COW_LOCATION_FILE}"
    ${OrIf} ${FileExists} "$PROFILE\cow\*.*"
      StrCpy $0 "1"
    ${EndIf}
    ${If} $installMode == "all"
      SetShellVarContext all
    ${EndIf}
    ${If} $0 == "1"
      StrCpy $cowWorkspaceRoot ""
      Abort
    ${EndIf}

    ${If} $cowWorkspaceRoot == ""
      StrCpy $cowWorkspaceRoot "$PROFILE"
    ${EndIf}

    ${If} $LANGUAGE == 2052
      !insertmacro MUI_HEADER_TEXT "工作空间位置" "选择 ${PRODUCT_NAME} 保存对话记录、记忆和知识库的位置。"
      StrCpy $R1 "将在所选文件夹下创建 cow 目录作为工作空间，存放对话记录、记忆、知识库和技能。$\r$\n$\r$\n工作空间会随使用增长，建议选择空间充足的磁盘。安装后可随时在「设置」中更改并迁移。"
      StrCpy $R2 "浏览..."
    ${Else}
      !insertmacro MUI_HEADER_TEXT "Workspace Location" "Choose where ${PRODUCT_NAME} keeps conversations, memory and the knowledge base."
      StrCpy $R1 "A cow folder is created inside the selected folder as the workspace, holding conversations, memory, the knowledge base and skills.$\r$\n$\r$\nThe workspace grows with use, so pick a drive with enough free space. You can change and migrate it later in Settings."
      StrCpy $R2 "Browse..."
    ${EndIf}

    nsDialogs::Create 1018
    Pop $0
    ${If} $0 == error
      Abort
    ${EndIf}

    ${NSD_CreateLabel} 0 0 100% 52u "$R1"
    Pop $0
    ${NSD_CreateDirRequest} 0 60u 76% 13u "$cowWorkspaceRoot"
    Pop $cowWorkspaceRootField
    ${NSD_CreateBrowseButton} 78% 59u 22% 15u "$R2"
    Pop $0
    ${NSD_OnClick} $0 cowWorkspaceLocationBrowse

    nsDialogs::Show
  FunctionEnd

  Function cowWorkspaceLocationBrowse
    Pop $0
    ${NSD_GetText} $cowWorkspaceRootField $0
    nsDialogs::SelectFolderDialog "" "$0"
    Pop $0
    ${If} $0 != error
      ${NSD_SetText} $cowWorkspaceRootField "$0"
    ${EndIf}
  FunctionEnd

  Function cowWorkspaceLocationPageLeave
    ${NSD_GetText} $cowWorkspaceRootField $0

    # Drop a trailing separator, except on a drive root ("D:\").
    StrCpy $1 $0 1 -1
    StrLen $2 $0
    ${If} $1 == "\"
    ${AndIf} $2 > 3
      IntOp $2 $2 - 1
      StrCpy $0 $0 $2
    ${EndIf}

    StrCpy $1 $0 1 1
    StrCpy $3 $0 2
    ${If} $1 != ":"
    ${AndIf} $3 != "\\"
      ${If} $LANGUAGE == 2052
        MessageBox MB_ICONEXCLAMATION|MB_OK "请选择一个完整的文件夹路径，例如 D:\CowAgentData。"
      ${Else}
        MessageBox MB_ICONEXCLAMATION|MB_OK "Please choose a full folder path, for example D:\CowAgentData."
      ${EndIf}
      Abort
    ${EndIf}

    # An update deletes the install directory, so data kept inside it would be
    # wiped by the next release. Checked on the workspace itself ($5): picking
    # D:\ with the app installed in D:\cow must be refused too.
    StrCpy $1 $0 1 -1
    ${If} $1 == "\"
      StrCpy $5 "$0cow"
    ${Else}
      StrCpy $5 "$0\cow"
    ${EndIf}
    StrLen $2 "$INSTDIR"
    StrCpy $3 $5 $2
    StrCpy $4 $5 1 $2
    ${If} $3 == "$INSTDIR"
      ${If} $4 == ""
      ${OrIf} $4 == "\"
        ${If} $LANGUAGE == 2052
          MessageBox MB_ICONEXCLAMATION|MB_OK "工作空间不能放在安装目录内，升级时安装目录会被清空。请选择其他文件夹。"
        ${Else}
          MessageBox MB_ICONEXCLAMATION|MB_OK "The workspace can't be inside the install folder, which is replaced on every update. Please choose another folder."
        ${EndIf}
        Abort
      ${EndIf}
    ${EndIf}

    # The Agent can read and write everything in its workspace, so it must not
    # sit inside the folder holding config and credentials.
    StrLen $2 "$PROFILE\.cow"
    StrCpy $3 $0 $2
    StrCpy $4 $0 1 $2
    ${If} $3 == "$PROFILE\.cow"
      ${If} $4 == ""
      ${OrIf} $4 == "\"
        ${If} $LANGUAGE == 2052
          MessageBox MB_ICONEXCLAMATION|MB_OK "工作空间不能放在配置和密钥目录（.cow）内，请选择其他文件夹。"
        ${Else}
          MessageBox MB_ICONEXCLAMATION|MB_OK "The workspace can't be inside the settings and keys folder (.cow). Please choose another folder."
        ${EndIf}
        Abort
      ${EndIf}
    ${EndIf}

    ClearErrors
    CreateDirectory "$0"
    FileOpen $1 "$0\.cow-write-test" w
    ${If} ${Errors}
      ${If} $LANGUAGE == 2052
        MessageBox MB_ICONEXCLAMATION|MB_OK "无法写入该文件夹，请选择其他位置：$\r$\n$0"
      ${Else}
        MessageBox MB_ICONEXCLAMATION|MB_OK "This folder isn't writable, please choose another one:$\r$\n$0"
      ${EndIf}
      Abort
    ${EndIf}
    FileClose $1
    Delete "$0\.cow-write-test"

    StrCpy $cowWorkspaceRoot $0
  FunctionEnd
!macroend

# Records a non-default workspace location for the app. Written UTF-16LE with a
# BOM: FileWrite would emit the ANSI code page and mangle a non-ASCII path.
!macro cowWriteWorkspaceLocation
  ${If} $cowWorkspaceRoot != ""
  ${AndIf} $cowWorkspaceRoot != "$PROFILE"
    # The pointer is per user even for an all-users install.
    SetShellVarContext current
    CreateDirectory "$APPDATA\${COW_LOCATION_DIR}"
    ${WordReplace} "$cowWorkspaceRoot" "\" "/" "+" $0
    ClearErrors
    FileOpen $1 "$APPDATA\${COW_LOCATION_DIR}\${COW_LOCATION_FILE}" w
    ${IfNot} ${Errors}
      FileWriteWord $1 0xFEFF
      FileWriteUTF16LE $1 '{"workspace": "$0/cow"}'
      FileClose $1
    ${EndIf}
    ${If} $installMode == "all"
      SetShellVarContext all
    ${EndIf}
  ${EndIf}
!macroend

# Replaces electron-builder's default update-removal step, which stages the old
# installation before deleting it:
#
#   CreateDirectory "$PLUGINSDIR\old-install"
#   Call un.atomicRMDir          ; MOVES every file, incl. the app executable
#   RMDir /r $INSTDIR
#
# That move is what breaks desktop shortcuts across an update. While the
# executable sits in the staging folder (under %TEMP%) and the install dir is
# gone, the shell resolves the shortcuts pointing at it, follows the file to its
# new location through NTFS link tracking, and persists that temp path back into
# the .lnk. The installer then deletes the staging folder on exit, so the user is
# left with a shortcut reporting that the item has been moved or renamed.
#
# Deleting in place never gives link tracking a new location to follow: the .lnk
# keeps its original target, which becomes valid again as soon as the new version
# is written to the same directory. The staging only existed to roll back a
# failed removal, and the fallback for that was this same delete anyway.
!macro customRemoveFiles
  # Retry: a file can still be locked by an instance that is on its way out.
  StrCpy $R9 0
  cowRemoveLoop:
    ClearErrors
    RMDir /r "$INSTDIR"
    ${IfNot} ${FileExists} "$INSTDIR\*.*"
      Goto cowRemoveDone
    ${EndIf}
    IntOp $R9 $R9 + 1
    ${If} $R9 < 10
      Sleep 300
      Goto cowRemoveLoop
    ${EndIf}
  cowRemoveDone:
  ClearErrors
!macroend

# Second extraction pass when the first one may have left files out.
#
# electron-builder extracts the app into $PLUGINSDIR\7z-out and copies it into
# $INSTDIR, retrying while a file is held (security software scanning what was
# just written, a process still on its way out). If the copy keeps failing, a
# silent update falls back to deleting the staging folder and extracting
# straight over $INSTDIR with errors ignored: whatever is still held is simply
# missing, and the app comes up with a backend that fails on every message.
# The missing staging folder is the only trace that path leaves, so extract
# again a little later, once a passing lock has usually cleared. A normal
# install keeps the folder and skips this entirely.
!macro cowReextractIfForced
  !ifndef APP_BUILD_DIR
  !ifndef APP_PACKAGE_URL
  !ifndef ZIP_COMPRESSION
    ${IfNot} ${FileExists} "$PLUGINSDIR\7z-out\*.*"
    ${AndIf} ${FileExists} "$PLUGINSDIR\app-$packageArch.7z"
      Push $OUTDIR
      Push $R8
      SetOutPath $INSTDIR
      StrCpy $R8 0
      cowReextractLoop:
        IntOp $R8 $R8 + 1
        Sleep 2000
        Nsis7z::Extract "$PLUGINSDIR\app-$packageArch.7z"
        ${If} $R8 < 2
          Goto cowReextractLoop
        ${EndIf}
      Pop $R8
      Exch $0
      SetOutPath $0
      Pop $0
    ${EndIf}
  !endif
  !endif
  !endif
!macroend

# Repair pass for shortcuts an earlier update already damaged.
#
# customRemoveFiles above only stops NEW damage, and only from the version after
# next: an update runs the OLD version's uninstaller (uninstallOldVersion copies
# $INSTDIR's uninstaller to $PLUGINSDIR and executes that), so the staging move
# still happens on the way in from any build released before it. This macro is
# what has to cope with the result, and it runs in the NEW installer, so it
# covers that transition.
#
# An update deliberately leaves existing shortcuts alone: addDesktopLink runs
# with keepShortcuts enabled, and its only other branch needs the recorded name
# to differ from the current one. So a .lnk whose target the shell rewrote to the
# staging path is never corrected, and the app can't correct it either while the
# user has no working way to launch it.
#
# Rewriting a shortcut regenerates its target and its shell link-tracking data
# from $appExe, which is what actually repairs it. When NOTHING is left to click
# a shortcut is created, on an update and on a manual reinstall alike: a
# reinstall over an existing app keeps shortcuts too (keepShortcuts), so one an
# interrupted first install never created would otherwise never appear. A stray
# extra icon is a far smaller problem than no way into the app.
!macro customInstall
  !insertmacro cowReextractIfForced
  !insertmacro cowWriteWorkspaceLocation

  !ifndef DO_NOT_CREATE_DESKTOP_SHORTCUT
    ${If} ${FileExists} "$newDesktopLink"
      CreateShortCut "$newDesktopLink" "$appExe" "" "$appExe" 0 "" "" "${APP_DESCRIPTION}"
      ClearErrors
      WinShell::SetLnkAUMI "$newDesktopLink" "${APP_ID}"
    ${EndIf}
    # A build that renames its shortcut at runtime leaves the file under the
    # recorded name instead, which addDesktopLink may not have renamed.
    ${If} $oldDesktopLink != $newDesktopLink
    ${AndIf} ${FileExists} "$oldDesktopLink"
      CreateShortCut "$oldDesktopLink" "$appExe" "" "$appExe" 0 "" "" "${APP_DESCRIPTION}"
      ClearErrors
      WinShell::SetLnkAUMI "$oldDesktopLink" "${APP_ID}"
    ${EndIf}
    # Neither recorded name is present: the shortcut was renamed by a build that
    # never told the installer (so it is invisible here and possibly broken), or
    # it is simply gone. Leave a working one behind.
    ${IfNot} ${isNoDesktopShortcut}
    ${AndIfNot} ${FileExists} "$newDesktopLink"
    ${AndIfNot} ${FileExists} "$oldDesktopLink"
      CreateShortCut "$newDesktopLink" "$appExe" "" "$appExe" 0 "" "" "${APP_DESCRIPTION}"
      ClearErrors
      WinShell::SetLnkAUMI "$newDesktopLink" "${APP_ID}"
    ${EndIf}
  !endif

  !ifndef DO_NOT_CREATE_START_MENU_SHORTCUT
    ${If} ${FileExists} "$newStartMenuLink"
      CreateShortCut "$newStartMenuLink" "$appExe" "" "$appExe" 0 "" "" "${APP_DESCRIPTION}"
      ClearErrors
      WinShell::SetLnkAUMI "$newStartMenuLink" "${APP_ID}"
    ${EndIf}
    ${If} $oldStartMenuLink != $newStartMenuLink
    ${AndIf} ${FileExists} "$oldStartMenuLink"
      CreateShortCut "$oldStartMenuLink" "$appExe" "" "$appExe" 0 "" "" "${APP_DESCRIPTION}"
      ClearErrors
      WinShell::SetLnkAUMI "$oldStartMenuLink" "${APP_ID}"
    ${EndIf}
    ${IfNot} ${FileExists} "$newStartMenuLink"
    ${AndIfNot} ${FileExists} "$oldStartMenuLink"
      CreateShortCut "$newStartMenuLink" "$appExe" "" "$appExe" 0 "" "" "${APP_DESCRIPTION}"
      ClearErrors
      WinShell::SetLnkAUMI "$newStartMenuLink" "${APP_ID}"
    ${EndIf}
  !endif

  # installSection.nsh points $launchLink at the Start Menu shortcut when one
  # exists, so the post-update relaunch goes through a .lnk: the very file an
  # earlier update may have left pointing at a path that no longer exists, in
  # which case the app silently never comes back up and the user is left poking
  # at broken icons. The executable is always the more reliable target, and by
  # this point it is on disk.
  StrCpy $launchLink "$appExe"

  System::Call 'Shell32::SHChangeNotify(i 0x8000000, i 0, i 0, i 0)'
!macroend
