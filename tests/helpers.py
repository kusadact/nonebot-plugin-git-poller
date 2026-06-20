from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types


PACKAGE_NAME = "nonebot_plugin_git_poller"
PACKAGE_DIR = Path(__file__).resolve().parents[1] / "src" / PACKAGE_NAME


def load_plugin_module(name: str):
    package = types.ModuleType(PACKAGE_NAME)
    package.__path__ = [str(PACKAGE_DIR)]
    package.__spec__ = importlib.util.spec_from_loader(
        PACKAGE_NAME,
        loader=None,
        is_package=True,
    )
    sys.modules[PACKAGE_NAME] = package

    module_name = f"{PACKAGE_NAME}.{name}"
    spec = importlib.util.spec_from_file_location(module_name, PACKAGE_DIR / f"{name}.py")
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module
