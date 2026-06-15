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
