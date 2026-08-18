"""
basis/shared/expr.py
--------------------
The Basis safe expression language — the single place that turns a ``{...}``
template expression into a value.

Isomorphic (runs over the server ``Element`` model and the client DOM via
Pyodide):

* ``desugar_expression`` rewrites the Basis DSL (``$store`` / ``#comp``) into
  plain ``BaseComponent.S['store']`` / ``BaseComponent.C['comp']`` subscripts.
* ``_eval_ast`` evaluates the desugared AST against a whitelist of builtins, an
  optional loop-variable scope chain, and the owning component/context.
* ``safe_eval`` / ``safe_format`` are the public
  entry points with structured error capture (see ``errors.py``).
* ``extract_dependencies`` parses a template string to find the owner state
  fields it depends on, and caches the desugared AST trees for eval.

The expression engine is a standalone concern; ``bindings.py`` re-exports
these names for backwards compatibility.
"""

import ast
import operator
import re
import sys
import traceback
from string import Formatter
from typing import Any

# Structured error capture (see module docstring in errors.py)
from basis.shared.errors import (
    ERROR_PREFIX,
    EVAL_ERROR,
    SILENT_ERROR,
    find_template_line,
    import_error_hint,
    record_error,
)


IS_CLIENT = "pyscript" in sys.modules

if IS_CLIENT:
    from pyscript import ffi, document, window
else:
    ffi = None
    document = None
    window = None


# Module-level singleton — Formatter is stateless, no need to re-instantiate
_FORMATTER = Formatter()

# Module-level operator lookup dicts for _eval_ast (avoid rebuilding per-expression)
_BINOP_MAP = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.FloorDiv: operator.floordiv,
}

_CMPOP_MAP = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
    ast.In: operator.contains,
}


ALLOWED_BUILTINS = {'False': False,
                    'True': True,
                    'None': None,
                    'divmod': divmod,
                    'enumerate': enumerate,
                    'filter': filter,
                    'float': float,
                    'format': format,
                    'hex': hex,
                    'int': int,
                    'iter': iter,
                    'len': len,
                    'list': list,
                    'map': map,
                    'max': max,
                    'min': min,
                    'oct': oct,
                    'ord': ord,
                    'pow': pow,
                    'range': range,
                    'repr': repr,
                    'reversed': reversed,
                    'round': round,
                    'set': set,
                    'slice': slice,
                    'sorted': sorted,
                    'str': str,
                    'sum': sum,
                    'tuple': tuple,
                    'zip': zip}


class MissingStore:
    def __getattr__(self, name):
        return None
    def __getitem__(self, key):
        return None
    def __bool__(self):
        return False
    def __str__(self):
        return ""
    def __repr__(self):
        return "MissingStore"


def desugar_expression(expr: str) -> str:
    """Transform Basis DSL ($store, #comp) into valid Python (BaseComponent.S['store'], BaseComponent.C['comp'])."""
    if not expr:
        return expr
    # Replace $name with BaseComponent.S['name']
    expr = re.sub(r'\$([a-zA-Z_][a-zA-Z0-9_]*)', r"BaseComponent.S['\1']", expr)
    # Replace #id with BaseComponent.C['id']
    expr = re.sub(r'#([a-zA-Z_][a-zA-Z0-9_]*)', r"BaseComponent.C['\1']", expr)
    return expr


_MISSING = object()


class LoopScope:
    """Per-item name overlay for loop bodies.

    ``vars`` maps a loop-variable name to the current item; ``parent`` is the
    enclosing LoopScope (an outer loop) or None.  The owning component is NOT
    stored here — it is the binding's ``component_instance`` (the eval context).
    Resolution is innermost→outermost so a loop variable shadows the owner
    (Vue/Svelte rule).  A chain (not a merged dict) lets an outer item be
    updated in place and stay live for every inner scope that chains to it.
    """
    __slots__ = ("vars", "parent")

    def __init__(self, vars: dict, parent: "LoopScope|None" = None):
        self.vars = vars
        self.parent = parent

    def lookup(self, name):
        s = self
        while s is not None:
            if name in s.vars:
                return s.vars[name], True
            s = s.parent
        return None, False


