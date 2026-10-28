# One-time setup for the MONAI demo, headless:
#   Slicer.exe --no-splash --no-main-window --python-script tools/setup_monai.py
# Needs the MONAIAuto3DSeg extension (tools/install_extension.py MONAIAuto3DSeg).
# Installs PyTorch (CUDA 12.8 build: RTX 50-series GPUs need it) and MONAI into
# Slicer's Python, downloads one model (Abdominal organs TS2, CC BY 4.0) and the
# CTLiver sample (Medical Decathlon, CC BY-SA 4.0). Log: tools/setup_monai.out.txt
import os, sys, time, traceback
import slicer

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "setup_monai.out.txt")
open(OUT, "w").close()
MODEL_TITLE = os.environ.get("DXR_MONAI_MODEL", "Abdominal organs TS2")


def log(*a):
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a) + "\n")


try:
    import PyTorchUtils
    tl = PyTorchUtils.PyTorchUtilsLogic()
    if not tl.torchInstalled():
        log("installing PyTorch (cu128)...")
        tl.installTorch(askConfirmation=False, forceComputationBackend="cu128", torchVersionRequirement=">=2.7")
    import torch
    log("torch", torch.__version__, "cuda", torch.cuda.is_available(),
        torch.cuda.get_device_name(0) if torch.cuda.is_available() else "-")

    import MONAIAuto3DSeg
    logic = MONAIAuto3DSeg.MONAIAuto3DSegLogic()
    log("installing MONAI...")
    logic.setupPythonRequirements()
    import monai
    log("monai", monai.__version__)

    model = next(m for m in logic.models if m.get("title") == MODEL_TITLE)
    log("model", model["id"], model.get("license"), "->", logic.modelPath(model["id"]))

    import SampleData
    vol = SampleData.downloadSample("CTLiver")
    log("sample CTLiver", vol.GetName(), vol.GetImageData().GetDimensions())
    log("SETUP OK")
    code = 0
except Exception:
    log("SETUP FAILED\n" + traceback.format_exc())
    code = 1
slicer.app.exit(code)
