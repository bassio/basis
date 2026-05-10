import asyncio
import functools
import importlib.util
import inspect
import itertools
import logging
import os
from pathlib import Path
from typing import Set
from urllib.parse import urljoin
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles
from fastapi import FastAPI, APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, HTMLResponse

from basis.server.db import DBAppMixin

ONLINE_PYSCRIPT = "https://pyscript.net/releases/2026.3.1"

logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)

async def pyscript_json(request:Request):

    components = []

    files_dict = {}
    
    base_url = str(request.base_url)

    files_dict["{DOMAIN}"] = base_url.removesuffix("/")

    #add main component.py
    files_dict["{DOMAIN}/basis/components/component.py"] = "./basis/components/component.py"
    files_dict["{DOMAIN}/basis/components/component.js"] = "./basis/components/component.js"

    #add shared
    files_dict["{DOMAIN}/basis/shared/store.py"] = "./basis/shared/store.py"
    files_dict["{DOMAIN}/basis/shared/bindings.py"] = "./basis/shared/bindings.py"
    files_dict["{DOMAIN}/basis/shared/base_component.py"] = "./basis/shared/base_component.py"
    files_dict["{DOMAIN}/basis/shared/element.py"] = "./basis/shared/element.py"
    files_dict["{DOMAIN}/basis/shared/component.py"] = "./basis/shared/component.py"
    files_dict["{DOMAIN}/basis/shared/context.py"] = "./basis/shared/context.py"
    files_dict["{DOMAIN}/basis/shared/dag.py"] = "./basis/shared/dag.py"
    files_dict["{DOMAIN}/basis/shared/hmr.py"] = "./basis/shared/hmr.py"

    
    for i, m in enumerate(request.app._component_routes, 1):
        #print(f"* Mount Point: '{m.path}' (Name: '{m.name}')")
        # The directory path is stored in route.app.directory
        #print(f"  Serving directory: '{Path(m.app.directory).absolute()}'")
        
        cdir_n_label = '{' + f'COMPONENTS_DIR_{i}' + '}'
        mount_path = m.path   # mount path
        c_dir = Path(m.app.directory).absolute()
        files_dict[cdir_n_label] = str(Path("{DOMAIN}") / str(mount_path))


        for f in itertools.chain(c_dir.glob("*.py"), c_dir.glob("**/*.py")):
            subdir = f.parent
            subdir_rel_to_cdir = subdir.relative_to(c_dir)
            component_file = str(Path(cdir_n_label) / subdir_rel_to_cdir / f.name)

            files_dict[component_file] = "." + os.path.join(*[part for part in Path(mount_path).parts], str(subdir_rel_to_cdir / f.name))

            if f.name == "__init__.py":
                # get the name of the package (parent folder name)
                css_file = (f.parent / f.parent.name).with_suffix(".css")
                html_file = (f.parent / f.parent.name).with_suffix(".html")
            else:
                css_file = f.with_suffix(".css")
                html_file = f.with_suffix(".html")

            component_assets:list[Path] = [css_file, html_file]
                    
            for asset in component_assets:
                if asset.exists():
                    asset_file = str(Path(cdir_n_label) / subdir_rel_to_cdir / asset.name)
                    files_dict[asset_file] = "." + os.path.join(*[part for part in Path(mount_path).parts], str(subdir_rel_to_cdir / asset.name))


    return JSONResponse({
        "files": files_dict,
        "interpreter": "pyscript/pyodide/pyodide.mjs"
    })


class HMRManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.active_connections.remove(connection)

