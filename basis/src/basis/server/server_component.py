import copy

from basis.shared.bindings import SelfBinding
from basis.shared.store import Store
from basis.shared.base_component import BaseComponent
from basis.shared.element import Element, ElementString, Comment, ServerFragment

from basis.server.tree_builder import html_to_element_tree



class ServerComponent(BaseComponent):

    # _registry = {} defined on BaseComponent
    _instance_registry = {}
    _pending_subscriptions = {}

    S = Store._registry
    C = _instance_registry

    #@server
    @classmethod
    def _initialize_blueprint(cls):
        ###Server
        blueprint_tree = html_to_element_tree(cls.__templatestr__)
        setattr(cls, "__blueprint__", blueprint_tree)
    
    #@server
    @classmethod
    def clone_blueprint(cls):
        raw = cls.__blueprint__
        # blueprint is the builder dict; 'component' key holds the root Element
        root_element = raw['component']
        return copy.deepcopy(root_element)

    #@server
    @property
    def __template__(self) -> ServerFragment:
        """Return a ServerFragment wrapping the root Element.

        Mirrors the client where __template__ is the DocumentFragment (.content)
        of the cloned <template> element.  The fragment is consumed (emptied) by
        the first Element.appendChild() call in mount(), so any later call (e.g.
        from _bind_node) is a silent no-op — identical to client behaviour.
        """
        if '_template' not in self.__dict__:
            root = self.__class__.clone_blueprint()
            self.__dict__['_template'] = ServerFragment(root)
        return self.__dict__['_template']
    
    def __init__(self):
        super().__init__()

    #@server
    def _get_nodes(self, element=None):
        
        nodes = []
        
        if element:
            for d in element.descendants:
                nodes.append(d)

            return nodes

        else:
            if hasattr(self, "_nodes"):
                return self._nodes
            else:
                # Iterate directly over template.descendants; ServerFragment
                # correctly yields the descendants of its children.
                template = self.__template__
                for d in template.descendants:
                    nodes.append(d)
        
                self.__dict__['_nodes'] = nodes

                return nodes
    
    #@server
    def _create_comment(self, comment_text, parent=None):
        return Comment(data=comment_text, parent=parent)
    
    #@server
    def _create_document_fragment(self):
        return ServerFragment(root=None)

    #@server
    @classmethod
    def _create_element(cls, tag):
        element = Element(tag, attrs={}, children=[])
        return element

    def fill_slots(self, container):
        if not self.has_slots():
            # No slots in this component — nothing was moved, nothing to clear.
            return

        super().fill_slots(container)

        # Server-side only: after all light-DOM children have been moved into
        # their slot positions inside the component's own template, clear the
        # container's children list so they are not rendered a second time as
        # direct children of the host element (e.g. <ui-accordion>).
        #
        # On the client the browser does this automatically: once slot
        # distribution runs, the original host children are no longer rendered
        # at their original position.  We must replicate that here.
        if isinstance(container, Element):
            container.children = []

    @classmethod
    def mount_app_ssr_old(cls, container, replace=False):
        """
        Entry point for SSR pages.

        Checks whether the container already holds server-rendered content
        (identified by data-basis-component markers). If so, calls .hydrate()
        on the matching Component subclass; otherwise falls back to .mount_app().

        Also registers a document-level listener for 'basis:hydrate' events
        fired by CustomElementFactory when custom elements with SSR content
        are upgraded by the browser.
        """
        # Register the global SSR hydration event listener so that nested
        # custom elements deferred by the browser emit their hydrate events
        # and get picked up here.
        @client
        def _register_hydration_listener():
            def _on_hydrate(event):
                py_class_name = event.detail.pyClassName
                element = event.detail.element
                for tag, component_cls in self.__class__._registry.items():
                    if component_cls.__name__ == py_class_name:
                        print(f"Hydrating {py_class_name} via basis:hydrate event")
                        component_cls.hydrate(element)
                        return
                print(f"Warning: No Component found for '{py_class_name}' during hydration")
            
            #client
            document.addEventListener('basis:hydrate', ffi.create_proxy(_on_hydrate))

        _register_hydration_listener()

        # Check if the container's first data-basis-component element matches cls
        ssr_root = None
        try:
            ssr_root = container.querySelector('[data-basis-component]')
        except Exception:
            pass

        if ssr_root is not None:
            py_class_name = ssr_root.getAttribute('data-basis-component')
            if py_class_name == cls.__name__:
                new_instance = cls.hydrate(ssr_root.parentElement or ssr_root)
                return new_instance

        # Fallback: regular SPA mount
        return cls.mount_app(container, replace)

    @classmethod
    def hydrate(cls, container, **attributes):

        """
        Attach Basis reactivity to an existing server-rendered DOM node.

        Unlike mount(), this method does NOT insert any new nodes — it binds
        against what is already in the live DOM (placed there by SSR).

        Parameters
        ----------
        container:
            The custom-element host node (e.g. <my-sidebar>) whose
            firstElementChild is the pre-rendered component root.
        attributes:
            Initial attribute values to set before building bindings.
        """
        print(f"hydrate: starting hydration of {cls} against existing DOM")
        new_instance = cls.__new__(cls)
        # Manually call super() __init__ to set up __bindings__ / __fields__
        super(cls, new_instance).__init__()
        new_instance.__dict__['_subscriptions'] = []

        if attributes:
            new_instance.__dict__.update(attributes)

        # Point _template at the existing live DOM root (firstElementChild of
        # the custom-element host, which is the server-rendered component root).
        live_root = container.firstElementChild or container
        new_instance.__dict__['_template'] = cls._create_element('template')
        new_instance.__dict__['_template'].content.appendChild(live_root)

        # Bootstrap SelfBinding from the live root
        new_instance.__dict__['__bindings__'].append(
            SelfBinding(component_instance=new_instance, node=live_root)
        )

        @client
        def _finish_hydration(inst):
            inst.__init_bindings__()
            inst.__init_fields__()
            with inst.refrain() as refrained:
                for k, v in attributes.items():
                    setattr(refrained, k, v)

        _finish_hydration(new_instance)

        print(f"hydrate: finished hydration of {cls}")
        return new_instance
        

