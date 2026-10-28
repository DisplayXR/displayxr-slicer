# Install a Slicer extension headlessly (default: SlicerVirtualReality):
#   Slicer.exe --no-splash --no-main-window --python-script tools/install_extension.py [ExtensionName]
import slicer, sys
em = slicer.app.extensionsManagerModel()
em.interactive = False
name = sys.argv[1] if len(sys.argv) > 1 else "SlicerVirtualReality"
ok = em.installExtensionFromServer(name) if hasattr(em, "installExtensionFromServer") else em.downloadAndInstallExtensionByName(name)
print("INSTALL", name, ok, flush=True)
print("INSTALLED", em.installedExtensions, flush=True)
slicer.app.exit(0 if ok else 1)
