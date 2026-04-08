import re
from string import Formatter
from basis.shared.store import Store
from basis.components.component import Component, client, AttributeBinding

try:
    from pyscript import window, ffi, document
except ImportError:
    window = None
    ffi = None
    document = None

class RouterStore(Store):
    current_path: str = ""
    
    @client
    def __init__(self, name):
        super().__init__(name)
        if window:
            self.current_path = window.location.pathname
            
            def on_popstate(event):
                self.current_path = window.location.pathname
                
            window.addEventListener("popstate", ffi.create_proxy(on_popstate))
        
    @client
    def navigate(self, path: str):
        if window and path != self.current_path:
            window.history.pushState(None, "", path)
            self.current_path = path


class Route(Component):
    __tag__ = "basis-route"
    _route_registry = {}
    path: str = ""
    is_match: bool = False

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
        # Ensure we subscribe to router.current_path
        self.router = Component.S['router']
        self.router.subscribe(self, "current_path")
        # Trigger an initial check
        self.check_match()
        if self.is_match:
            matched_dict = self.path_matched_groups()
            print(self.__element__.innerHTML)

    def path_matched_groups(self):
        # Convert the {url_id} syntax to a named regex group (?P<name>...)
        # [^/]+ matches any character except a forward slash
        regex_pattern = re.sub(r'\{(\w+)\}', r'(?P<\1>[^/]+)', self.path)
        
        # Add anchors to ensure we match the full string, not just a substring
        regex_pattern = f"^{regex_pattern}$"

        # 3. Attempt the match
        match = re.match(regex_pattern, self.router.current_path)

        if match:
            return match.groupdict()
        else:
            return {}
        
    def check_match(self):
        # Convert the {url_id} syntax to a named regex group (?P<name>...)
        # [^/]+ matches any character except a forward slash
        regex_pattern = re.sub(r'\{(\w+)\}', r'(?P<\1>[^/]+)', self.path)
        
        # Add anchors to ensure we match the full string, not just a substring
        regex_pattern = f"^{regex_pattern}$"

        # 3. Attempt the match
        match = re.match(regex_pattern, self.router.current_path)
        
        if match:
            matched_groups = match.groupdict()
            print("YES MATCHED!!!", matched_groups, self.__bindings__, self.__fields__)
            print(self.__element__.innerHTML)

            with self.refrain() as refrained:
                for k, v in matched_groups.items():
                    if k not in self.__fields__:
                        self.__fields__.append(k)
                    setattr(self, k, v)
            
            self.is_match = True
                    
        else:
            self.is_match = False

        '''
        regex_pattern = ""
        keys = []
        for literal_text, fname, format_spec, conversion in Formatter().parse(self.path):
            regex_pattern += re.escape(literal_text)
            if fname is not None:
                regex_pattern += r"(?P<" + fname + r">[^/]+)"
                keys.append(fname)
        
        regex_pattern = "^" + regex_pattern + "$"
        match = re.match(regex_pattern, self.router.current_path)
        
        new_match = bool(match)
        if getattr(self, 'is_match', None) != new_match:
            self.is_match = new_match
            
        if new_match:
            for k, v in match.groupdict().items():
                if getattr(self, k, None) != v:
                    setattr(self, k, v)
        '''

    def react(self, names):
        if "$router.current_path" in names or "path" in names:
            self.check_match()
        super().react(names)


class Link(Component):
    __tag__ = "basis-link"
    href: str = ""
    
    def template(self):
        """
        <a href="{href}" onclick="{handle_click}">
            <slot></slot>
        </a>
        """
    
    @client
    def handle_click(self, event):
        event.preventDefault()
        router = Component.S['router']
        router.navigate(self.href)
