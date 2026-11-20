"""
executor.py - Script execution engine.

* Runs the user's code with exec() on a worker thread so Tk never blocks.
* Injects a `Lenses` dict into the script's globals.
* Redirects sys.stdout / sys.stderr into a thread-safe queue that the GUI
  drains on the main thread (Tk widgets must only be touched there).
* Catches every exception and writes a trimmed traceback to the console stream.

Variables persist between runs until `reset_namespace()` is called, which lets
a continuous script keep state (counters, previous values, ...).
"""

import ctypes
import io
import queue
import sys
import threading
import traceback
from typing import Dict, List, Tuple

from vision import WHITELIST_PRESETS

SCRIPT_NAME = "<script>"


class ScriptStopped(BaseException):
    """Raised inside the worker thread to abort a running script."""


class LensDict(dict):
    """dict with a friendlier error for unknown lens names."""

    def __missing__(self, key):
        available = ", ".join(repr(k) for k in self) or "none - add one in the sidebar"
        raise KeyError(f"No lens named {key!r}. Available lenses: {available}")


class QueueStream(io.TextIOBase):
    """File-like object whose write() is safe to call from any thread."""

    def __init__(self, out_queue: "queue.Queue", tag: str):
        super().__init__()
        self._queue = out_queue
        self._tag = tag

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        if text:
            self._queue.put((self._tag, text))
        return len(text)

    def flush(self) -> None:
        pass


class ScriptExecutor:
    def __init__(self):
        self._queue: "queue.Queue[Tuple[str, str]]" = queue.Queue()
        self._stdout = QueueStream(self._queue, "stdout")
        self._stderr = QueueStream(self._queue, "stderr")
        self._orig_streams = (None, None)
        self._thread = None
        self._lock = threading.Lock()
        self.namespace: dict = {}
        self.reset_namespace()

    # ---------------------------------------------------- stream redirection
    def install_redirect(self) -> None:
        """Route print() and tracebacks to the console queue."""
        self._orig_streams = (sys.stdout, sys.stderr)
        sys.stdout, sys.stderr = self._stdout, self._stderr

    def restore_redirect(self) -> None:
        if self._orig_streams[0] is not None:
            sys.stdout, sys.stderr = self._orig_streams

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

    # ------------------------------------------------------------ execution
    def reset_namespace(self) -> None:
        # Whitelist presets (NUMERIC, ALPHANUM, ...) are available to scripts by name.
        self.namespace = {"__name__": "__main__", **WHITELIST_PRESETS}

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def run(self, source: str, lenses: Dict[str, object]) -> bool:
        """Start the script on a worker thread. Returns False if one is already running."""
        with self._lock:
            if self.is_running:
                return False
            self.namespace["Lenses"] = LensDict(lenses)
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
        try:
            code = compile(source, SCRIPT_NAME, "exec")
            exec(code, self.namespace)
        except ScriptStopped:
            self.log("[script stopped]\n", "info")
        except SystemExit:
            pass
        except BaseException as exc:  # noqa: BLE001 - everything must reach the console
            self._queue.put(("stderr", self._format_error(exc)))

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