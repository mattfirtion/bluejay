import logging
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src" / "http_checks" / "python"))

# The Synthetics runtime provides aws_synthetics; stub it for local tests.
_common = types.ModuleType("aws_synthetics.common")
_common.synthetics_logger = logging.getLogger("test")
_pkg = types.ModuleType("aws_synthetics")
_pkg.common = _common
sys.modules.setdefault("aws_synthetics", _pkg)
sys.modules.setdefault("aws_synthetics.common", _common)
