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
binaries = []
if not IS_MAC:
    # Collect Qt plugins explicitly: PyInstaller's PySide6 hook can miss them when it cannot query Qt
    # at build time (e.g. cross-builds), and without platforms/qwindows.dll the window cannot open.
    import importlib.util

    _pyside = Path(importlib.util.find_spec("PySide6").origin).parent
    for _sub in ("platforms", "imageformats", "iconengines", "styles"):
        if (_pyside / "plugins" / _sub).is_dir():
            datas.append((str(_pyside / "plugins" / _sub), f"PySide6/plugins/{_sub}"))
hidden = ["keyring.backends.macOS", "keyring.backends.Windows", "winsound", "wave", "tiktoken_ext.openai_public", "tiktoken_ext"]

for pkg in ["sherpa_onnx", "onnxruntime", "imageio_ffmpeg", "docx", "openpyxl"]:
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

gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name="VERBATIM", console=False,
          icon=str(ROOT / "assets" / ("VERBATIM.icns" if IS_MAC else "VERBATIM.ico")),
          target_arch="arm64" if IS_MAC else None, upx=False)
exes = [gui]
if not IS_MAC:  # console twin for scripts / scheduled updates on Windows
    exes.append(EXE(pyz, a.scripts, [], exclude_binaries=True, name="verbatim-cli", console=True,
                    icon=str(ROOT / "assets" / "VERBATIM.ico"), upx=False))

coll = COLLECT(*exes, a.binaries, a.datas, strip=False, upx=False, name="VERBATIM")

if IS_MAC:
    app = BUNDLE(coll, name="VERBATIM.app", icon=str(ROOT / "assets" / "VERBATIM.icns"),
                 bundle_identifier="in.infinitestory.verbatim",
                 info_plist={
                     "CFBundleName": "VERBATIM", "CFBundleDisplayName": "VERBATIM",
                     "CFBundleShortVersionString": __version__, "CFBundleVersion": __version__,
                     "LSMinimumSystemVersion": "13.3", "NSHighResolutionCapable": True,
                     "NSHumanReadableCopyright": "© Infinite Story",
                     "CFBundleDocumentTypes": [{"CFBundleTypeName": "Media", "CFBundleTypeRole": "Viewer",
                                                "LSItemContentTypes": ["public.movie", "public.audio"]}],
                 })
