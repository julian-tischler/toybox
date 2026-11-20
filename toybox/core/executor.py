"""
executor.py - Script execution engine (no GUI code).

* Each Script panel owns one ScriptExecutor; several can run at the same time.
* A script runs with exec() on its own worker thread, so the GUI never blocks.
* print() / tracebacks are routed per thread: `install_output_router()` replaces
  sys.stdout/sys.stderr once with streams that look up which executor owns the
  current thread and put the text into that executor's queue. The owning panel
  drains the queue on the GUI thread into its own console.
* Variables persist between runs until `reset_namespace()` is called, which lets
  a continuous script keep state (counters, previous values, ...).
* Scripts drive the workspace one-way: they run predictably, when Run is
  pressed, and nothing in the GUI triggers them.
* Before compiling, Toybox shorthands are expanded (see script_syntax.py),
  e.g. a line "! expr" becomes print(expr).
"""

import ctypes
import io
import queue
import sys
import threading
import traceback
from typing import Dict, List, Mapping, Optional, Tuple

from . import script_syntax
from .vision import WHITELIST_PRESETS

SCRIPT_NAME = "<script>"


class ScriptStopped(BaseException):
    """Raised inside the worker thread to abort a running script."""


class NamedDict(dict):
    """dict with a friendlier error for unknown names (e.g. Lenses["typo"])."""

    def __init__(self, kind: str, items: Mapping):
        super().__init__(items)
        self._kind = kind

    def __missing__(self, key):
        available = ", ".join(repr(k) for k in self) or "none"
        raise KeyError(f"No {self._kind} named {key!r}. Available: {available}")


# --------------------------------------------------------------------------
# Per-thread output routing
# --------------------------------------------------------------------------
_routes: Dict[int, "queue.Queue[Tuple[str, str]]"] = {}
_routes_lock = threading.Lock()


class _RoutedStream(io.TextIOBase):
    """sys.stdout/sys.stderr replacement that sends text to the current thread's
    executor queue, or to the original stream for any other thread."""

    def __init__(self, tag: str, fallback):
        super().__init__()
        self._tag = tag
        self._fallback = fallback

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        if not text:
            return 0
        target = _routes.get(threading.get_ident())
        if target is not None:
            target.put((self._tag, text))
        elif self._fallback is not None:
            try:
                self._fallback.write(text)
            except (OSError, ValueError):
                pass                       # pythonw.exe has no console
        return len(text)

    def flush(self) -> None:
        if self._fallback is not None:
            try:
                self._fallback.flush()
            except (OSError, ValueError, AttributeError):
                pass


_installed: Optional[Tuple[object, object]] = None


def install_output_router() -> None:
    """Replace sys.stdout/sys.stderr with the routing streams (idempotent)."""
    global _installed
    if _installed is None:
        _installed = (sys.stdout, sys.stderr)
        sys.stdout = _RoutedStream("stdout", sys.stdout)
        sys.stderr = _RoutedStream("stderr", sys.stderr)


def uninstall_output_router() -> None:
    global _installed
    if _installed is not None:
        sys.stdout, sys.stderr = _installed
        _installed = None


# --------------------------------------------------------------------------
# Executor
# --------------------------------------------------------------------------
class ScriptExecutor:
    def __init__(self):
        self._queue: "queue.Queue[Tuple[str, str]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.namespace: dict = {}
        self.reset_namespace()

    def drain(self, max_items: int = 1000) -> List[Tuple[str, str]]:
        """Pop pending (tag, text) chunks. Call from the GUI thread."""
        items = []
        while len(items) < max_items:
            try:
                items.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return items

    def log(self, text: str, tag: str = "info") -> None:
        self._queue.put((tag, text))

    def reset_namespace(self) -> None:
        # Whitelist presets (NUMERIC, ALPHANUM, ...) are available to scripts by name.
        self.namespace = {"__name__": "__main__", **WHITELIST_PRESETS}

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def run(self, source: str, injected: Mapping[str, object]) -> bool:
        """Start the script on a worker thread with `injected` names (Lenses, ...)
        added to its globals. Returns False if one is already running."""
        with self._lock:
            if self.is_running:
                return False
            self.namespace.update(injected)
            self._thread = threading.Thread(target=self._worker, args=(source,),
                                            name="ScriptWorker", daemon=True)
            self._thread.start()
            return True

    def stop(self) -> None:
        """Ask a running script to abort (takes effect at the next Python bytecode)."""
        thread = self._thread
        if thread is not None and thread.is_alive():
            ctypes.pythonapi.PyThreadState_SetAsyncExc(
                ctypes.c_ulong(thread.ident), ctypes.py_object(ScriptStopped))

    def _worker(self, source: str) -> None:
        ident = threading.get_ident()
        with _routes_lock:
            _routes[ident] = self._queue
        try:
            code = compile(script_syntax.expand(source), SCRIPT_NAME, "exec")
            exec(code, self.namespace)
        except ScriptStopped:
            self.log("[script stopped]\n", "info")
        except SystemExit:
            pass
        except BaseException as exc:  # noqa: BLE001 - everything must reach the console
            self._queue.put(("stderr", self._format_error(exc)))
        finally:
            with _routes_lock:
                _routes.pop(ident, None)

    @staticmethod
    def _format_error(exc: BaseException) -> str:
        """Traceback starting at the user's script (hides executor internals)."""
        tb = exc.__traceback__
        while tb is not None and tb.tb_frame.f_code.co_filename != SCRIPT_NAME:
            tb = tb.tb_next
        tail = "".join(traceback.format_exception_only(type(exc), exc))
        if tb is None:  # e.g. SyntaxError raised by compile()
            return tail
        return "Traceback (most recent call last):\n" + "".join(traceback.format_tb(tb)) + tail