def _eval_ast(node, context, allowed_builtins, scope=None):
    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)

        elif isinstance(node, ast.Name):
            if node.id in allowed_builtins:
                return allowed_builtins[node.id]

            # Loop-variable scope chain (innermost → outer) shadows the owner.
            if scope is not None:
                val, found = scope.lookup(node.id)
                if found:
                    return val

            # Check context (can be a dict or a component instance)
            if isinstance(context, dict):
                if node.id in context:
                    return context[node.id]
            else:
                if hasattr(context, node.id):
                    return getattr(context, node.id)
            
            raise NameError(f"Name {node.id} is not defined")

        elif isinstance(node, ast.Attribute):
            val = _eval(node.value)
            return getattr(val, node.attr)

        elif isinstance(node, ast.Subscript):
            val = _eval(node.value)
            if hasattr(ast, 'Index') and isinstance(node.slice, ast.Index):
                key = _eval(node.slice.value)
            else:
                key = _eval(node.slice)
            
            base_comp = allowed_builtins.get('BaseComponent')
            if base_comp:
                # Missing $store / #component references resolve to the falsy
                # MissingStore placeholder ("" when stringified) instead of
                # raising — the single "missing ref" policy.
                if val is getattr(base_comp, 'S', None) and key not in val:
                    return MissingStore()
                if val is getattr(base_comp, 'C', None) and key not in val:
                    return MissingStore()
            return val[key]

        elif isinstance(node, ast.Call):
            func = _eval(node.func)
            args = [_eval(arg) for arg in node.args]
            kwargs = {kw.arg: _eval(kw.value) for kw in node.keywords}
            return func(*args, **kwargs)

        elif isinstance(node, ast.Constant):
            return node.value

        elif isinstance(node, ast.List):
            return [_eval(e) for e in node.elts]

        elif isinstance(node, ast.Tuple):
            return tuple(_eval(e) for e in node.elts)

        elif isinstance(node, ast.Set):
            return {_eval(e) for e in node.elts}

        elif isinstance(node, ast.Dict):
            return {
                _eval(k): _eval(v)
                for k, v in zip(node.keys, node.values)
                if k is not None  # **kwargs splat is not supported
            }

        elif isinstance(node, ast.BinOp):
            left = _eval(node.left)
            right = _eval(node.right)
            op_type = type(node.op)
            if op_type in _BINOP_MAP:
                return _BINOP_MAP[op_type](left, right)
            raise ValueError(f"Unsupported binop {op_type}")

        elif isinstance(node, ast.Compare):
            left = _eval(node.left)
            for op, comparator in zip(node.ops, node.comparators):
                right = _eval(comparator)
                op_type = type(op)
                if op_type == ast.NotIn:
                    res = not operator.contains(right, left)
                elif op_type in _CMPOP_MAP:
                    if op_type == ast.In:
                        res = _CMPOP_MAP[op_type](right, left)
                    else:
                        res = _CMPOP_MAP[op_type](left, right)
                else:
                    raise ValueError(f"Unsupported cmp {op_type}")
                if not res: return False
                left = right
            return True

        elif isinstance(node, ast.UnaryOp):
            operand = _eval(node.operand)
            if isinstance(node.op, ast.Not): return not operand
            elif isinstance(node.op, ast.USub): return -operand
            elif isinstance(node.op, ast.UAdd): return +operand
            raise ValueError(f"Unsupported unary {type(node.op)}")

        elif isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                last_val = None
                for val in node.values:
                    last_val = _eval(val)
                    if not last_val:
                        return last_val
                return last_val
            elif isinstance(node.op, ast.Or):
                last_val = None
                for val in node.values:
                    last_val = _eval(val)
                    if last_val:
                        return last_val
                return last_val

        else:
            raise ValueError(f"Unsupported AST node type: {type(node).__name__}")
            
    return _eval(node)


