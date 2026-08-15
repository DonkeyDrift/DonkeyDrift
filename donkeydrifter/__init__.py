import importlib
import importlib.abc
import importlib.util
import sys

from donkeycar import *  # noqa: F401,F403
from donkeycar._version import __version__


def _warn_if_upstream_donkeycar_installed():
    """检测官方上游 donkeycar 包是否覆盖了本项目的 donkeycar 兼容包。

    本项目的发行名是 donkeydrifter，安装后同时提供 donkeycar 与
    donkeydrifter 两个 import 名。PyPI 上的 donkeycar 是官方上游包：
    一旦安装，其文件会覆盖本项目的 donkeycar 包并接管 `donkey`
    命令入口，导致 tui/web/drive/installweb 等 DonkeyDrifter 命令
    全部消失。此处通过发行元数据探测该冲突并在 stderr 给出修复指引。
    """
    try:
        from importlib.metadata import PackageNotFoundError, distribution
    except ImportError:  # pragma: no cover - Python >= 3.11 始终可用
        return

    try:
        dist = distribution('donkeycar')
    except PackageNotFoundError:
        return
    except Exception:  # pragma: no cover - 元数据损坏时不阻塞导入
        return

    version = getattr(dist, 'version', None) or 'unknown'
    print(
        '\n'
        '==================================================================\n'
        ' WARNING: upstream "donkeycar" package detected (v{})!\n'
        '==================================================================\n'
        'The PyPI package "donkeycar" is the upstream Donkeycar project,\n'
        'NOT DonkeyDrifter. Installing it overwrites the donkeycar\n'
        'compatibility package shipped by DonkeyDrifter and takes over\n'
        'the `donkey` command, so DonkeyDrifter commands such as\n'
        'tui / web / drive / installweb become unavailable.\n'
        '\n'
        'To restore DonkeyDrifter functionality:\n'
        '  pip uninstall -y donkeycar\n'
        '  pip install "donkeydrifter[macos]"     # macOS\n'
        '  pip install "donkeydrifter[pc]"        # other desktop platforms\n'
        '  # or from a source checkout:\n'
        '  pip install -e ".[pc]"\n'
        '==================================================================\n'.format(version),
        file=sys.stderr,
    )


_warn_if_upstream_donkeycar_installed()

_SUBMODULES = (
    "config",
    "contrib",
    "geom",
    "la",
    "memory",
    "vehicle",
    "management",
    "parts",
    "pipeline",
    "templates",
    "utils",
)


class _DonkeyDrifterAliasFinder(importlib.abc.MetaPathFinder,
                                importlib.abc.Loader):
    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith("donkeydrifter."):
            return None

        legacy_name = "donkeycar" + fullname[len("donkeydrifter"):]
        legacy_spec = importlib.util.find_spec(legacy_name)
        if legacy_spec is None:
            return None

        is_package = legacy_spec.submodule_search_locations is not None
        return importlib.util.spec_from_loader(
            fullname, self, is_package=is_package
        )

    def create_module(self, spec):
        legacy_name = "donkeycar" + spec.name[len("donkeydrifter"):]
        module = importlib.import_module(legacy_name)
        sys.modules[spec.name] = module
        return module

    def exec_module(self, module):
        return None


if not any(isinstance(finder, _DonkeyDrifterAliasFinder)
           for finder in sys.meta_path):
    sys.meta_path.insert(0, _DonkeyDrifterAliasFinder())

for module_name in _SUBMODULES:
    legacy_name = f"donkeycar.{module_name}"
    alias_name = f"{__name__}.{module_name}"
    sys.modules[alias_name] = importlib.import_module(legacy_name)
