"""Official Basis plugins, shipped in-tree with the framework.

Each subpackage is a self-contained :class:`~basis.server.plugin.BasisPlugin`
registered through the standard ``basis.plugins`` entry-point mechanism, so the
framework's own plugins use the exact same discovery/lifecycle path as
third-party plugins ("everything is a plugin").
"""
