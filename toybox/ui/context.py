"""
context.py - Shared application state handed to every panel.
"""

from typing import TYPE_CHECKING, Dict, Optional

from ..core.executor import NamedDict
from ..core.lenses import LensManager
from ..panels.base import REGISTRY

if TYPE_CHECKING:
    from .workspace import Workspace

DEFAULT_PREFS = {
    "hide_while_measuring": True,   # make lenses invisible while a script captures
    "settle_ms": 50,                # wait after hiding, so the compositor repaints
    "interval_ms": 500,             # default Run Continuous interval for new scripts
}


class AppContext:
    def __init__(self):
        self.lenses = LensManager()
        self.prefs: Dict[str, object] = dict(DEFAULT_PREFS)
        self.workspace: Optional["Workspace"] = None
        self.apply_prefs()

    def apply_prefs(self) -> None:
        self.lenses.hide_while_measuring = bool(self.prefs["hide_while_measuring"])
        self.lenses.settle_ms = max(0, int(self.prefs["settle_ms"]))

    def script_namespace(self) -> Dict[str, object]:
        """Names injected into every script run (GUI thread): Lenses plus one
        collection per panel kind that exposes itself to scripts."""
        ns: Dict[str, object] = {"Lenses": NamedDict("lens", self.lenses.snapshot())}
        if self.workspace is None:
            return ns
        for kind, cls in REGISTRY.items():
            collection = cls.script_collection()
            if collection:
                handles = {p.name: p.script_handle() for p in self.workspace.panels()
                           if p.kind == kind}
                ns[collection] = NamedDict(cls.title.lower(), handles)
        return ns
