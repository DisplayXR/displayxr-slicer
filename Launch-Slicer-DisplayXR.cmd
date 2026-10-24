@echo off
rem 3D Slicer with glasses-free 3D on DisplayXR (Leia SR).
rem The 3D shows inside Slicer's 3D view and weaves next to other 3D apps;
rem F11 (or "Full screen") puts it on the whole panel.
setlocal
set "HERE=%~dp0"
set "SLICER=%LOCALAPPDATA%\slicer.org\3D Slicer 5.12.4\Slicer.exe"
if not exist "%SLICER%" (
  echo 3D Slicer 5.12.4 not found. Install it: winget install Kitware.Slicer
  exit /b 1
)
rem Windowed 3D needs the hosted-window embed (DisplayXR PR #2332). Use the dev
rem runtime build while that is unreleased; released v2.53 shows the 3D full panel.
set "DEVRT=%USERPROFILE%\dev\displayxr-runtime\_package\bin\DisplayXR_win64.json"
if exist "%DEVRT%" (set "XR_RUNTIME_JSON=%DEVRT%") else (set "XR_RUNTIME_JSON=C:\Program Files\DisplayXR\Runtime\DisplayXR_win64.json")
set "DXR_HOSTED_WINDOW=auto"
rem Mouse over the 3D goes to Slicer (runtime hosted/input-passthrough; ignored by older runtimes)
set "DXR_HOSTED_INPUT=app"
start "" "%SLICER%" --additional-module-paths "%HERE%DisplayXR" --python-code "slicer.util.selectModule('DisplayXR'); slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalWidescreenView)" %*
