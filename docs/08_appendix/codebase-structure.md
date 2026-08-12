# Codebase Structure

Below is an overview of the core directories and modules within the Basis framework repository:

```text
src/basis/
├── cli/              # Developer CLI commands (dev, init, plugin)
├── ui/               # Built-in component suite (button, toast, breadcrumbs, etc.)
├── client/           # Browser-side component mounting and PyScript runtime
├── server/           # FastAPI app wrapper, static file servers, PYC compiler, RPC router
└── shared/           # Isomorphic shared code between server and PyScript client
    ├── reactive.py   # Unified reactive dependency graph engine (DAG)
    ├── bindings.py   # DOM bindings (Text, Attribute, Loops, Slots, FormModel)
    ├── store.py      # State stores and reactive collections
    └── base_component.py # Component lifecycle, state mapping, and setup
```

---

## Directory & Module Details

- **`src/basis/cli/`**: Implements the `basis` command-line utility (`basis dev`, `basis init`, `basis plugin`).
- **`src/basis/ui/`**: Pre-built accessible UI primitives (`Button`, `Toast`, `Breadcrumbs`, `CommandPalette`, `AudioRecorder`, etc.).
- **`src/basis/shared/reactive.py`**: The central `DependencyGraph` (DAG), `StateNode`, `ComputedNode`, `EffectNode`, and `ReactiveObject` implementation.
- **`src/basis/shared/bindings.py`**: DOM bindings connecting template nodes to DAG effect updates.
- **`src/basis/shared/base_component.py`**: Component initialization, AST template analysis, slot filling, and state node creation.
- **`src/basis/client/`**: Browser-side PyScript mount logic, action invocation, and DOM hydration.
- **`src/basis/server/`**: FastAPI application class (`Basis`), server-side rendering pipeline, `.pyc` bytecode compiler, and `@server_action` RPC endpoints.
