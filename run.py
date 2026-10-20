"""VERBATIM entry point.

  VERBATIM                    -> desktop app
  VERBATIM --cli …            -> command line (see verbatim/cli.py)
  VERBATIM --update [opts]    -> check / install updates (used by the scheduled updater)
"""
import multiprocessing
import sys


def _console_utf8() -> None:
    # Windows consoles default to cp1252, which cannot print "→", "✓" or Hindi text.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _no_telemetry() -> None:
    # VERBATIM promises no telemetry: ONNX Runtime's Windows builds emit telemetry events by default.
    try:
        import onnxruntime

        onnxruntime.disable_telemetry_events()
    except Exception:
        pass


def _support_trace() -> None:
    # Support aid: VERBATIM_TRACE=<seconds> writes all thread stacks to verbatim_trace.txt periodically.
    import os

    secs = os.environ.get("VERBATIM_TRACE")
    if secs:
        import faulthandler

        fh = open(os.path.join(os.path.expanduser("~"), "verbatim_trace.txt"), "w")
        faulthandler.dump_traceback_later(int(secs), repeat=True, file=fh)


def _qt_plugins() -> None:
    # Packaged Windows app: point Qt at the bundled plugins (window system, SVG icons, image formats).
    import os

    base = getattr(sys, "_MEIPASS", None)
    if base:
        plug = os.path.join(base, "PySide6", "plugins")
        if os.path.isdir(plug):
            os.environ.setdefault("QT_PLUGIN_PATH", plug)


def main() -> int:
    multiprocessing.freeze_support()
    _qt_plugins()
    _support_trace()
    _console_utf8()
    _no_telemetry()
    args = sys.argv[1:]
    if args[:1] == ["--update"]:
        from verbatim.updater import main as upd

        return upd(args[1:])
    if args[:1] == ["--cli"]:
        from verbatim.cli import main as cli

        return cli(args[1:])
    if args[:1] == ["--selftest-ui"] and len(args) > 1:
        # Support/CI aid: open the window, save a screenshot to the given path and quit.
        from verbatim.gui import selftest

        return selftest(args[1])
    if args[:1] == ["--version"]:
        from verbatim import __version__

        print(__version__)
        return 0
    from verbatim.gui import main as gui

    return gui()


if __name__ == "__main__":
    sys.exit(main())
