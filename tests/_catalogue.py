"""Shared catalogue walking for the text-level component contracts.

The touch and mobile-arrangement rules are asserted against each component's own
template and stylesheet, so both guard modules must find the *same* components and
scan them with the same brace-aware helpers. One copy here means adding a plugin
package or a new scanning rule cannot fork the two audits.
"""
import importlib
import pkgutil
import re

from basis.shared.base_component import BaseComponent

#: The plugin packages whose templates and styles are audited (chrome + catalogue).
AUDITED_PACKAGES = ("basis.plugins.ui", "basis.plugins.shell")

_MEDIA_OPEN = re.compile(r"@media([^{]*)\{")
_QUERY = re.compile(r"@media\s*([^{]+)\{")

#: CSS comments, for scans that must not match commented-out rules.
COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def audited_classes():
    """Every component class defined under :data:`AUDITED_PACKAGES`."""
    found = {}
    for package_name in AUDITED_PACKAGES:
        package = importlib.import_module(package_name)
        for info in pkgutil.walk_packages(package.__path__, package_name + "."):
            module = importlib.import_module(info.name)
            for name in dir(module):
                obj = getattr(module, name)
                if (
                    isinstance(obj, type)
                    and issubclass(obj, BaseComponent)
                    and obj is not BaseComponent
                    and obj.__module__ == info.name
                    and obj.__tag__
                ):
                    found[f"{info.name}.{name}"] = obj
    return found


AUDITED = audited_classes()


def matching_brace(text, open_index):
    """Index of the ``}`` closing the ``{`` at *open_index*."""
    depth = 0
    for index in range(open_index, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    raise AssertionError("unbalanced braces in component CSS")


def strip_guarded_blocks(css, queries):
    """*css* with every ``@media`` block whose query matches *queries* removed."""
    out, index = [], 0
    while True:
        match = _MEDIA_OPEN.search(css, index)
        if not match:
            out.append(css[index:])
            return "".join(out)
        out.append(css[index : match.start()])
        end = matching_brace(css, match.end() - 1)
        if any(query in match.group(1) for query in queries):
            index = end + 1
        else:
            out.append(css[match.start() : end + 1])
            index = end + 1


def guarded_block_bodies(css, queries):
    """Only the body of every ``@media`` block whose query matches *queries*."""
    bodies, index = [], 0
    while True:
        match = _MEDIA_OPEN.search(css, index)
        if not match:
            return "".join(bodies)
        end = matching_brace(css, match.end() - 1)
        if any(query in match.group(1) for query in queries):
            bodies.append(css[match.end() : end])
        index = end + 1


def media_queries(css):
    """Every ``@media`` prelude in *css*, in order."""
    return [m.group(1).strip() for m in _QUERY.finditer(css)]


def component_css(cls) -> str:
    """Every stylesheet *cls* injects: the main one plus its additive ``@extra_style``
    blocks.

    The audits must read all of them — a rule that escapes to an additive block is still
    a rule (a modal's sheet arrangement is exactly that shape).
    """
    parts = [cls._get_style_string() or ""]
    parts.extend(css for _name, css in cls._get_extra_styles())
    return "\n".join(parts)
