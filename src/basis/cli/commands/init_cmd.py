"""
``basis init <project-name>`` — Scaffold a new Basis project.

Generates a best-practice project structure with all the directories and
starter files a developer needs to begin building a Basis app.
"""

from __future__ import annotations

import re
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.tree import Tree

console = Console()


def init(
    project_name: str = typer.Argument(
        ...,
        help="Name for the new project (e.g. 'my-app').",
    ),
    directory: str = typer.Option(
        None,
        "--dir",
        "-d",
        help="Parent directory to create the project in. Defaults to current directory.",
    ),
):
    """
    Scaffold a new Basis project with best-practice structure.

    Creates a complete project skeleton including components, state management,
    plugins directory, and a starter root component ready for development.
    """
    # Normalise the project name
    project_slug = re.sub(r"[^a-zA-Z0-9_]", "_", project_name.lower().replace("-", "_"))
    if not project_slug or project_slug[0].isdigit():
        console.print(f"[bold red]Error:[/] Invalid project name '{project_name}'.")
        raise typer.Exit(code=1)

    parent = Path(directory).resolve() if directory else Path.cwd()
    project_dir = parent / project_name
    src_dir = project_dir / "src" / project_slug

    if project_dir.exists():
        console.print(f"[bold red]Error:[/] Directory '{project_dir}' already exists.")
        raise typer.Exit(code=1)

    console.print(f"\n[bold cyan]Creating[/] [bold white]{project_name}[/]...\n")

    # Create directory structure
    dirs = [
        src_dir / "components",
        src_dir / "plugins",
        src_dir / "stores",
        src_dir / "static",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    # Generate files
    _write_pyproject(project_dir, project_name, project_slug)
    _write_package_init(src_dir, project_slug)
    _write_root_component(src_dir / "components")
    # components/ must be a proper package for auto-discovery (isomorphism:
    # client VFS namespace == filesystem import namespace).
    (src_dir / "components" / "__init__.py").write_text("")
    _write_example_store(src_dir / "stores")
    _write_plugins_init(src_dir / "plugins")
    _write_readme(project_dir, project_name)
    _write_gitignore(project_dir)

    # Display the created structure
    tree = Tree(f"📁 [bold cyan]{project_name}/[/]")
    _build_tree(tree, project_dir, project_dir)
    console.print(tree)

    # Success message
    console.print()
    panel = Panel(
        f"[bold green]✅ Project created![/]\n\n"
        f"  [dim]$[/] cd {project_name}\n"
        f"  [dim]$[/] uv sync\n"
        f"  [dim]$[/] basis dev\n",
        title="[bold white]Next Steps[/]",
        border_style="green",
        padding=(1, 2),
    )
    console.print(panel)


def _build_tree(tree: Tree, current: Path, root: Path, depth: int = 0):
    """Recursively build a Rich Tree from the filesystem."""
    if depth > 4:
        return

    entries = sorted(current.iterdir(), key=lambda p: (p.is_file(), p.name))
    for entry in entries:
        if entry.name.startswith(".") and entry.name != ".gitignore":
            continue
        if entry.name == "__pycache__":
            continue

        if entry.is_dir():
            branch = tree.add(f"📁 [cyan]{entry.name}/[/]")
            _build_tree(branch, entry, root, depth + 1)
        else:
            icon = _file_icon(entry.name)
            tree.add(f"{icon} {entry.name}")


def _file_icon(name: str) -> str:
    if name.endswith(".py"):
        return "🐍"
    if name.endswith(".toml"):
        return "⚙️"
    if name.endswith(".md"):
        return "📄"
    if name.endswith(".html"):
        return "🌐"
    if name.endswith(".css"):
        return "🎨"
    return "📄"


# ---------------------------------------------------------------------------
# Template generators
# ---------------------------------------------------------------------------


def _write_pyproject(project_dir: Path, project_name: str, project_slug: str):
    content = f'''\
[project]
name = "{project_name}"
version = "0.1.0"
description = "A Basis web application"
readme = "README.md"
requires-python = ">=3.14"
dependencies = [
    "basis-framework",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/{project_slug}"]
'''
    (project_dir / "pyproject.toml").write_text(content)


def _write_package_init(src_dir: Path, project_slug: str):
    content = f'''\
"""
{project_slug} — A Basis web application.
"""

from basis.server.app import Basis

app = Basis()

# Bootstrap the framework. Conventional subdirectories (components/, stores/,
# plugins/) are auto-discovered: components/ and stores/ are mounted with
# package-derived paths (so client VFS == filesystem == IDE import names), and
# stores/ modules are imported so their module-scope store instances register.
app.bootstrap()
'''
    (src_dir / "__init__.py").write_text(content)


def _write_root_component(components_dir: Path):
    # Python component
    py_content = '''\
from basis.shared.component import Component


class App(Component):
    """Root application component."""

    tag_name = "app-root"

    def state(self):
        return {
            "title": "Welcome to Basis! 🧱",
            "count": 0,
        }

    def methods(self):
        return {
            "increment": self.increment,
        }

    def increment(self):
        self.count += 1
'''
    (components_dir / "app.py").write_text(py_content)

    # HTML template
    html_content = '''\
<div class="app-container">
    <header class="hero">
        <h1>{{ title }}</h1>
        <p class="subtitle">Your full-stack Python reactive web app is ready.</p>
    </header>

    <section class="demo-card">
        <p class="counter">Count: <strong>{{ count }}</strong></p>
        <button @click="increment">Click me</button>
    </section>

    <footer>
        <p>
            Edit <code>components/app.py</code> to get started.
            <br/>
            Run <code>basis dev</code> for hot-reload development.
        </p>
    </footer>
</div>
'''
    (components_dir / "app.html").write_text(html_content)

    # CSS styles
    css_content = '''\
:host {
    display: block;
    font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif;
    color: #e0e0e0;
    background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 50%, #16213e 100%);
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
}

.app-container {
    text-align: center;
    max-width: 600px;
    padding: 3rem 2rem;
}

.hero h1 {
    font-size: 2.5rem;
    font-weight: 700;
    background: linear-gradient(135deg, #667eea, #764ba2);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin-bottom: 0.5rem;
}

.subtitle {
    font-size: 1.1rem;
    color: #888;
}

.demo-card {
    margin: 2rem auto;
    padding: 2rem;
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 12px;
    backdrop-filter: blur(10px);
}

.counter {
    font-size: 1.5rem;
    margin-bottom: 1rem;
}

button {
    padding: 0.75rem 2rem;
    font-size: 1rem;
    font-weight: 600;
    color: white;
    background: linear-gradient(135deg, #667eea, #764ba2);
    border: none;
    border-radius: 8px;
    cursor: pointer;
    transition: transform 0.15s ease, box-shadow 0.15s ease;
}

button:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 20px rgba(102, 126, 234, 0.4);
}

button:active {
    transform: translateY(0);
}

footer {
    margin-top: 2rem;
    color: #666;
    font-size: 0.9rem;
    line-height: 1.8;
}

code {
    background: rgba(255, 255, 255, 0.1);
    padding: 0.15em 0.4em;
    border-radius: 4px;
    font-size: 0.85em;
}
'''
    (components_dir / "app.css").write_text(css_content)


def _write_example_store(stores_dir: Path):
    content = '''\
from basis.shared.store import Store


class AppStore(Store):
    """Global application state. Class attributes become reactive state."""

    user = None
    theme = "dark"


# Module-scope instance — the stores auto-discovery convention. Instantiating
# at module scope registers this store's blueprint (name → class + config) so
# Page.stores can resolve it by name and SSR/RPC can rebuild it.
app_store = AppStore("app_store")
'''
    (stores_dir / "__init__.py").write_text("")
    (stores_dir / "app_store.py").write_text(content)


def _write_plugins_init(plugins_dir: Path):
    content = '''\
# Basis auto-discovers plugins in this directory.
# Each .py file or package here should expose a `plugin` variable
# that is a BasisPlugin instance.
#
# Example (plugins/analytics.py):
#
#     from basis.server.plugin import BasisPlugin
#
#     plugin = BasisPlugin(
#         prefix="/analytics",
#         name="analytics",
#     )
#
#     @plugin.action
#     async def track_event(event_name: str):
#         return {"tracked": True}
'''
    (plugins_dir / "__init__.py").write_text(content)


def _write_readme(project_dir: Path, project_name: str):
    content = f"""\
# {project_name}

A web application built with [Basis](https://github.com/bassio/basis) — the full-stack Python reactive web framework.

## Getting Started

```bash
# Install dependencies
uv sync

# Start the development server
basis dev
```

## Project Structure

```
src/{project_name.replace("-", "_")}/
├── __init__.py          # App setup (Basis instance)
├── components/          # UI components (.py + .html + .css), auto-discovered
│   ├── __init__.py
│   └── app.py           # Root component
├── plugins/             # Auto-discovered plugins
├── stores/              # Global stores, auto-discovered
│   ├── __init__.py
│   └── app_store.py     # Example store
└── static/              # Static assets
```

## Learn More

- [Basis Documentation](https://github.com/bassio/basis)
- [Plugin Guide](https://github.com/bassio/basis/docs/plugins.md)
"""
    (project_dir / "README.md").write_text(content)


def _write_gitignore(project_dir: Path):
    content = """\
__pycache__/
*.pyc
.venv/
*.egg-info/
dist/
build/
.pytest_cache/
*.db
"""
    (project_dir / ".gitignore").write_text(content)
