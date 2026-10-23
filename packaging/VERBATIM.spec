# PyInstaller spec — builds VERBATIM.app (macOS) or VERBATIM\ (Windows, with VERBATIM.exe + verbatim-cli.exe).
# Run from the repository root:  pyinstaller --noconfirm packaging/VERBATIM.spec
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))
from verbatim import __version__  # noqa: E402

IS_MAC = sys.platform == "darwin"
datas = [(str(ROOT / "assets"), "assets")]
if (ROOT / "bundled_models").exists():  # e.g. bundled_models/sherpa/<parakeet folder> -> ships inside the app
    datas.append((str(ROOT / "bundled_models"), "models"))
if (ROOT / "engine_host").exists():     # PyTorch engines run from here inside their own runtime (3.5)
    datas.append((str(ROOT / "engine_host"), "engine_host"))
if (ROOT / "llama.cpp").exists():       # llama-server for offline translation (3.4: shipped inside the app)
    datas.append((str(ROOT / "llama.cpp"), "llama.cpp"))
for _doc in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
    if (ROOT / _doc).exists():
        datas.append((str(ROOT / _doc), "."))
binaries = []
if not IS_MAC:
    # Collect Qt plugins explicitly: PyInstaller's PySide6 hook can miss them when it cannot query Qt
    # at build time (e.g. cross-builds), and without platforms/qwindows.dll the window cannot open.
    import importlib.util

    _pyside = Path(importlib.util.find_spec("PySide6").origin).parent
    for _dll in list(_pyside.glob("av*.dll")) + list(_pyside.glob("sw*.dll")) + \
            [p for p in (_pyside / "Qt6Multimedia.dll", _pyside / "Qt6MultimediaWidgets.dll", _pyside / "Qt6Network.dll")
             if p.exists()]:
        binaries.append((str(_dll), "PySide6"))
    for _sub in ("platforms", "imageformats", "iconengines", "styles", "multimedia"):
        if (_pyside / "plugins" / _sub).is_dir():
            datas.append((str(_pyside / "plugins" / _sub), f"PySide6/plugins/{_sub}"))
hidden = ["keyring.backends.macOS", "keyring.backends.Windows", "winsound", "wave", "tiktoken_ext.openai_public", "tiktoken_ext",
          "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtNetwork", "cv2"]

for pkg in ["sherpa_onnx", "onnxruntime", "imageio_ffmpeg", "docx", "openpyxl", "cv2"]:
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hidden += h
for pkg in (["mlx", "mlx_whisper", "tiktoken"] if IS_MAC else ["faster_whisper", "ctranslate2", "tokenizers", "sentencepiece"]):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hidden += h
    except Exception as exc:  # optional engine not installed on this build machine
        print("skip", pkg, exc)

a = Analysis([str(ROOT / "run.py")], pathex=[str(ROOT)], binaries=binaries, datas=datas, hiddenimports=hidden,
             excludes=["tkinter", "matplotlib", "torch", "tensorflow", "IPython", "pytest"], noarchive=False)
pyz = PYZ(a.pure)

VERSION_INFO = None
if not IS_MAC:  # Windows file properties: Infinite Story LLP as the company, copyright, product version
    from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                     VarFileInfo, VarStruct, VSVersionInfo)

    _t = tuple(int(x) for x in __version__.split(".")[:3]) + (0,)
    VERSION_INFO = VSVersionInfo(ffi=FixedFileInfo(filevers=_t, prodvers=_t), kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", "Infinite Story LLP"), StringStruct("FileDescription", "VERBATIM"),
            StringStruct("FileVersion", __version__), StringStruct("InternalName", "VERBATIM"),
            StringStruct("LegalCopyright", "Copyright (c) 2026 Infinite Story LLP. All rights reserved."),
            StringStruct("OriginalFilename", "VERBATIM.exe"), StringStruct("ProductName", "VERBATIM"),
            StringStruct("ProductVersion", __version__)])]),
        VarFileInfo([VarStruct("Translation", [1033, 1200])])])

gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name="VERBATIM", console=False,
          icon=str(ROOT / "assets" / ("VERBATIM.icns" if IS_MAC else "VERBATIM.ico")),
          target_arch="arm64" if IS_MAC else None, upx=False, version=VERSION_INFO)
exes = [gui]
if not IS_MAC:  # console twin for scripts / scheduled updates on Windows
    exes.append(EXE(pyz, a.scripts, [], exclude_binaries=True, name="verbatim-cli", console=True,
                    icon=str(ROOT / "assets" / "VERBATIM.ico"), upx=False, version=VERSION_INFO))

coll = COLLECT(*exes, a.binaries, a.datas, strip=False, upx=False, name="VERBATIM")

if IS_MAC:
    app = BUNDLE(coll, name="VERBATIM.app", icon=str(ROOT / "assets" / "VERBATIM.icns"),
                 bundle_identifier="in.infinitestory.verbatim",
                 info_plist={
                     "CFBundleName": "VERBATIM", "CFBundleDisplayName": "VERBATIM",
                     "CFBundleShortVersionString": __version__, "CFBundleVersion": __version__,
                     "NSHumanReadableCopyright": "© 2026 Infinite Story LLP. All rights reserved.",
                     "LSMinimumSystemVersion": "13.3", "NSHighResolutionCapable": True,
                     "CFBundleDocumentTypes": [{"CFBundleTypeName": "Media", "CFBundleTypeRole": "Viewer",
                                                "LSItemContentTypes": ["public.movie", "public.audio"]}],
                 })
