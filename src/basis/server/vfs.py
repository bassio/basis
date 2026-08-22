"""Filesystem-mount → client VFS (PyScript import namespace) helpers.

Every place that serves a component directory and derives the client-side
import module name / VFS URL must use these helpers so the derivations can
never drift apart.

The isomorphism invariant (docs/04_components/importing-components.md): the
client VFS import name MUST equal the filesystem import name. These helpers
keep the mount path mirrored in the import namespace, which is what all three
environments (server imports, client VFS, IDEs) resolve against.
"""

from pathlib import Path


def normalize_mount(mount_path: str) -> str:
    """Normalize a mount path to a leading ``/`` and no trailing ``/`` (root → ``""``)."""
    clean = mount_path
    if not clean.startswith("/"):
        clean = "/" + clean
    return clean.rstrip("/")


def mount_to_module_name(mount_path: str, rel_path: Path) -> str | None:
    """Translate *rel_path* (relative to the mounted dir) into its dotted client
    import module name.

    The mount path becomes the import prefix (``/jotter/components`` →
    ``jotter.components``) and the file's stem the tail, with ``__init__``
    popping the package segment. Returns ``None`` when there is nothing to
    translate (e.g. a bare ``__init__.py`` at the mount root).
    """
    parts = [p for p in normalize_mount(mount_path).split("/") if p]
    parts += [p for p in rel_path.with_suffix("").parts if p]
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) if parts else None


def vfs_relative_url(mount_path: str, rel_path: Path) -> str:
    """Server-relative VFS URL for *rel_path* under *mount_path* (starts with ``./``)."""
    url = "." + normalize_mount(mount_path) + "/" + rel_path.as_posix()
    return url.replace("//", "/")


def companion_assets(module_file: Path) -> tuple[Path, Path]:
    """Return the (css, html) companion files owned by *module_file*.

    A package's ``__init__.py`` owns the package-named companions
    (``pkg/__init__.py`` → ``pkg.css`` / ``pkg.html``); a flat module owns its
    stem-named companions (``my_comp.py`` → ``my_comp.css`` / ``my_comp.html``).
    """
    if module_file.name == "__init__.py":
        base = module_file.parent / module_file.parent.name
    else:
        base = module_file
    return base.with_suffix(".css"), base.with_suffix(".html")
