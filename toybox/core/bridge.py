"""
bridge.py - Run a callable on the Qt GUI thread from any thread.

Scripts run on worker threads, but Qt widgets may only be touched from the GUI
thread. Anything a script-facing API needs from the GUI goes through
`gui_call(fn, ...)`:

    gui_call(window.setWindowOpacity, 0.0)            # waits for the result
    gui_call(timer.start, wait=False)                 # fire and forget

Called on the GUI thread itself, the function simply runs directly (waiting on
ourselves would deadlock).
"""

import threading
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, QThread, Qt, Signal


class _Invoker(QObject):
    request = Signal(object)

    def __init__(self):
        super().__init__()
        # Queued: the slot always runs in the thread this object lives in (GUI).
        self.request.connect(self._run, Qt.QueuedConnection)

    @staticmethod
    def _run(task: Callable[[], None]) -> None:
        task()


_invoker: Optional[_Invoker] = None


def init_bridge() -> None:
    """Create the invoker. Must be called once on the GUI thread at start-up."""
    global _invoker
    if _invoker is None:
        _invoker = _Invoker()


def on_gui_thread() -> bool:
    return _invoker is None or QThread.currentThread() is _invoker.thread()


def gui_call(fn: Callable[..., Any], *args, wait: bool = True,
             timeout: Optional[float] = 5.0, **kwargs) -> Any:
    """Run fn(*args, **kwargs) on the GUI thread; return its result if `wait`."""
    if on_gui_thread():
        return fn(*args, **kwargs)
    if not wait:
        _invoker.request.emit(lambda: fn(*args, **kwargs))
        return None

    done = threading.Event()
    box = {}

    def task():
        try:
            box["result"] = fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 - re-raised in the caller's thread
            box["error"] = exc
        finally:
            done.set()

    _invoker.request.emit(task)
    if not done.wait(timeout):
        raise TimeoutError(f"GUI did not respond within {timeout} s")
    if "error" in box:
        raise box["error"]
    return box.get("result")
