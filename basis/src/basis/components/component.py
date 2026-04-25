from string import Formatter
from dataclasses import dataclass
from functools import wraps, partial
import inspect
import json
from pathlib import Path

try:
    from pyscript import window, document, ffi, fetch

    PYSCRIPT = True
    
except ImportError:

    PYSCRIPT = False

from basis.shared.bindings import Binding, SelfBinding, TextBinding, \
    AttributeBinding, SelfAttributeBinding, ModelBinding, EventBinding, IfBinding, \
    ChildBinding, LoopBinding, KeyedLoopBinding, SlotBinding, \
    safe_eval, safe_format, safe_format_with_stores, \
    extract_dependencies, ALLOWED_BUILTINS, Refrain, \
    _process_event_attr_bindings, _process_standard_attr_bindings, \
    _process_text_bindings, _process_self_attr_bindings

from basis.shared.store import Store
from basis.shared.base_component import BaseComponent

def client(func):

    @wraps(func)
    def wrapper(*args, **kwargs):
        if PYSCRIPT:
            return func(*args, **kwargs)

    return wrapper


class Refrain:
    def __init__(self, component):
        self.__dict__['inner_dict'] = {}
        self.__dict__['component'] = component

    def __enter__(self):
        return self
    
    def __setattr__(self, name, value):
        self.inner_dict[name] = value

    def __exit__(self, exc_type, exc_val, exc_tb):

        inner_dict = self.inner_dict

        for k, v in inner_dict.items():
            self.component.__dict__[k] = v
        
        #print(f"inner_dict in Refrain of {self.component}: ", inner_dict)

        if len(inner_dict) > 0:
            self.component.react([k for k in inner_dict.keys()])


class Component(BaseComponent):

    # _registry = {} defined on BaseComponent
    _instance_registry = {}
    _pending_subscriptions = {}

    S = Store._registry
    C = _instance_registry

    @classmethod
    def _initialize_blueprint(cls):
        ###Client
        init_template = cls._create_element('template')
        init_template.innerHTML = cls.__templatestr__
        setattr(cls, "__blueprint__", init_template)
    
    @classmethod
    @client
    def clone_blueprint(cls):
        cloned = document.importNode(cls.__blueprint__, True)
        return cloned
    
    @property
    @client
    def __template__(self):
        if '_template' not in self.__dict__:
            cloned_blueprint = self.__class__.clone_blueprint()
            cloned_content = cloned_blueprint.content
            self.__dict__['_template'] = cloned_content
        return self.__dict__['_template']

    @classmethod
    def _register_custom_element(cls):
        if "-" in cls.__tag__ \
        and cls.__tag__ not in cls._registry:
            templatestr = cls.__templatestr__
            custom_element = window.CustomElementFactory(ffi.to_js({'__templatestr__': templatestr, 'pyClassName': cls.__name__, '__shadow__': getattr(cls, '__shadow__', False)}))
            window.customElements.define(cls.__tag__, custom_element)
            setattr(cls, 'custom_element', custom_element)
    
    @classmethod
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        
        #client
        cls._register_custom_element()

    def __init__(self):
        super().__init__()

    @client
    def _get_nodes(self, element=None):

        if not element:
            element_to_walk = self.__template__
        else:
            element_to_walk = element

        walker = document.createTreeWalker(element_to_walk, window.NodeFilter.SHOW_ELEMENT | window.NodeFilter.SHOW_TEXT)

        nodes = []
        current_node = walker.nextNode()
        while current_node:
            nodes.append(current_node)
            current_node = walker.nextNode()

        return nodes

    @client
    def _create_comment(self, comment_text):
        return document.createComment(comment_text)
    
    @client
    def _create_document_fragment(self):
        return document.createDocumentFragment()

    @classmethod
    def _create_element(cls, tag):
        return document.createElement(tag)

    @client
    def _create_function_proxy(self, f):
        return ffi.create_proxy(f)

    @client   
    def _create_update_handler(self, f, input_type):
        handler = super()._create_update_handler(f, input_type)
        return self._create_function_proxy(handler)


    @classmethod
    def mount_app_ssr(cls, container, replace=False):
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
                for tag, component_cls in cls._registry.items():
                    if component_cls.__name__ == py_class_name:
                        print(f"Hydrating {py_class_name} via basis:hydrate event")
                        component_cls.hydrate(element)
                        return
                print(f"Warning: No Component found for '{py_class_name}' during hydration")

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
        super(Component, new_instance).__init__()
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
                