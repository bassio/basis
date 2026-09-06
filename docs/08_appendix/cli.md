# Appendix: CLI Tooling (`basis`)

The Basis Framework includes a developer CLI tool (`basis`) designed to streamline application development, project initialization, and plugin management.

---

## Command Overview

```bash
basis [OPTIONS] COMMAND [ARGS]...
```

| Command | Description |
| :--- | :--- |
| `basis dev` | Start the development server with auto-detection, live HMR, and plugin scanning. |
| `basis init [name]` | Interactive app-shell wizard: scaffold a loadable workbench (`app`) or website (`site`) project. |
| `basis bench` | Run the framework benchmark suite (median + p95) — see [ROADMAP-PERFORMANCE.md T0](https://github.com/bassio/basis/blob/main/ROADMAP-PERFORMANCE.md). |
| `basis plugin list` | List all discovered local and installed plugins. |
| `basis theme list` | List installed theme packages (`kind == "theme"`). |
| `basis theme apply <id>` | Resolve + validate a theme by id (loud errors on a broken manifest). |

### Plugin-contributed commands

Basis plugins can extend the CLI with their own command groups. The hook point is
**`basis <plugin-name> <subcommand>`** (namespaced by the plugin's identifier — the
same name used by `$plugins.<name>`). A plugin ships its commands in a `cli/`
subpackage exposing a module-level `cli` that is a `typer.Typer`:

```text
myapp/plugins/migrations/
    __init__.py          # plugin = BasisPlugin(...)
    cli/
        __init__.py      # cli = typer.Typer(...)  →  basis migrations up
```

The `cli/__init__.py` may also declare a module-level `help = "…"` string — the
one-line description shown in `basis --help`. Discovery reads it straight from
source (no import), so the root help shows each group's real description while
staying import-free; without it, a generic `{plugin} commands` line is used.

The CLI mounts these groups **lazily** (import-on-first-use): `basis dev` /
`basis init` / `basis bench` never import plugin code, and a plugin's `cli/`
module is imported only when one of its commands is actually requested. Installed
plugins always contribute; local `plugins/` plugins contribute when the command
is run inside the project.

`basis theme list` and `basis theme apply` are themselves contributed this way —
they live in the `theme` plugin (`basis.plugins.theme.cli`), not hardcoded in the
CLI core.

To check the CLI version:
```bash
basis --version
```

---

## 1. `basis dev` — Development Server

The `basis dev` command wraps `uvicorn` with auto-detection and developer-focused feedback.

```bash
basis dev [APP_PATH] [FLAGS]
```

### Automatic App Detection
If `APP_PATH` is omitted, `basis dev` auto-detects the app in this order:

1. `pyproject.toml` project name → `src/<name>/__init__.py` containing a module-level `app = Basis()` — the exact layout `basis init` generates.
2. Any `src/<package>/__init__.py` containing a module-level `Basis()` instance.
3. A root `app.py` / `main.py` (or a root `__init__.py`) containing `app = Basis()`.

### Command Flags

| Flag | Short | Default | Description |
| :--- | :--- | :--- | :--- |
| `--host` | `-h` | `127.0.0.1` | Bind host address. |
| `--port` | `-p` | `8000` | Bind port number. |
| `--hmr / --no-hmr` | | `True` | **Live client-side HMR** (default): watch component files (`.py`/`.html`/`.css`) and hot-swap them in the browser over a WebSocket — no page refresh, no state loss. |
| `--reload / --no-reload` | | `False` | Full-process restart on any file change (uvicorn `--reload`). Mutually exclusive with HMR — use while editing server-only code outside component directories. |
| `--pyc` | | `False` | Enable **PYC Compilation Mode** (serves pre-compiled bytecode to PyScript client VFS). |
| `--profile` | | `False` | Run the server under `cProfile` and print a hot-path summary on shutdown (saves `.basis-profile.pstats`). T0 server profiling — see `tests/benchmarks/README.md`. |

### Example Usage

Start dev server with default options:
```bash
basis dev
```

Run on custom host and port with PYC mode enabled:
```bash
basis dev myapp:app --host 0.0.0.0 --port 8080 --pyc
```

Profile the server and print a hot-path summary on shutdown (SSR/action profiling):
```bash
basis dev --profile
```

### Startup Banner & Plugin Summary
When launched, `basis dev` displays a formatted console output:
- **App Import Path & URL**
- **Project Directory & Watch Mode**
- **Discovered Local Plugins** (`plugins/` directory)
- **Discovered Installed Packages** (`basis.plugins` entry points)

---

## 2. `basis init` — Interactive App-Shell Wizard

`basis init` is a cookiecutter-style interactive wizard (create-react-app for
Basis). It asks a short series of questions — project name → shell paradigm →
top-level stack → extras — then generates a **loadable app shell** (workbench
`app` or website `site`) that runs on `basis dev --hmr` out of the box, with an
SSR page registered at `/`.

```bash
basis init [PROJECT_NAME] [FLAGS]
```

### Interactive flow

Run it with no arguments (or just a project name) and answer the prompts:

```text
$ basis init

  0 · Project
   · Project / package name:   my-app

  A · Shell paradigm
   · Shell paradigm:           app (workbench) / site (website)

  B · Top-level Stack
   · Include a Titlebar?       y
   · Include a Statusbar?      y
   · Include an ActivityBar?   y
   · Include a Left Sidebar?   y
   · ...

  C · Extras
   · Theme seed:               dark
   · Generate demo content?    y
   · Generate an example store?  y
   · Generate an example plugin? y

  Create project 'my-app' in /path/to/cwd?  [y/n]  y
```

Each answer group renders a live "current plan" panel; the wizard only asks
questions that apply to the chosen paradigm (`site` hides the workbench chrome
questions and vice-versa). Ctrl-C aborts without writing anything.

### Command Flags

| Flag | Short | Description |
| :--- | :--- | :--- |
| `PROJECT_NAME` | | Project name. If omitted, the wizard asks (default: the current directory name). |
| `--dir` | `-d` | Parent directory to create the project in (default: current directory). |
| `--shell` | | Shell paradigm: `app` (fixed-viewport workbench) or `site` (document-flow website). |
| `--theme` | | Theme seed: `dark` or `light`. |
| `--sidebar-left-collapsible` | | Left sidebar collapse mode: `none` \| `icon` \| `offcanvas`. |
| `--titlebar/--no-titlebar` | | Include a Titlebar (app). |
| `--statusbar/--no-statusbar` | | Include a Statusbar (app). |
| `--activitybar/--no-activitybar` | | Include an ActivityBar (app). |
| `--sidebar-left/--no-sidebar-left` | | Include a Left Sidebar (app). |
| `--sidebar-right/--no-sidebar-right` | | Include a Right Sidebar (app). |
| `--header/--no-header` | | Include a Header / nav (site). |
| `--footer/--no-footer` | | Include a Footer (site). |
| `--sticky-header/--no-sticky-header` | | Make the header sticky (site). |
| `--demo/--no-demo` | | Generate demo content (reactive counter + sample list). |
| `--store/--no-store` | | Generate an example store (`stores/app_state.py`). |
| `--plugin/--no-plugin` | | Generate an example plugin (`plugins/demo.py`). |
| `--yes` | `-y` | Non-interactive: build the project from defaults plus any flags given (a minimal loadable skeleton). |
| `--config` | | Path to a JSON answers file to replay (non-interactive). |
| `--list` | | Print the wizard's question tree and exit. |

Provided flags pre-fill the wizard and skip those questions; unset flags fall
back to the wizard defaults. In `--yes` / `--config` mode flags become hard
values.

### Non-interactive generation

```bash
# Minimal loadable skeleton (defaults, no prompts):
basis init my-app --yes

# A site with no footer, no demo, no store/plugin:
basis init my-site --shell site --no-footer --no-demo --no-store --no-plugin

# Replay a saved answers file (an explicit flag overrides the file):
basis init --config answers.json --shell app

# Preview the wizard's questions:
basis init --list
```

### Generated structure

```text
my-app/
├── pyproject.toml              # name, requires-python >=3.14, basis-framework, hatchling
├── .gitignore
├── README.md
└── src/
    └── my_app/
        ├── __init__.py         # app = Basis(); app.bootstrap(); app.serve("/")(HomePage)
        ├── components/
        │   ├── __init__.py
        │   ├── page.py             # HomePage(Page): root_component, stores default-all
        │   ├── app_container.py    # the shell frame (app or site) + demo blocks
        │   ├── titlebar.py         # MyTitleBar(TitleBar)      (app)
        │   ├── statusbar.py        # MyStatusBar(StatusBar)    (app)
        │   ├── activitybar.py      # MyActivityBar(ActivityBar) (app)
        │   └── sidebar.py          # MySidebarLeft / MySidebarRight (app)
        ├── stores/
        │   ├── __init__.py
        │   └── app_state.py        # AppState(Store) + module-scope instances (when --store)
        ├── plugins/
        │   ├── __init__.py
        │   └── demo.py             # DemoView added to workspace-center (when --plugin)
        └── static/
            └── app.css             # override layer, linked via HomePage.stylesheets
```

The generated app is a normal Basis project — install deps, then dev-serve:

```bash
cd my-app
uv sync
basis dev            # auto-detects my_app:app, serves /, live HMR on
```

- **SSR page at `/`** — `components/page.py` registers `HomePage`, an SSR page, at the root route.
- **Demo (default on)** — a reactive counter (`count`), a store-backed list
  (`app_state.add_item` via a canonical-path server action), and a theme toggle
  that flips the design tokens.
- **Example plugin (default on)** — `plugins/demo.py` registers `DemoView` into
  the `workspace-center` region, proving the regions/plugin story end to end.

---

## 3. `basis plugin` — Plugin Management

Inspect and manage Basis plugins installed in the environment or defined locally.

### List Discovered Plugins

```bash
basis plugin list
```

This scans:
1. **Local Plugins**: Python modules/packages inside the `plugins/` directory exposing a module-level `plugin` variable.
2. **Installed Plugins**: Third-party packages registered via the `basis.plugins` entry point in `pyproject.toml`.

Themes (`kind == "theme"`) are excluded from `basis plugin list` — they live under
`basis theme`.

---

## 4. `basis theme` — Theme Management

Inspect and validate theme packages — `Theme(BasisPlugin)` instances
(`kind == "theme"`) discovered through the standard `basis.plugins` entry
points, the same catalog the theme manager renders from `$themes`.

### List Installed Themes

```bash
basis theme list
```

Shows each installed theme's id, display name, plugin, version and modes. The
in-tree themes are `basis` (the built-in default) and `ambient` (the dogfood).

### Resolve + Validate a Theme

```bash
basis theme apply ambient
```

Resolves the theme by id (installed themes or the built-in `basis`), validates
its manifest, and prints the resolved metadata. A broken theme package fails
**loudly** (clear `ValueError`), so a bad community theme is caught here — not at
3am in a browser.

At runtime the theme is applied per-user via the theme manager
(`<ui-theme-picker>`) and persists through the `basis_theme` cookie. A per-app
default-theme seed from the CLI is a later phase.

---

## 5. `basis bench` — Benchmark Suite (T0)

Runs the framework's realistic benchmark scenarios and reports **median + p95**
timings (plus mean; full min/max/stdev via `--json`). This is the T0
"Measure First" harness — the baseline against which T1+ optimization work is
judged and the future CI regression gate. See
[`tests/benchmarks/README.md`](https://github.com/bassio/basis/blob/main/tests/benchmarks/README.md) for the
scenario list, baseline numbers, and client/server profiling notes.

```bash
basis bench              # full suite, 5 iterations per scenario
basis bench --quick      # 1 iteration each (fast smoke)
basis bench -s loop      # only scenarios whose name contains "loop"
basis bench -n 3 --json  # 3 iterations, machine-readable output (CI)
```

Scenarios: mount N components (50/200), mutate M state fields in one handler
(10/25, sequential vs `refrain()`-batched), render a 1k/10k-row keyed loop,
hydrate an SSR page (1k-row root), fan-out a store to 50/100 subscribers, and a
template-parse/format baseline. Under pytest, the same scenarios are opt-in:

```bash
pytest tests/benchmarks --bench
```