def _report_binding_error(
    expr_str,
    context,
    exc,
    *,
    component=None,
    binding_type=None,
    template=None,
    template_line=None,
    stage="eval",
    phase=None,
):
    """Record a structured :class:`BindingError` (when a sink is registered) and
    tell the caller whether it was handled.

    Returns True when a sink consumed the record — the caller should then return
    the empty value (``""``) so the raw ``[Error: ...]`` string never reaches the
    rendered DOM.  Returns False when no sink is installed; the caller keeps the
    ``[Error: ...]`` sentinel.
    """
    # Callers pass a component *instance*; the record stores the class name
    # (instances are not JSON-serializable and are useless to an overlay).
    if component is not None and not isinstance(component, str):
        _cls = getattr(component, "__class__", component)
        component = getattr(_cls, "__name__", None) or str(component)
    elif component is None and not isinstance(context, dict):
        _cls = getattr(context, "__class__", None)
        if _cls is not None:
            component = getattr(_cls, "__name__", None) or type(context).__name__

    # Prefer the component's authored template for ``template_line`` reporting
    # (it has real line numbers); fall back to the binding's own content, then
    # the expression itself.
    src_template = None
    if not isinstance(component, str) and component is not None:
        src_template = getattr(getattr(component, "__class__", None), "__templatestr__", None)
    if src_template is None and not isinstance(context, dict):
        src_template = getattr(getattr(context, "__class__", None), "__templatestr__", None)
    if src_template:
        template = src_template
    if template is None:
        template = expr_str
    if template_line is None:
        template_line = find_template_line(template, expr_str)

    if phase is None:
        phase = "client" if IS_CLIENT else "server"
    recorded = record_error(
        component=component,
        binding_type=binding_type,
        expr=expr_str,
        template=template,
        error=str(exc),
        traceback=traceback.format_exc(),
        phase=phase,
        template_line=template_line,
        hint=import_error_hint(exc, phase),
    )

    # Server-side: keep a log line (the overlay lives on the client).
    # Client-side: the overlay/global replace console spam, so only log when
    # nothing consumed the record.
    if not recorded or phase == "server":
        location = f" ({binding_type})" if binding_type else ""
        print(f"[basis] {stage} error evaluating '{expr_str}'{location}: {exc}")
    return recorded


def safe_eval(expr_str, context, allowed_builtins, tree=None, *,
              component=None, binding_type=None, template=None, template_line=None,
              record=True, scope=None):

    if expr_str in allowed_builtins:
        return allowed_builtins[expr_str]

    if tree is None:
        try:
            tree = ast.parse(desugar_expression(expr_str), mode='eval')
        except Exception as e:
            if not record:
                return SILENT_ERROR
            if _report_binding_error(expr_str, context, e, component=component,
                                     binding_type=binding_type, template=template,
                                     template_line=template_line, stage="parse"):
                return EVAL_ERROR
            return f"{ERROR_PREFIX}{expr_str}]"

    try:
        return _eval_ast(tree.body if isinstance(tree, ast.Expression) else tree,
                         context, allowed_builtins, scope=scope)
    except Exception as e:
        if not record:
            return SILENT_ERROR
        if _report_binding_error(expr_str, context, e, component=component,
                                 binding_type=binding_type, template=template,
                                 template_line=template_line, stage="eval"):
            return EVAL_ERROR
        return f"{ERROR_PREFIX}{expr_str}]"

