# Custom NSIS hooks, picked up automatically by electron-builder as
# <buildResources>/installer.nsh. Included in both the installer and the
# uninstaller script, so a macro only takes effect where it is inserted.

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
# Data root picker (issue #3136). The install directory is already choosable;
# app data was always written to %USERPROFILE%\.cow and the agent workspace to
# %USERPROFILE%\cow. This page lets the user put both under another root:
#
#   <root>\.cow   app data and credentials (COW_DATA_DIR)
#   <root>\cow    agent workspace (agent_workspace)
#
# The choice is recorded in %APPDATA%\CowAgent\data-root, which
# desktop/src/main/data-dir.ts reads at startup. The page is only shown on a
# fresh install: updates and reinstalls over existing data keep it where it is,
# because moving data is not something an installer should do silently.
!macro customPageAfterChangeDir
  !define COW_DATA_ROOT_PAGE
  !include nsDialogs.nsh

  Var cowDataRoot
  Var cowDataRootInput

  Page custom cowDataRootPageCreate cowDataRootPageLeave

  Function cowDataRootPageCreate
    ${If} ${isUpdated}
      Abort
    ${EndIf}
    ReadEnvStr $0 APPDATA
    ${If} ${FileExists} "$0\CowAgent\data-root"
    ${OrIf} ${FileExists} "$PROFILE\.cow\*.*"
      Abort
    ${EndIf}
    ${If} $cowDataRoot == ""
      StrCpy $cowDataRoot "$PROFILE"
    ${EndIf}

    !insertmacro MUI_HEADER_TEXT "Data Location" "Choose where ${PRODUCT_NAME} keeps its data."
    nsDialogs::Create 1018
    Pop $0
    ${If} $0 == error
      Abort
    ${EndIf}

    ${NSD_CreateLabel} 0 0 100% 36u "Settings, logs and the agent workspace are stored under this folder, in a .cow and a cow subfolder. The default is your user folder."
    Pop $0
    ${NSD_CreateDirRequest} 0 44u 78% 12u "$cowDataRoot"
    Pop $cowDataRootInput
    ${NSD_CreateBrowseButton} 80% 43u 20% 14u "Browse..."
    Pop $0
    ${NSD_OnClick} $0 cowDataRootBrowse

    nsDialogs::Show
  FunctionEnd

  Function cowDataRootBrowse
    ${NSD_GetText} $cowDataRootInput $0
    nsDialogs::SelectFolderDialog "Choose the data folder" "$0"
    Pop $0
    ${If} $0 != error
      ${NSD_SetText} $cowDataRootInput "$0"
    ${EndIf}
  FunctionEnd

  Function cowDataRootPageLeave
    ${NSD_GetText} $cowDataRootInput $0
    # Drop a trailing backslash, but keep a drive root like D:\ intact.
    StrCpy $1 $0 "" -1
    StrLen $2 $0
    ${If} $1 == "\"
    ${AndIf} $2 > 3
      StrCpy $0 $0 -1
    ${EndIf}
    StrCpy $1 $0 2 1
    StrCpy $2 $0 2
    ${If} $1 != ":\"
    ${AndIf} $2 != "\\"
      MessageBox MB_OK|MB_ICONEXCLAMATION "Please choose a full folder path, for example D:\CowAgentData."
      Abort
    ${EndIf}
    ClearErrors
    CreateDirectory "$0\.cow"
    ${If} ${Errors}
      MessageBox MB_OK|MB_ICONEXCLAMATION "Cannot create a folder in $0. Please choose another location."
      Abort
    ${EndIf}
    StrCpy $cowDataRoot $0
  FunctionEnd
!macroend

!macro customInstall
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

  # Record the data root chosen on the page above (only set on a fresh,
  # interactive install). UTF-16LE with a BOM so a non-ASCII user folder is
  # read back correctly by data-dir.ts.
  !ifdef COW_DATA_ROOT_PAGE
    ${If} $cowDataRoot != ""
      CreateDirectory "$cowDataRoot\.cow"
      CreateDirectory "$cowDataRoot\cow"
      ReadEnvStr $0 APPDATA
      CreateDirectory "$0\CowAgent"
      ClearErrors
      FileOpen $1 "$0\CowAgent\data-root" w
      ${IfNot} ${Errors}
        FileWriteUTF16LE /BOM $1 "$cowDataRoot"
        FileClose $1
      ${EndIf}
      ClearErrors
    ${EndIf}
  !endif

  System::Call 'Shell32::SHChangeNotify(i 0x8000000, i 0, i 0, i 0)'
!macroend