class Basis(FastAPI, DBAppMixin):
    
    _component_dirs = []
    _component_routes = []
    hmr_manager = HMRManager()

    def include_offline_pyscript(self, mount_path:str="/pyscript"):
        pyscript_mount = Mount(mount_path, StaticFiles(packages=[("basis", "static/pyscript")]), name="pyscript")
        self.routes.append(pyscript_mount)
    
    def include_pyscript_json(self, mount_path:str="/pyscript.json"):
        self.add_route(mount_path, pyscript_json, methods=['get'])

    def include_components_dir(self, mount_path:str, dir_path:str, name:str):

        m = Mount(mount_path, StaticFiles(directory=dir_path), name=name)
        
        self.routes.append(m)
        self._component_routes.append(m)

        # HMR WebSocket endpoint
        @self.websocket("/ws/hmr")
        async def hmr_websocket_endpoint(websocket: WebSocket):
            await self.hmr_manager.connect(websocket)
            try:
                while True:
                    await websocket.receive_text() # Just keep connection alive
            except WebSocketDisconnect:
                self.hmr_manager.disconnect(websocket)
            except Exception:
                self.hmr_manager.disconnect(websocket)

    async def _start_file_watcher(self):
        """Simple poller to watch for file changes and broadcast HMR events."""
        mtimes = {}
        
        # Initial scan
        watch_dirs = [Path(m.app.directory).absolute() for m in self._component_routes]
        # Also watch the basis package itself for core changes? Maybe too much.
        
        while True:
            for watch_dir in watch_dirs:
                for ext in ["*.py", "*.html", "*.css"]:
                    for f in watch_dir.glob(f"**/{ext}"):
                        mtime = f.stat().st_mtime
                        if f in mtimes and mtimes[f] < mtime:
                            logger.info(f"HMR: File changed: {f.name}")
                            # Determine type and relative path
                            rel_path = f.relative_to(watch_dir)
                            await self.hmr_manager.broadcast({
                                "type": "hmr",
                                "file": str(rel_path),
                                "ext": f.suffix.lstrip("."),
                                "content": f.read_text()
                            })
                        mtimes[f] = mtime
            await asyncio.sleep(0.5)

    def start_file_watcher(self):
        asyncio.create_task(self._start_file_watcher())

    def run_with_hmr(self, host="127.0.0.1", port=8000):
        import uvicorn
        
        @self.on_event("startup")
        async def startup_event():
            asyncio.create_task(self._start_file_watcher())
            
        uvicorn.run(self, host=host, port=port)

    def run_without_hmr(self, host="127.0.0.1", port=8000):
        import uvicorn
            
        uvicorn.run(self, host=host, port=port)

    def include_framework(self):
        components_route = None
        shared_route = None

        for r in self.routes:
            if r.name == 'basis_components':
                components_route = r
            elif r.name == 'basis_shared':
                shared_route = r

        if not components_route:
            components_mount = Mount("/basis/components", StaticFiles(packages=[('basis', 'components')]), name='basis_components')
            self.routes.append(components_mount)

        if not shared_route:
            shared_mount = Mount("/basis/shared", StaticFiles(packages=[('basis', 'shared')]), name='basis_shared')
            self.routes.append(shared_mount)

    def include_ui_components(self):

        spec = importlib.util.find_spec("basis.ui")
        
        ui_path = Path(spec.origin).parent

        ui_mount = Mount("/basis/ui/", StaticFiles(directory=ui_path), name='basis_ui')

        self.routes.append(ui_mount)
        self._component_routes.append(ui_mount)

    def include_ssr_page(
        self,
        path: str,
        component_cls,
        entry_module: str = "/main.py",
        title: str = "Basis App",
        stores: dict | None = None,
        name: str | None = None,
        pyscript_src: str = "/pyscript"
    ):
        """
        Register a GET route that returns a fully server-rendered HTML page.

        Parameters
        ----------
        path:
            The URL path, e.g. "/" or "/home".
        component_cls:
            A ServerComponent subclass to render for this route.
        entry_module:
            URL path for the PyScript entry .py file.
        title:
            HTML <title> for the page.
        stores:
            Dict of {name: Store instance} to embed as initial-state JSON.
        name:
            Optional route name.
        """
        from basis.server.ssr import render_page, render_page_async

        async def _ssr_handler(request: Request):

            from basis.shared.context import base_url_var
            
            # Set the base URL context for this request lifecycle
            token = base_url_var.set(str(request.base_url))
            try:
                html = await render_page_async(
                    component_cls,
                    title=title,
                    stores=stores or {},
                    entry_module=entry_module,
                    pyscript_src=pyscript_src,
                    pyscript_json_url=str(request.url_for('pyscript_json')),
                )
                return HTMLResponse(html)
            finally:
                base_url_var.reset(token)

        self.add_route(path, _ssr_handler, methods=['GET'], name=name)


    def bootstrap(self, include_offline_pyscript=True):
        self.include_offline_pyscript()
        self.include_pyscript_json()
        self.include_framework()
        self.include_ui_components()

    def entrypoint(self, component_cls=None, *, pyscript_src=ONLINE_PYSCRIPT):
        """
        Configure the app with bootstrap, component routes, and SSR page in one go.
        Returns the component class so it can be used as a decorator.
        """
        
        #handle optional argument case (i.e. @entrypoint decorator with no args)
        if component_cls is None:
            return functools.partial(self.entrypoint, pyscript_src=pyscript_src)


        self.bootstrap()

        # Detect where the component was defined to serve that directory
        try:
            component_file = Path(inspect.getfile(component_cls)).absolute()
        except (TypeError, OSError):
            # Fallback to the file that called entrypoint()
            caller_frame = inspect.stack()[1]
            component_file = Path(caller_frame.filename).absolute()
        
        app_dir = component_file.parent
        entry_module = f"/{component_file.name}"
        
        # Register the main SSR page
        print("including ssr page at /")
        self.include_ssr_page("/", component_cls, entry_module=entry_module, pyscript_src=pyscript_src)

        self.state.entry_module = entry_module
        self.state.pyscript_src = pyscript_src

        # Serve the application directory so PyScript can find the code
        self.include_components_dir("/", str(app_dir), name="app_root")

        return self

    def serve(self, component_cls, port=8000, **kwargs):
        """
        Bootstrap, register, and run a Basis app with HMR.
        """
        self.component(component_cls, **kwargs)

        # Print startup info
        import inspect
        from pathlib import Path
        try:
            component_file = Path(inspect.getfile(component_cls)).absolute()
        except:
            component_file = Path.cwd()

        print(f"\n🚀 Basis app starting at http://localhost:{port}")
        print(f"📦 Entry module: /{component_file.name}")
        print(f"🏠 App directory: {component_file.parent}\n")

        self.run_without_hmr(port=port)
        

class BasisAPIRouter(APIRouter):
    def component(self, cls):

        print(f"declaring {cls} is a component with a filename {cls.__file__}!")
        return cls