def safe_format(template_str, context, allowed_builtins, ast_trees=None, *,
                component=None, binding_type=None, template=None, template_line=None,
                record=True, scope=None):
    """Interpolate ``{...}`` fields in ``template_str`` into a string — the one
    resolver for every text/attribute binding.

    Every field is desugared once — either from the caller's cached
    ``ast_trees`` (desugared by ``extract_dependencies``) or by ``safe_eval``
    itself when no tree is supplied — and evaluated by ``safe_eval`` against
    (scope chain → owner).  ``$store.x`` / ``#id.x`` resolve through the
    ``BaseComponent.S/C`` subscript path in ``_eval_ast``; ``None`` renders as
    "" and a failed field aborts the whole template to "" (never a partial
    string, never a raw ``[Error: ...]`` when a sink is registered).
    """
    result = ""
    fname = None
    try:
        for literal_text, fname, format_spec, conversion in _FORMATTER.parse(template_str):
            result += literal_text
            if fname is not None:
                ast_tree = ast_trees.get(fname) if ast_trees else None
                val = safe_eval(fname, context, allowed_builtins, tree=ast_tree,
                                component=component, binding_type=binding_type,
                                template=template, template_line=template_line,
                                record=record, scope=scope)
                if val is EVAL_ERROR or val is SILENT_ERROR:
                    # A field failed — abort the whole template to the empty
                    # value rather than returning a partial string.
                    return ""
                if val is None:
                    val = ""
                if format_spec:
                    result += format(val, format_spec)
                else:
                    result += str(val)
    except Exception as e:
        if not record:
            return ""
        if _report_binding_error(fname or template_str, context, e,
                                 component=component, binding_type=binding_type,
                                 template=template or template_str,
                                 template_line=template_line, stage="eval"):
            return ""
        return f"{ERROR_PREFIX}{template_str}]"
    return result

def extract_dependencies(template_str, allowed_builtins=ALLOWED_BUILTINS):
    """
    Extracts dependencies from a template string and returns a tuple:
    (list of dependencies, dictionary of desugared AST trees mapping fname -> tree).
    """
    deps = set()
    trees = {}
    try:
        parsed_template = list(_FORMATTER.parse(template_str))
    except ValueError:
        # Handle cases where template_str is not a valid format string (e.g. CSS)
        return [], {}
    
    fnames = [fname for _, fname, _, _ in parsed_template if fname is not None]
    
    has_expr = any(fnames)

    if not has_expr:
        return [], {}
    
    for fname in fnames:

        desugared = desugar_expression(fname)

        try:
            tree = ast.parse(desugared, mode='eval')
            trees[fname] = tree

            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    if node.id not in allowed_builtins and node.id not in ['BaseComponent'] and isinstance(getattr(node, 'ctx', None), ast.Load):
                        deps.add(node.id)
                elif isinstance(node, ast.Attribute):
                    # Detect BaseComponent.S['store'].attr or BaseComponent.C['comp'].attr
                    if isinstance(node.value, ast.Subscript) and \
                       isinstance(node.value.value, ast.Attribute) and \
                       isinstance(node.value.value.value, ast.Name) and \
                       node.value.value.value.id == 'BaseComponent' and \
                       node.value.value.attr in ['S', 'C']:
                        
                        s_name = None
                        if isinstance(node.value.slice, ast.Constant):
                            s_name = node.value.slice.value
                        elif hasattr(ast, 'Index') and isinstance(node.value.slice, ast.Index) and isinstance(node.value.slice.value, ast.Constant):
                            s_name = node.value.slice.value.value
                        
                        if s_name:
                            prefix = '$' if node.value.value.attr == 'S' else '#'
                            deps.add(f"{prefix}{s_name}.{node.attr}")
                
                elif isinstance(node, ast.Subscript):
                    # Fallback for just BaseComponent.S['store'] without attribute
                    if isinstance(node.value, ast.Attribute) and \
                       isinstance(node.value.value, ast.Name) and \
                       node.value.value.id == 'BaseComponent' and \
                       node.value.attr in ['S', 'C']:
                        
                        s_name = None
                        if isinstance(node.slice, ast.Constant):
                            s_name = node.slice.value
                        elif hasattr(ast, 'Index') and isinstance(node.slice, ast.Index) and isinstance(node.slice.value, ast.Constant):
                            s_name = node.slice.value.value
                        
                        if s_name:
                            prefix = '$' if node.value.attr == 'S' else '#'
                            deps.add(f"{prefix}{s_name}")

        except SyntaxError:
            print(f"Error parsing expression: {desugared}")
        except Exception as e:
            print(f"Error extracting dependencies for {desugared}: {e}")

    return list(deps), trees
