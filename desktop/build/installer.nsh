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
# from $appExe, which is what actually repairs it. Shortcuts that aren't there
# are left alone so one the user deleted isn't resurrected, except when updating
# and NOTHING is left to click: a stray extra icon is a far smaller problem than
# no way into the app.
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
    # Neither recorded name is present. On an update that means the shortcut was
    # renamed by a build that never told the installer (so it is invisible here
    # and possibly broken), or it is simply gone. Leave a working one behind.
    ${If} ${isUpdated}
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
    ${If} ${isUpdated}
    ${AndIfNot} ${FileExists} "$newStartMenuLink"
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
