"""Generate a project on disk from a ``ShellConfig`` (the writer path)."""

from __future__ import annotations

from pathlib import Path

from basis.cli.init.config import ShellConfig
from basis.cli.init.layout import build_context, build_inventory, dest_path
from basis.cli.init.render import render_template


def generate(config: ShellConfig, target_dir: Path) -> list[Path]:
    """Render every applicable template into ``target_dir``; return written paths.

    Validates ``config`` first (so an invalid config never creates a partial
    directory), builds the render context, then walks the registry's ``when``
    filter writing each file under ``target_dir``.
    """
    config.validate()
    context = build_context(config)
    written: list[Path] = []
    for template in build_inventory(config):
        source = render_template(template.source, context)
        dest = target_dir / dest_path(template, config)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(source, encoding="utf-8")
        written.append(dest)
    return written
