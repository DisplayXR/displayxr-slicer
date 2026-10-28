@echo off
rem The MONAI demo in one command: CT (CTLiver sample) -> MONAI Auto3DSeg organs ->
rem 3D in Slicer's own 3D view -> Send to Omniverse (USD). One-time setup first:
rem   Slicer.exe --no-splash --no-main-window --python-script tools\install_extension.py MONAIAuto3DSeg
rem   Slicer.exe --no-splash --no-main-window --python-script tools\setup_monai.py
rem Research and demonstration software; not a medical device.
call "%~dp0Launch-Slicer-DisplayXR.cmd" --python-script "%~dp0tools\monai_demo.py" %*
