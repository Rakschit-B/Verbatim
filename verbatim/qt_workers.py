# Copyright © 2026 Infinite Story LLP. All rights reserved.
# VERBATIM is proprietary software of Infinite Story LLP. Unauthorised copying, modification or
# distribution of this file, via any medium, is strictly prohibited.
"""Safe background threads for the Qt UI.

3.5 crash fix: a QThread that is garbage-collected while still running aborts the whole app
("QThread: Destroyed while thread is still running"). That happened when a second update check or model
download replaced the attribute holding a running thread. Every worker now goes through `start()`, which
keeps the thread and worker alive in a registry until the thread has really finished, and `shutdown()`
waits for them when the app quits.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QThread

_LIVE: set = set()


def start(worker: QObject, run_slot, finished_signals=(), parent=None) -> QThread:
    """Move `worker` to a new thread, start `run_slot`, quit the thread when any of `finished_signals` fires."""
    th = QThread(parent)
    worker.moveToThread(th)
    th.started.connect(run_slot)
    for sig in finished_signals:
        sig.connect(th.quit)
    pair = (th, worker)
    _LIVE.add(pair)
    th.finished.connect(lambda: _LIVE.discard(pair))
    th.start()
    return th


def running() -> int:
    return sum(1 for th, _ in _LIVE if th.isRunning())


def shutdown(timeout_ms: int = 3000):
    """Ask every thread to finish (used on quit). Threads stuck in network I/O are left to the OS."""
    for th, _ in list(_LIVE):
        th.quit()
    for th, _ in list(_LIVE):
        th.wait(timeout_ms)
