from string import Formatter
import copy
import inspect

from basis.shared.bindings import (
    Binding, SelfBinding, TextBinding, AttributeBinding, ModelBinding,
    EventBinding, IfBinding, ChildBinding, LoopBinding, KeyedLoopBinding, SlotBinding,
    safe_eval, safe_format, extract_dependencies, ALLOWED_BUILTINS
)
from basis.server.components.element import Element, ElementString, html_to_element_tree
from basis.shared.base_component import BaseComponent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def deep_clone_element(node):
    """Recursively deep-copy an Element / ElementString tree."""
    if isinstance(node, ElementString):
        return ElementString(value=node.value, parent=None)
    elif isinstance(node, Element):
        cloned_children = []
        cloned = Element(
            tag=node.tag,
            attrs=dict(node.attrs),
            children=cloned_children,
            void_=node.void_,
            _detached=node._detached,
            _if_expr=node._if_expr,
        )
        for child in node.children:
            cloned_child = deep_clone_element(child)
            if isinstance(cloned_child, ElementString):
                cloned_child.parent = cloned
            elif isinstance(cloned_child, Element):
                cloned_child.parent = cloned
            cloned_children.append(cloned_child)
        return cloned
    else:
        # Fallback: plain string or unknown
        return node


# ---------------------------------------------------------------------------
# ServerComponent
# ---------------------------------------------------------------------------

