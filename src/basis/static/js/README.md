# `/basis/js` — raw vendored JS

Static mount for raw JS libraries consumed by `@js_component`
(`basis/server/bootstrap.py`, `include_framework`):

```python
@js_component(module="/basis/js/chartlib/index.js", exports=["Chart"])
```

Files here are served verbatim — no VFS or Python transform — so a browser-native
ESM bundle can ship next to the Python package that uses it.

This file is also what keeps the directory in the distribution: git does not track
empty directories, and the mount requires its source directory to exist, so a
package built without it fails at `app.bootstrap()`.
