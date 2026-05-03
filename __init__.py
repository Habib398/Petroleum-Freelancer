"""backend package bootstrap.

Keeps backward compatibility for modules that use absolute imports like
`import routes...` or `from db import ...` while also allowing
`import backend.app` during tests.
"""
from pathlib import Path
import sys

_pkg_dir = str(Path(__file__).resolve().parent)
if _pkg_dir not in sys.path:
    sys.path.insert(0, _pkg_dir)
