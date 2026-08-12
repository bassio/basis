# Appendix: CLI Tooling (`basis`)

The Basis Framework includes a developer CLI tool (`basis`) designed to streamline application development, project initialization, and plugin management.

---

## Command Overview

```bash
basis [OPTIONS] COMMAND [ARGS]...
```

| Command | Description |
| :--- | :--- |
| `basis dev` | Start the development server with auto-detection, auto-reload, and plugin scanning. |
| `basis init <name>` | Scaffold a new Basis project. |
| `basis plugin list` | List all discovered local and installed plugins. |

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
If `APP_PATH` is omitted, `basis dev` automatically scans your current directory for common Basis application entry points (`app.py:app`, `main.py:app`, etc.).

### Command Flags

| Flag | Short | Default | Description |
| :--- | :--- | :--- | :--- |
| `--host` | `-h` | `127.0.0.1` | Bind host address. |
| `--port` | `-p` | `8000` | Bind port number. |
| `--reload / --no-reload` | | `True` | Automatically reload on file changes. |
| `--pyc` | | `False` | Enable **PYC Compilation Mode** (serves pre-compiled bytecode to PyScript client VFS). |

### Example Usage

Start dev server with default options:
```bash
basis dev
```

Run on custom host and port with PYC mode enabled:
```bash
basis dev myapp:app --host 0.0.0.0 --port 8080 --pyc
```

### Startup Banner & Plugin Summary
When launched, `basis dev` displays a formatted console output:
- **App Import Path & URL**
- **Project Directory & Watch Mode**
- **Discovered Local Plugins** (`plugins/` directory)
- **Discovered Installed Packages** (`basis.plugins` entry points)

---

## 2. `basis init` — Project Scaffolding

Scaffold a new Basis project structure:

```bash
basis init my-awesome-app
```

This creates a clean workspace pre-configured with:
- Standard `app.py` entrypoint.
- `components/` directory for single/multi-file UI components.
- `plugins/` directory for auto-discovered plugins.
- `pyproject.toml` or dependency setup.

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
