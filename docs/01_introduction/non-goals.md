# Non-Goals

Knowing what a framework does not do is as important as knowing what it does. These are deliberate trade-offs, not gaps to be filled later.

---

## 1. Strict Theoretical Correctness

Basis prioritizes practical usability over academic purity. You can mutate a list in-place:

```python
self.items.append(new_item)
```

This works. Basis uses proxies and fine-grained change interception to detect mutations rather than requiring immutable update patterns. If you're looking for a framework that enforces functional state pipelines throughout, Basis is probably not the right fit.

---

## 2. Winning Micro-Benchmarks

Basis does not aim to top raw DOM rendering benchmarks. For the applications it's designed for — data dashboards, internal tools, SaaS platforms — rendering speed is rarely the bottleneck. Network latency, database queries, and developer time are.

The DAG reactivity engine does update only the nodes that changed, so performance is solid in practice. But if you're evaluating frameworks based on how fast they can render 100,000 rows in a synthetic benchmark, that's not what Basis is optimized for.

---

## 3. High-Performance Graphics and Games

Basis is for web applications. It is not designed for real-time 3D rendering, complex audio processing, or game engines. Those use cases belong in native WebGL/WebGPU or compiled WebAssembly.

---

## 4. Replacing Backend Infrastructure

Basis extends FastAPI — it doesn't replace it. Authentication, database transactions, security checks, and heavy processing stay on the server where they belong. Basis provides a clean bridge between frontend components and backend logic, but it doesn't collapse that distinction.

> [!WARNING]
> Always enforce authorization and validation in your `@server_action` methods. The client can call server actions, but the server should never assume the client-supplied state is trustworthy.
