"""
base.py - The contract every workspace tool implements, plus the registry.

Adding a tool = subclass Panel, set `kind` / `title`, and decorate with
@register. The workspace then offers it in the "choose a tool" picker and
in every panel's "Change tool" menu, and saves/restores it in projects.

Script access (one-way: scripts use tools, tools never trigger scripts): a
panel class may return a global name from `script_collection()` (e.g. "Plots")
and a handle from `script_handle()`. Every script run then gets
Plots["panel name"] -> handle, the way Lenses["name"] works. Anything a handle
does with widgets must go through core.bridge.gui_call, because scripts run on
worker threads.
"""

from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Tuple, Type

from PySide6.QtWidgets import QWidget

if TYPE_CHECKING:
    from ..ui.main_window import AppContext

REGISTRY: Dict[str, Type["Panel"]] = {}


def register(cls: Type["Panel"]) -> Type["Panel"]:
    if not cls.kind:
        raise ValueError(f"{cls.__name__} needs a 'kind'")
    REGISTRY[cls.kind] = cls
    return cls


class Panel(QWidget):
    kind: str = ""              # stable id used in project files, e.g. "script"
    title: str = ""             # shown in the picker and panel header, e.g. "Script"
    description: str = ""       # one line for the picker

    def __init__(self, ctx: "AppContext", name: str):
        super().__init__()
        self.ctx = ctx
        self.name = name

    # -- persistence ---------------------------------------------------------
    def state(self) -> dict:
        """Contents to save in a project (layout files save no state)."""
        return {}

    def load_state(self, state: dict) -> None:
        pass

    def has_content(self) -> bool:
        """True if closing the panel would throw away user work (asks first)."""
        return False

    # -- header / menu -------------------------------------------------------
    def header_widgets(self) -> List[QWidget]:
        """Extra small widgets shown in the panel header (e.g. an eye toggle)."""
        return []

    def menu_actions(self) -> List[Tuple[str, Callable[[], None]]]:
        """Extra entries for the panel's ⋮ menu."""
        return []

    # -- scripts -------------------------------------------------------------
    @classmethod
    def script_collection(cls) -> Optional[str]:
        """Global name this kind is exposed under in scripts (None = not exposed)."""
        return None

    def script_handle(self) -> object:
        """Object a script receives as Collection[self.name]."""
        return None

    # -- lifecycle -----------------------------------------------------------
    def renamed(self, name: str) -> None:
        self.name = name

    def shutdown(self) -> None:
        """Called before the panel is destroyed (stop timers, threads, ...)."""
