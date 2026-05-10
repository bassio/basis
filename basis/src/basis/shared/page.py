from basis.shared.component import Component

class Page(Component):
    title: str = "Basis App"
    stores: dict | None = None
    entry_module: str = "/main.py"
    pyscript_src: str = "/pyscript"
    pyscript_json_url: str = "/pyscript.json"

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