import re
from basis.shared.store import Store
from basis.shared.component import Component, IS_CLIENT, client

if IS_CLIENT:
    from pyscript import window, ffi
else:
    window = None
    ffi = None

class RouterStore(Store):
    current_path: str = ""
    
    def __init__(self, name):
        super().__init__(name)
        if window:
            self.current_path = window.location.pathname
            
            def on_popstate(event):
                self.current_path = window.location.pathname
                
            window.addEventListener("popstate", ffi.create_proxy(on_popstate))
        
    def navigate(self, path: str):
        if window and path != self.current_path:
            window.history.pushState(None, "", path)
            self.current_path = path


class Route(Component):
    __tag__ = "basis-route"
    _route_registry = {}
    path: str = ""
    is_match: bool = False
    exact: bool = True
    fallback: bool = False

    def __init__(self):
        super().__init__()

        # Ensure we subscribe to router.current_path
        Component.S['router'].subscribe(self, "current_path")
        self.__dict__['router'] = Component.S['router']

    @classmethod
    def initialize(cls, container, **kwargs):
        new_instance = super().initialize(container, **kwargs)
        Route._route_registry[new_instance.path] = new_instance
        return new_instance
 
    def template(self):
        """
        <div style="display: contents" if="{is_match}" >
            <slot></slot>
        </div>
        """

    @client
    def __init_bindings__(self):
        super().__init_bindings__()
        # Trigger an initial check
        self.check_match()

    @client
    def __init_fields__(self):
        super().__init_fields__()
        # Trigger an initial check
        if "path" in self.__fields__:
            self.__fields__.pop("path")

        #print("FALLBACK", type(self.fallback), self.fallback)

    def is_path_matching(self, current_path):
        if self.path == "*":
            return True
            
        regex_pattern = re.sub(r'\{(\w+)\}', r'(?P<\1>[^/]+)', self.path)
        regex_pattern = f"^{regex_pattern}"
        
        is_exact = self.exact
        if isinstance(is_exact, str):
            is_exact = is_exact.lower() != 'false'
            
        if is_exact:
            regex_pattern += "$"
            
        return bool(re.match(regex_pattern, current_path))

    def path_matched_groups(self):
        if self.path == "*":
            return {}
            
        regex_pattern = re.sub(r'\{(\w+)\}', r'(?P<\1>[^/]+)', self.path)
        regex_pattern = f"^{regex_pattern}"
        
        is_exact = self.exact
        if isinstance(is_exact, str):
            is_exact = is_exact.lower() != 'false'
            
        if is_exact:
            regex_pattern += "$"

        match = re.match(regex_pattern, self.router.current_path)

        if match:
            return match.groupdict()
        else:
            return {}
        
    def check_match(self):

        is_fallback = self.fallback

        if isinstance(is_fallback, str):
            is_fallback = is_fallback.lower() == 'true'

        if self.path == "*":
            match = True  # Used to denote a structural match
        else:
            regex_pattern = re.sub(r'\{(\w+)\}', r'(?P<\1>[^/]+)', self.path)
            regex_pattern = f"^{regex_pattern}"
            
            is_exact = self.exact
            if isinstance(is_exact, str):
                is_exact = is_exact.lower() != 'false'
                
            if is_exact:
                regex_pattern += "$"
                
            match = re.match(regex_pattern, self.router.current_path)

        if match:
            # If this is a fallback route, we must check if any standard route matches
            if is_fallback:
                for path, route in Route._route_registry.items():
                    #print("path, route", path, route)
                    if route is self:
                        continue
                    
                    route_fallback = route.fallback
                    if isinstance(route_fallback, str):
                        route_fallback = route_fallback.lower() == 'true'
                        
                    if not route_fallback and route.is_path_matching(self.router.current_path):
                        self.is_match = False
                        return

            if self.path != "*":
                matched_groups = match.groupdict()
                with self.refrain() as refrained:
                    for k, v in matched_groups.items():
                        if k not in self.__fields__:
                            self.__fields__.append(k)
                        setattr(self, k, v)
        
            self.is_match = True
            
        else:
            self.is_match = False

    def react(self, names):
        if "$router.current_path" in names or "path" in names:
            self.check_match()
        super().react(names)


class Link(Component):
    __tag__ = "basis-link"
    href: str = ""
    exact: bool = True
    active_class: str = ""
    active: bool = False

    def __init__(self):
        super().__init__()
        Component.S['router'].subscribe(self, "current_path")
        self.__dict__['router'] = Component.S['router']

    @client
    def __init_bindings__(self, root_element=None):
        super().__init_bindings__(root_element)
        self.check_active()

    def check_active(self):
        # Allow string 'false' from html attribute
        is_exact = self.exact
        if isinstance(is_exact, str):
            is_exact = is_exact.lower() != 'false'
            
        if is_exact:
            is_active = self.href == self.router.current_path
        else:
            is_active = bool(self.href) and self.router.current_path.startswith(self.href)
            
        if self.active != is_active:
            self.active = is_active
        
            self.active_class = "active" if self.active else ""

    def react(self, names):
        if "$router.current_path" in names or "href" in names:
            self.check_active()
        super().react(names)

    def template(self):
        """
        <a href="{href}" onclick="{handle_click}" class="{active_class}">
            <slot></slot>
        </a>
        """
    
    @client
    def handle_click(self, event):
        event.preventDefault()
        self.router.navigate(self.href)
        self.check_active()
