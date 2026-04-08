from pathlib import Path
from fastapi import FastAPI, APIRouter, Request, WebSocket, WebSocketDisconnect
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from urllib.parse import urljoin
import logging
import itertools
import importlib.util
import os

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

    #add store
    files_dict["{DOMAIN}/basis/shared/store.py"] = "./basis/shared/store.py"
    
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


class StoreManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            await connection.send_json(message)

class Basis(FastAPI):
    
    _component_dirs = []
    _component_routes = []

    def include_offline_pyscript(self, mount_path:str="/pyscript"):
        pyscript_mount = Mount(mount_path, StaticFiles(packages=[("basis", "static/pyscript")]), name="pyscript")
        self.routes.append(pyscript_mount)
        
    def include_components_dir(self, mount_path:str, dir_path:str, name:str):

        static_route = None
        shared_route = None

        for r in self.routes:
            if r.name == 'basis_components':
                static_route = r
            elif r.name == 'basis_shared':
                shared_route = r

        if not static_route:
            static_mount = Mount("/basis/components", StaticFiles(packages=[('basis', 'components')]), name='basis_components')
            self.routes.append(static_mount)

        if not shared_route:
            shared_mount = Mount("/basis/shared", StaticFiles(packages=[('basis', 'shared')]), name='basis_shared')
            self.routes.append(shared_mount)

        m = Mount(mount_path, StaticFiles(directory=dir_path), name=name)
        
        self.routes.append(m)
        self._component_routes.append(m)


        self.add_route("/pyscript.json", pyscript_json, methods=['get'])


        # Store sync mechanism over WebSockets
        '''
        self.store_manager = StoreManager()
        
        @self.websocket("/ws/store")
        async def store_websocket_endpoint(websocket: WebSocket):
            await self.store_manager.connect(websocket)
            try:
                while True:
                    data = await websocket.receive_json()
                    
                    # You could validate with schemas here:
                    # from basis.shared.schemas import StoreAction
                    # action = StoreAction(**data)
                    
                    # For demonstration, broadcast directly
                    await self.store_manager.broadcast(data)
            except WebSocketDisconnect:
                self.store_manager.disconnect(websocket)
        '''


    def include_ui_components(self):

        spec = importlib.util.find_spec("basis.ui")
        
        ui_path = Path(spec.origin).parent

        ui_mount = Mount("/basis/ui/", StaticFiles(directory=ui_path), name='basis_ui')

        self.routes.append(ui_mount)
        self._component_routes.append(ui_mount)


class BasisAPIRouter(APIRouter):
    def component(self, cls):

        print(f"declaring {cls} is a component with a filename {cls.__file__}!")
        return cls
