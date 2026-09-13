"""The client VFS manifest must mirror the framework packages it serves.

``VFSRegistry.add_framework_files`` builds ``/pyscript.json`` from explicit file lists,
and Pyodide can only import what that manifest ships. A module missing from the list is
still served over HTTP, so nothing fails server-side — the client fails inside a guarded
boot step ("No module named 'basis.shared.x'") and degrades silently instead.

Asserting the list against the directory it mirrors keeps that silent failure from
recurring whenever a framework module is added or removed.
"""

from pathlib import Path

import pytest

from basis.server.vfs import VFSRegistry

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1] / "src" / "basis"


def _served_stems(package: str) -> set[str]:
    registry = VFSRegistry()
    registry.add_framework_files()
    marker = f"/basis/{package}/"
    return {Path(name).stem for name in registry.files if marker in name}


def _module_stems(package: str) -> set[str]:
    return {path.stem for path in (FRAMEWORK_ROOT / package).glob("*.py")}


@pytest.mark.parametrize("package", ["shared", "client"])
def test_manifest_matches_the_package(package):
    """Served files and on-disk modules are the same set, in both directions.

    A module missing from the manifest cannot be imported on the client; an entry
    without a file is a 404 during boot.
    """
    on_disk = _module_stems(package)
    served = _served_stems(package)
    assert on_disk - served == set(), (
        f"{package} modules are not served to the client — add them to "
        f"VFSRegistry.add_framework_files"
    )
    assert served - on_disk == set(), (
        f"the manifest advertises {package} modules that do not exist on disk"
    )
