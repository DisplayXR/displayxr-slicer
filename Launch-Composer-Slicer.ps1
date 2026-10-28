# The Slicer (MONAI) organs in USD Composer, RTX, in 3D (displayxr.omniverse).
# Export first: in Slicer, "Send to Omniverse (USD)" (or Launch-Slicer-MONAI-3D.cmd),
# which writes Documents\DisplayXR\Slicer\SlicerScene.usda.
#   -Pitch: camera degrees down at the body (35 default; >= 50 overshoots the framing).
#   -Usd:   another exported .usda.
# Needs the DisplayXR Composer build (kit-app-template, displayxr.usd_composer.kit)
# and the installed DisplayXR runtime. Run non-elevated; close Slicer first (one heavy
# GPU app at a time).
param(
    [double]$Pitch = 35,
    [string]$Usd = ""
)
$kitRoot = $env:DXR_KIT_APP_TEMPLATE
if (-not $kitRoot) { $kitRoot = "$env:USERPROFILE\dev\kit-app-template" }
$rel = "$kitRoot\_build\windows-x86_64\release"
if (-not (Test-Path "$rel\displayxr.usd_composer.kit.bat")) { throw "Composer build not found under $rel (set DXR_KIT_APP_TEMPLATE)" }
$env:DXR_SLICER_PITCH = "$Pitch"
if ($Usd) { $env:DXR_SLICER_USD = (Resolve-Path $Usd).Path }
Start-Process -FilePath "$rel\displayxr.usd_composer.kit.bat" -WorkingDirectory $rel -ArgumentList @(
    "--/app/file/ignoreUnsavedOnExit=true",
    "--exec", "`"$PSScriptRoot\tools\composer_show_slicer.py`"")
