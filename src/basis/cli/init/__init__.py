"""The ``basis init`` wizard + template system (INIT-SHELL-PLAN.md).

Decoupled pipeline: ``config`` (ShellConfig, one answer record) → ``layout``
(render context + file inventory) → ``registry`` (which files) + ``render``
(Jinja2-based rendering) → the writer path (wired in P3). Everything here is
pure/stdlib + jinja2, so the whole pipeline is unit-testable without a TTY.
"""