class ServerComponent(BaseComponent):
    _registry = {}
    tag: str

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        if hasattr(cls, 'template'):
            if inspect.isfunction(cls.template):
                templatestr = cls.template.__doc__
            elif isinstance(cls.template, str):
                templatestr = cls.template
            else:
                return
        elif cls.__doc__:
            templatestr = cls.__doc__
        else:
            return

        setattr(cls, "__templatestr__", templatestr)

        blueprint_tree = html_to_element_tree(templatestr)
        setattr(cls, "__blueprint__", blueprint_tree)

        if hasattr(cls, 'tag') and "-" in cls.tag:
            tag = cls.tag
        else:
            tag = cls.__name__

        cls._registry[tag] = cls

    @classmethod
    def clone_blueprint(cls):
        """Return a fresh deep-copy of the root Element from the blueprint."""
        raw = cls.__blueprint__
        # blueprint is the builder dict; 'component' key holds the root Element
        root_element = raw['component']
        return deep_clone_element(root_element)

    @property
    def __template__(self):
        """Return the cached cloned Element tree for this instance."""
        if '_template' not in self.__dict__:
            self.__dict__['_template'] = self.__class__.clone_blueprint()
        return self.__dict__['_template']

    @property
    def __element__(self):
        """Return the root Element node (equivalent to firstElementChild on client)."""
        for binding in self.__dict__.get('__bindings__', []):
            if isinstance(binding, SelfBinding):
                return binding.node
        return None

    def __init__(self):
        super().__init__()
        self.__init_bindings__()
        self.__init_fields__()

    def __init_bindings__(self):
        bindings = []
        fields = []

        root_element = self.__template__

        # Register a SelfBinding for the root element
        bindings.append(SelfBinding(component_instance=self, node=root_element))

        formatter = Formatter()

        for node in root_element.descendants:
            if node is root_element:
                # Still process root element's attributes below
                pass

            if isinstance(node, Element):
                element = node
                element_attrs = list(element.attrs.keys())
                event_attrs = [a for a in element_attrs if a.startswith("on")]
                other_attrs = [a for a in element_attrs if not a.startswith("on")]

                # ── child components ───────────────────────────────────────
                if '-' in element.tag:
                    tag = element.tag.lower()
                    if tag in self.__class__._registry:
                        childcomponent_py = self.__class__._registry[tag]
                        bindings.append(ChildBinding(
                            component_instance=self,
                            node=element,
                            childclass=childcomponent_py,
                        ))

                # ── slot ──────────────────────────────────────────────────
                if element.tag.lower() == 'slot':
                    slot_name = element.attrs.get('name')
                    is_default = not slot_name
                    bindings.append(SlotBinding(
                        component_instance=self,
                        node=element,
                        name=slot_name,
                        is_default=is_default,
                    ))

                # ── event bindings ────────────────────────────────────────
                for event_attr in event_attrs:
                    event_attr_value = element.attrs[event_attr]
                    if event_attr_value.startswith("{") and event_attr_value.endswith("}"):
                        event_attr_value = event_attr_value.strip("{}")
                        bindings.append(EventBinding(
                            component_instance=self,
                            node=element,
                            event=event_attr,
                            target_fn=event_attr_value,
                        ))
                        fields.append(event_attr_value)

                # ── if binding ────────────────────────────────────────────
                if 'if' in other_attrs:
                    if_expr = element.attrs['if']
                    if_expr_clean = if_expr.removeprefix("{").removesuffix("}")
                    fieldnames = extract_dependencies(if_expr, ALLOWED_BUILTINS)
                    bindings.append(IfBinding(
                        component_instance=self,
                        node=element,
                        expr=if_expr_clean,
                        anchor=None,   # no JS anchor on server
                        is_visible=True,
                        fields=fieldnames,
                    ))
                    fields += fieldnames

                # ── model (bind) binding ──────────────────────────────────
                if 'bind' in other_attrs:
                    bind_attr_value = element.attrs['bind']
                    fieldnames = [
                        fname for _, fname, _, _ in formatter.parse(bind_attr_value)
                        if fname is not None
                    ]
                    if len(fieldnames) == 1:
                        field = fieldnames[0]
                        bindings.append(ModelBinding(
                            component_instance=self,
                            node=element,
                            field=field,
                        ))
                        fields.append(field)

                # ── loop binding ──────────────────────────────────────────
                if 'for' in other_attrs:
                    for_attr_value = element.attrs.get('for', '')
                    in_attr_value = element.attrs.get('in', '').strip("{}")
                    has_expr = any(
                        fname is not None
                        for _, fname, _, _ in formatter.parse(for_attr_value)
                    )
                    if has_expr:
                        fieldnames = extract_dependencies(for_attr_value, ALLOWED_BUILTINS)
                        bindings.append(LoopBinding(
                            component_instance=self,
                            node=element,
                            clone=deep_clone_element(element),
                            parent=getattr(element, 'parent', None),
                            collection=in_attr_value,
                            item=for_attr_value,
                        ))
                        fields += fieldnames

                # ── attribute bindings ────────────────────────────────────
                for other_attr in other_attrs:
                    other_attr_value = element.attrs[other_attr]

                    # Handle boolean {attr} style
                    if other_attr.startswith("{") and other_attr.endswith("}"):
                        other_attr_no_braces = other_attr.strip("{}")
                        other_attr_isboolean = True
                        # Rename in the attrs dict
                        del element.attrs[other_attr]
                        element.attrs[other_attr_no_braces] = other_attr_value
                    else:
                        other_attr_no_braces = other_attr
                        other_attr_isboolean = False

                    has_expr = any(
                        fname is not None
                        for _, fname, _, _ in formatter.parse(str(other_attr_value))
                    )
                    if has_expr:
                        fieldnames = extract_dependencies(str(other_attr_value), ALLOWED_BUILTINS)
                        bindings.append(AttributeBinding(
                            component_instance=self,
                            node=element,
                            attr=other_attr_no_braces,
                            content=str(other_attr_value),
                            fields=fieldnames,
                            is_boolean=other_attr_isboolean,
                        ))
                        fields += fieldnames

            elif isinstance(node, ElementString):
                # Skip text inside <style> blocks
                if node.parent and node.parent.tag.lower() == 'style':
                    continue

                text_content = str(node)
                has_expr = any(
                    fname is not None
                    for _, fname, _, _ in formatter.parse(text_content)
                )
                if has_expr:
                    fieldnames = extract_dependencies(text_content, ALLOWED_BUILTINS)
                    bindings.append(TextBinding(
                        component_instance=self,
                        node=node,
                        content=text_content,
                        fields=fieldnames,
                    ))
                    fields += fieldnames

        self.__dict__['__bindings__'] = bindings
        self.__dict__['__fields__'] = list(set(fields))

    def __init_fields__(self):
        cls = self.__class__

        fields_on_class = [
            attr for attr in self.__fields__
            if attr not in self.__dict__
            and attr in cls.__dict__
            and not inspect.isfunction(getattr(cls, attr))
        ]

        for field in fields_on_class:
            self.__dict__[field] = cls.__dict__[field]

        if fields_on_class:
            self.react(fields_on_class)

    def react(self, names):
        text_bindings = [tb for tb in self.__bindings__ if isinstance(tb, TextBinding)]
        attr_bindings = [ab for ab in self.__bindings__ if isinstance(ab, AttributeBinding)]
        model_bindings = [mb for mb in self.__bindings__ if isinstance(mb, ModelBinding)]
        if_bindings = [ib for ib in self.__bindings__ if isinstance(ib, IfBinding)]

        for name in names:
            # ── model bindings ─────────────────────────────────────────────
            for mb in model_bindings:
                if mb.field == name:
                    val = safe_eval(name, self.__dict__, ALLOWED_BUILTINS)
                    input_type = mb.node.attrs.get('type', 'text')
                    if input_type == 'checkbox':
                        if val:
                            mb.node.attrs['checked'] = 'checked'
                        else:
                            mb.node.attrs.pop('checked', None)
                    else:
                        mb.node.attrs['value'] = str(val) if val is not None else ""

            # ── text bindings ──────────────────────────────────────────────
            for tb in text_bindings:
                if name in tb.fields:
                    tb.node.value = safe_format(tb.content, self.__dict__, ALLOWED_BUILTINS)

            # ── attribute bindings ─────────────────────────────────────────
            for ab in attr_bindings:
                if name in ab.fields:
                    final_val = safe_format(ab.content, self.__dict__, ALLOWED_BUILTINS)
                    if ab.is_boolean:
                        if final_val:
                            ab.node.attrs[ab.attr] = ab.attr
                        else:
                            ab.node.attrs.pop(ab.attr, None)
                    else:
                        ab.node.attrs[ab.attr] = final_val

            # ── if bindings ────────────────────────────────────────────────
            for ib in if_bindings:
                if name in ib.fields:
                    expr_eval = bool(safe_eval(ib.expr, self.__dict__, ALLOWED_BUILTINS))
                    ib.is_visible = expr_eval
                    # Mark the Element node so __html__() emits a comment
                    ib.node._detached = not expr_eval
                    ib.node._if_expr = ib.expr

    @classmethod
    def render(cls, **kwargs):
        """
        Server-side render: create an instance, apply kwargs (triggering react()),
        inject the `data-basis-component` hydration marker, and return an HTML string.
        """
        instance = cls()

        if kwargs:
            for k, v in kwargs.items():
                setattr(instance, k, v)

        root = instance.__element__
        if root is not None:
            root.attrs['data-basis-component'] = cls.__name__

        return root.__html__() if root is not None else ""

    @classmethod
    def mount(cls, container, replace=False, **attributes):
        """Server-side mount: attach the rendered component tree into a container Element."""
        new_instance = cls()

        if attributes:
            for k, v in attributes.items():
                setattr(new_instance, k, v)

        self_element = new_instance.__element__

        print("*******************", self_element)

        if replace:
            container.replace_with(self_element)
        else:
            container.children.append(self_element)
            self_element.parent = container

        # Mount child components
        child_bindings = [b for b in new_instance.__bindings__ if isinstance(b, ChildBinding)]
        for binding in child_bindings:
            updated_attrs = dict(binding.node.attrs)
            binding.childclass.mount(binding.node, replace=True, **updated_attrs)

        # Mount statically declared nested children
        for nested_child in cls.get_nested_children():
            nested_child.mount(self_element, replace=False)

        return new_instance
