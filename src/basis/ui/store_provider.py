import asyncio
from basis.shared.store import Store, ReactiveCollection
from basis.shared.component import Component, client, IS_CLIENT

try:
    from pyscript import fetch
except ImportError:
    pass

class StoreProvider(Component):
    __tag__ = "store-provider"
    
    url = ""
    name = ""
    target = None
    _last_fetched_url = ""

    def __setattr__(self, key, value):
        old_value = getattr(self, key, None)

        print(f"*****In __setattr__ for StoreProvider: {key}, {value}")
        
        super().__setattr__(key, value)
        
        # When 'url' changes dynamically via a binding, trigger a new fetch
        if key == "url" and value != old_value and value:
            if IS_CLIENT:
                asyncio.create_task(self.fetch_data())

    @classmethod
    def initialize(cls, container, **kwargs):
        name = kwargs.get("name", "")
        if name and name not in Store._registry:
            # Create store synchronously so children can bind to it
            Store(name)
            
        instance = super().initialize(container, **kwargs)
        
        # Schedule the fetch task if on client
        if IS_CLIENT:
            asyncio.create_task(instance.fetch_data())
        else:
            pass
            
        return instance

    async def server_load(self):
        if not self.url or not self.name or "{" in self.url:
            return
            
        url = self.url
        if url.startswith("/"):
            from basis.shared.context import get_base_url
            base_url = get_base_url()
            if base_url:
                url = base_url.rstrip("/") + url
            else:
                # Fallback for local development or if context is missing
                url = f"http://127.0.0.1:8000{url}"
            
        def _fetch():
            import urllib.request
            import json
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req) as response:
                return json.loads(response.read().decode())
                
        try:
            data = await asyncio.to_thread(_fetch)
            store = Store._registry.get(self.name)
            if store:
                if self.target:
                    if isinstance(data, list):
                        setattr(store, self.target, ReactiveCollection(data))
                    else:
                        setattr(store, self.target, data)
                elif isinstance(data, list):
                    setattr(store, "items", ReactiveCollection(data))
                else:
                    for k, v in dict(data).items():
                        setattr(store, k, v)
        except Exception as e:
            print(f"Server load failed for {self.name}: {e}")

    @client
    async def fetch_data(self):

        print(f"*****In fetch_data for url: {self.url}")
        
        if not self.url or not self.name:
            return

        if  "{" in self.url:
            return
                      
        if getattr(self, "_last_fetched_url", None) == self.url:
            return
            
        store = Store._registry.get(self.name)

        try:
            response = await fetch(self.url)
            data = await response.json()
            
            if store:
                if self.target:
                    if isinstance(data, list):
                        print("***Creating ReactiveCollection with target***")
                        setattr(store, self.target, ReactiveCollection(data))
                    else:
                        setattr(store, self.target, data)
                        pass
                elif isinstance(data, list):
                    setattr(store, "items", ReactiveCollection(data))
                else:
                    for k, v in dict(data).items():
                        setattr(store, k, v)
                        pass
                    
            self.__dict__["_last_fetched_url"] = self.url
            
        except Exception as e:
            print(f"Failed to fetch data for {self.name} from {self.url}: {e}")

    def style(self):
        """
        ui-store-provider {
            display: contents;
        }
        """

    def template(self):
        """
        <slot></slot>
        """
