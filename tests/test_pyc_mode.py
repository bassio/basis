import importlib.util
import marshal
import os
import tempfile
import time
import pytest
import sys

from pathlib import Path
from starlette.requests import Request
from starlette.datastructures import Headers

from basis.server.app import Basis
from basis.server.static import BasisStaticFiles, BasisStaticFilesPyc, compile_to_pyc_bytes



def test_compile_to_pyc_bytes():
    source = "def calc(a, b):\n    return a + b\n"
    pyc_bytes = compile_to_pyc_bytes(source, "test_calc.py")
    
    assert len(pyc_bytes) > 16
    assert pyc_bytes[:4] == importlib.util.MAGIC_NUMBER
    
    # Extract code object from bytecode payload (skip 16-byte header)
    code_obj = marshal.loads(pyc_bytes[16:])
    
    namespace = {}
    exec(code_obj, namespace)
    assert "calc" in namespace
    assert namespace["calc"](3, 4) == 7


@pytest.mark.anyio
async def test_basis_static_files_pyc_serving_and_stripping():
    with tempfile.TemporaryDirectory() as tmpdir:
        comp_file = Path(tmpdir) / "my_comp.py"
        source_code = (
            "from basis.shared.actions import server_action\n\n"
            "class MyComp:\n"
            "    @server_action\n"
            "    def secret_backend_logic(self):\n"
            "        db_pass = 'super_secret'\n"
            "        return db_pass\n\n"
            "    def client_method(self):\n"
            "        return 'hello_client'\n"
        )
        comp_file.write_text(source_code)

        static_handler = BasisStaticFilesPyc(directory=tmpdir)

        # Mock ASGI Scope for GET /my_comp.pyc
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/my_comp.pyc",
            "headers": Headers(raw=[(b"host", b"testserver")]).raw,
        }

        response = await static_handler.get_response("my_comp.pyc", scope)
        assert response.status_code == 200
        assert response.media_type in ("application/x-python-code", "application/x-bytecode.python")

        # Verify pyc header and payload
        pyc_bytes = response.body
        assert pyc_bytes[:4] == importlib.util.MAGIC_NUMBER
        
        # Unmarshal and verify @server_action body was stripped to 'pass'
        code_obj = marshal.loads(pyc_bytes[16:])
        namespace = {}
        exec(code_obj, namespace)

        comp_inst = namespace["MyComp"]()
        assert comp_inst.client_method() == "hello_client"
        # Secret method body should return None (since body was replaced with 'async def ... pass')
        res = await comp_inst.secret_backend_logic()
        assert res is None


def test_vfs_registry_pyc_mode(monkeypatch):
    monkeypatch.setattr("sys.version_info", (3, 12, 0, "final", 0))
    app = Basis(pyc_mode=True)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        app.include_components_dir("/components", tmpdir, "components")

        vfs_files = app.vfs.files
        
        # Verify client and shared framework files have .pyc extensions
        assert "{DOMAIN}/basis/client/component.pyc" in vfs_files
        assert vfs_files["{DOMAIN}/basis/client/component.pyc"] == "./basis/client/component.pyc"
        
        assert "{DOMAIN}/basis/shared/reactive.pyc" in vfs_files
        assert vfs_files["{DOMAIN}/basis/shared/reactive.pyc"] == "./basis/shared/reactive.pyc"


def test_basis_pyc_mode_environment_variable(monkeypatch):
    monkeypatch.setattr("sys.version_info", (3, 12, 0, "final", 0))
    monkeypatch.setenv("BASIS_PYC_MODE", "1")
    app = Basis()
    assert app.pyc_mode is True
