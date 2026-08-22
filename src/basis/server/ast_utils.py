import ast
import logging

logger = logging.getLogger('uvicorn.error')

class ServerActionStripper(ast.NodeTransformer):
    """
    AST Transformer that finds functions/methods decorated with @server_action
    and replaces their body with 'pass'.
    """
    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        # Check if '@server_action' or '@plugin.action' is in the decorator list
        is_server_action = False
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Name) and decorator.id in ('server_action', 'action'):
                is_server_action = True
                break
            elif isinstance(decorator, ast.Attribute) and decorator.attr in ('server_action', 'action'):
                is_server_action = True
                break
            elif isinstance(decorator, ast.Call):
                # Handle @server_action(...) or @plugin.action(...)
                func = decorator.func
                if isinstance(func, ast.Name) and func.id in ('server_action', 'action'):
                    is_server_action = True
                    break
                elif isinstance(func, ast.Attribute) and func.attr in ('server_action', 'action'):
                    is_server_action = True
                    break

        if is_server_action:
            # Hollow out the function body
            # We replace it with 'pass'
            node.body = [ast.Pass()]
            logger.debug(f"AST: Stripped body of server/plugin action: {node.name}")
            
        return self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AsyncFunctionDef:
        # Same logic for async functions
        return self.visit_FunctionDef(node) # type: ignore

def strip_server_actions(source: str) -> str:
    """
    Parses source code, strips bodies of @server_action functions, and returns modified source.
    """
    try:
        tree = ast.parse(source)
        transformer = ServerActionStripper()
        new_tree = transformer.visit(tree)
        ast.fix_missing_locations(new_tree)
        return ast.unparse(new_tree)
    except Exception as e:
        logger.error(f"AST: Failed to strip server actions: {e}")
        return source # Fallback to original source on error


def collect_imported_modules(source: str) -> list[str]:
    """
    Return the dotted module paths *source* imports (``import X`` /
    ``from X import ...``; absolute imports only).

    Used to build the plugin dependency list: which client modules import a
    plugin-owned package, so a plugin can be marked *essential* (refusing
    disable/remove). A plain list of direct imports — no transitive closure is
    needed: a plugin is pinned iff any enabled consumer imports it directly,
    and the importer names give the reason surfaced when unloading is refused.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # Absolute imports only — relative imports stay within the package
            # and can never be a cross-plugin dependency.
            if node.module and node.level == 0:
                imported.append(node.module)
    return imported
