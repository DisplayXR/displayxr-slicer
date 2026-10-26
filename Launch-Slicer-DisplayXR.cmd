@echo off
rem 3D Slicer with glasses-free 3D on DisplayXR (Leia SR).
rem The 3D shows inside Slicer's 3D view and weaves next to other 3D apps;
rem F11 (or "Full screen") puts it on the whole panel.
rem
rem Usage: Launch-Slicer-DisplayXR.cmd [-dev] [--which] [Slicer arguments...]
rem   -dev     use a local runtime build (also: set DXR_RUNTIME=dev); see below
rem   --which  print the Slicer and runtime that would be used, then exit
rem Slicer:  the newest installed 3D Slicer; set SLICER_EXE to pick another one.
rem Runtime: the installed DisplayXR runtime by default (else the system's
rem          active OpenXR runtime); XR_RUNTIME_JSON, if already set, wins.
setlocal EnableDelayedExpansion
set "HERE=%~dp0"
set "WHICH="
:args
if /i "%~1"=="-dev" (set "DXR_RUNTIME=dev" & shift & goto args)
if /i "%~1"=="--which" (set "WHICH=1" & shift & goto args)

rem --- find Slicer: SLICER_EXE, else the highest "3D Slicer <version>" install
if defined SLICER_EXE (
  set "SLICER=%SLICER_EXE%"
) else (
  set "SLICER="
  for /f "delims=" %%P in ('powershell -NoProfile -Command "$d = @($env:LOCALAPPDATA, $env:ProgramFiles) | ForEach-Object { Join-Path $_ 'slicer.org' } | Where-Object { Test-Path $_ }; Get-ChildItem -Path $d -Directory -Filter '3D Slicer *' -ErrorAction SilentlyContinue | Where-Object { Test-Path (Join-Path $_.FullName 'Slicer.exe') } | ForEach-Object { $v = $null; if ([version]::TryParse(($_.Name -replace '^3D Slicer ', ''), [ref]$v)) { [pscustomobject]@{ V = $v; P = Join-Path $_.FullName 'Slicer.exe' } } } | Sort-Object V -Descending | Select-Object -First 1 -ExpandProperty P"') do set "SLICER=%%P"
)
if not defined SLICER goto noslicer
if not exist "!SLICER!" goto noslicer

rem --- runtime: installed by default; a local build only on request.
rem Windowed 3D needs the hosted-window embed (DisplayXR PR #2332); runtimes
rem without it show the 3D on the whole panel instead.
if /i "%DXR_RUNTIME%"=="dev" (
  if not defined DXR_DEV_RUNTIME_JSON set "DXR_DEV_RUNTIME_JSON=%USERPROFILE%\dev\displayxr-runtime\_package\bin\DisplayXR_win64.json"
  if not exist "!DXR_DEV_RUNTIME_JSON!" (
    echo Dev runtime requested but not found: !DXR_DEV_RUNTIME_JSON!
    echo Build it, or set DXR_DEV_RUNTIME_JSON to its DisplayXR_win64.json.
    exit /b 1
  )
  set "XR_RUNTIME_JSON=!DXR_DEV_RUNTIME_JSON!"
) else if not defined XR_RUNTIME_JSON (
  if exist "%ProgramFiles%\DisplayXR\Runtime\DisplayXR_win64.json" set "XR_RUNTIME_JSON=%ProgramFiles%\DisplayXR\Runtime\DisplayXR_win64.json"
)
if defined WHICH (
  echo Slicer:  !SLICER!
  if defined XR_RUNTIME_JSON (echo Runtime: !XR_RUNTIME_JSON!) else (echo Runtime: system active OpenXR runtime)
  exit /b 0
)

set "DXR_HOSTED_WINDOW=auto"
rem Mouse over the 3D goes to Slicer (runtime hosted/input-passthrough; ignored by older runtimes)
set "DXR_HOSTED_INPUT=app"
rem A gamepad drives Slicer's own 3D camera (the module); keep the runtime's pad
rem fly camera and emulated VR controllers off, they would move the 3D off it.
set "DXR_INPUT_GAMEPAD_NAV=0"
set "DXR_INPUT_GAMEPAD_EMULATE_CONTROLLERS=0"
rem The DisplayXR 3D module starts the depth slider (tools\) with the 3D session.
start "" "!SLICER!" --additional-module-paths "%HERE%DisplayXR" --python-code "slicer.util.selectModule('DisplayXR'); slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalWidescreenView)" %1 %2 %3 %4 %5 %6 %7 %8 %9
exit /b 0

:noslicer
if defined SLICER_EXE (
  echo SLICER_EXE is set but does not exist: %SLICER_EXE%
) else (
  echo 3D Slicer not found under %LOCALAPPDATA%\slicer.org or %ProgramFiles%\slicer.org.
  echo Install it: winget install Kitware.Slicer   ^(or set SLICER_EXE to Slicer.exe^)
)
exit /b 1
