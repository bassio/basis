from basis.shared.component import Component
from basis.shared.element import Element, ServerFragment, DocumentType

class Page(Component):
    doctype: DocumentType = DocumentType("html")
    title: str = "Basis App"
    entry_module: str = "/main.py"
    pyscript_src: str = "/pyscript"
    pyscript_json_url: str = "/pyscript.json"
    initial_state_json: str = "{}"

    @classmethod
    def load(cls):

        container = Element("html", {}, [])
        
        attributes = {"title": cls.title,
                      "entry_module": cls.entry_module,
                      "pyscript_src": cls.pyscript_src,
                      "pyscript_json_url": cls.pyscript_json_url,
                      "initial_state_json": cls.initial_state_json}

        instance = cls.mount(container, replace=False, **attributes)

        instance.__element__ = container
        
        return instance

    def head(self):
        """Override to add custom head content."""
        return ""

    def body(self):
        """Override to add main page content."""
        return ""

    def template(self):
        """
<html>
    <head>
        <meta charset="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>{title}</title>

        <!-- PyScript offline bundle -->
        <link rel="stylesheet" href="{pyscript_src}/core.css" />
        <script type="module" src="{pyscript_src}/core.js" onload="window.pyscript = this.module;"></script>
        
        <script src="./basis/components/component.js"></script>

        <!-- Basis SSR: initial store state for client hydration -->
        <script id="basis-initial-state" type="application/json">
            {initial_state_json}
        </script>
        
    </head>
    <body>
        <div id="basis-ssr-root">
            
        </div>
        <!-- PyScript entry point: mounts/hydrates the application -->
        <script type="py" src="{entry_module}" config="{pyscript_json_url}"></script>
    </body>
</html>
"""

    def render_full_page(self, initial_state_json="{}"):
        """
        Assembles the full HTML document with doctype.
        """
        self.initial_state_json = initial_state_json
        print(self.__fields__)
        return self.doctype.__html__() + "\n" + self.__element__.outerHTML
