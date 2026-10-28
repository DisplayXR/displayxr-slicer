@echo off
rem Copyright 2026, The DisplayXR Project
rem SPDX-License-Identifier: Apache-2.0
rem
rem   build.bat        host core + GL presenter -> DisplayXR\bin (the module loads them)
rem   build.bat test   also runs the rig unit tests
rem
rem The host core (core\) is the app-neutral core shared with the MotionBuilder,
rem Nuke and Houdini adapters (seed of the shared host library), built here
rem with 3D Slicer's identity. Needs VS 2022 (x64 C++).
setlocal
set ROOT=%~dp0
set VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat
if not exist "%VCVARS%" set VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat
call "%VCVARS%" >nul || exit /b 1

set OUT=%ROOT%..\DisplayXR\bin
set OBJ=%ROOT%build
if not exist "%OUT%" mkdir "%OUT%"
if not exist "%OBJ%" mkdir "%OBJ%"
set CL_COMMON=/nologo /std:c++17 /O2 /MD /EHsc /W3 /D_CRT_SECURE_NO_WARNINGS /D_USE_MATH_DEFINES
set APP_DEFS=/DDXRH_APP_NAME="\"3D Slicer\"" /DDXRH_ENGINE_NAME="\"displayxr-slicer\"" ^
  /DDXRH_WINDOW_CLASS=L"\"DisplayXR_Slicer_3D\"" /DDXRH_WINDOW_TITLE=L"\"3D Slicer 3D - DisplayXR\"" ^
  /DDXRH_LOG_NAME="\"displayxr-slicer.log\""

cl %CL_COMMON% /LD /DDXRH_BUILD %APP_DEFS% /I"%ROOT%third_party\openxr" ^
  "%ROOT%core\core.cpp" "%ROOT%core\xr_session.cpp" "%ROOT%core\rig.cpp" "%ROOT%core\log.cpp" ^
  /Fo"%OBJ%\\" /Fe"%OUT%\displayxr_host.dll" ^
  /link d3d11.lib dxgi.lib user32.lib ole32.lib windowscodecs.lib || exit /b 1
copy /y "%ROOT%third_party\openxr_loader.dll" "%OUT%\" >nul

cl %CL_COMMON% /LD /I"%ROOT%." "%ROOT%gl_present.cpp" /Fo"%OBJ%\\" /Fe"%OUT%\displayxr_slicer_gl.dll" ^
  /link "%OUT%\displayxr_host.lib" opengl32.lib d3d11.lib || exit /b 1

if /i "%1"=="test" (
  cl %CL_COMMON% "%ROOT%tests\test_rig.cpp" "%ROOT%core\rig.cpp" /Fo"%OBJ%\\" /Fe"%OBJ%\test_rig.exe" || exit /b 1
  "%OBJ%\test_rig.exe" || exit /b 1
)
echo Built %OUT%
