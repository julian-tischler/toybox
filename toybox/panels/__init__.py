"""Workspace tools. Importing this package registers every built-in panel."""

# Import order = order in the tool picker.
from . import script_panel  # noqa: F401,I001  (registration side effect)
from . import lenses_panel  # noqa: F401
from . import note_panel  # noqa: F401
from . import plot_panel  # noqa: F401
from . import definition_panel  # noqa: F401
