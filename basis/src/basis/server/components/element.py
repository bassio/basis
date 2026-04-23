from bs4.builder import TreeBuilder
from dataclasses import dataclass, field

voids = {'area', 'base', 'br', 'col', 'command', 'embed', 'hr', 'img', 'input', 'keygen', 'link', 'meta', 'param', 'source', 'track', 'wbr', '!doctype'}

class Node(object):
    parent:Node|None = None

    @property
    def parentNode(self):
        if isinstance(self.parent, dict):
            return self.parent['component']
        print("parentNode", self, ":::", self.parent)
        return self.parent

    def after(self, *nodes):
        parent = self.parentNode
        print("inside after::", self, parent, parent.children)
        try:
            index = parent.children.index(self)
        except ValueError:
            # self is not currently in the parent's children list
            # (e.g. an IfBinding node that was removed); append at the end.
            print(f"after(): {self!r} not found in parent.children — appending at end")
            index = len(parent.children) - 1
        parent.children[index+1:index+1] = list(nodes)
        # Update parent references for inserted elements
        for n in nodes:
            if hasattr(n, 'parent'):
                n.parent = parent

    def remove(self):
        """Detach this node from its parent, mirroring browser node.remove()."""
        parent = self.parentNode
        if parent is None:
            return  # already detached — no-op, same as browser behaviour
        try:
            parent.children.remove(self)
        except ValueError:
            pass  # not in the list — treat as a no-op
        self.parent = None

@dataclass
class Comment(Node):
    parent:Element|None = None
    nodeName:str = field(default= "#comment", init=False, repr=False)
    data:str = field(default="")
    
    def __html__(self):
        return f"""<!--{self.data}-->"""

    def __str__(self):
        return self.__html__()

    @property
    def parentElement(self):
        return self.parentNode
        
    @property
    def descendants(self):
        return []

    def cloneNode(self, deep:bool=True):
        new_node = Comment(data=self.data, parent=self.parent)
        return new_node

@dataclass
class ElementString(Node):
    value:str
    nodeName:str = field(default= "#text", init=False, repr=False)
    parent:Element|None = None
    
    def wholeText(self):
        return self.value

    def get_value(self):
        return self.value
    
    def set_value(self, value):
        self.value = value

    textContent = property(get_value, set_value)
    
    def __html__(self):
        return self.value

    def __str__(self):
        return self.value
    
    def __repr__(self):
        return f'"{self.value}"'
        
    @property
    def parentElement(self):
        return self.parentNode
    
    @property
    def descendants(self):
        return []
    
    def cloneNode(self, deep:bool=True):
        new_node = ElementString(value=self.value, parent=self.parent)
        return new_node

@dataclass
class Element(Node):
    tag:str
    attrs:dict
    children:list
    void_:bool|None = field(default=None, repr=False)
    _detached:bool = field(default=False, repr=False)
    _if_expr:str|None = field(default=None, repr=False)
    
    @property
    def nodeName(self):
        return self.tag
    
    def __repr__(self):
        return f"{self.__class__.__name__}(tag={self.tag}, attrs={self.attrs}, children={len(self.children)} children)"

    @property
    def is_void(self):
        if self.void_ == None:
            return self.tag in voids
        else:
            return self.void_

    # Attributes that are template directives — fully resolved by react(),
    # so we strip them from the final serialized HTML to keep output clean.
    _DIRECTIVE_ATTRS = frozenset({'if', 'for', 'in', 'bind', 'key'})

    @property
    def __tag__(self) -> str:
        return self.tag

    @property
    def tagName(self) -> str:
        return self.tag
    
    @property
    def parentElement(self):
        self.parentNode

    @property
    def childNodes(self):
        return self.children
    
    @property
    def attributes(self) -> dict:
        return self.attrs

    def hasAttribute(self, attr) -> bool:
        return attr in self.attrs.keys()
    
    def getAttributeNames(self):
        return self.attrs.keys()
    
    def getAttribute(self, attr):
        try:
            return self.attrs[attr]
        except KeyError:
            return None
    
    def setAttribute(self, attr, value):
        self.attrs[attr] = value

    def removeAttribute(self, attr):
        self.attrs.pop(attr, None)

    def toggleAttribute(self, attr, force:bool|None=None):
        if force == None:
            if attr in self.attrs:
                del self.attrs[attr]
            else:
                self.attrs[attr] = ""
        elif force == True:
            self.attrs[attr] = ""
        else:
            #force == False
            del self.attrs[attr]

    # ------------------------------------------------------------------
    # EventTarget surface (server-side passive registry)
    #
    # On the client these are native browser methods.  On the server no
    # user interaction ever occurs, so handlers are simply recorded in
    # _listeners for potential introspection (e.g. testing, future
    # hydration hints).  They are NEVER invoked server-side.
    # ------------------------------------------------------------------

    def addEventListener(self, event: str, handler, options=None):
        """
        Record an event listener in the passive server-side registry.

        Mirrors the browser EventTarget.addEventListener signature;
        `options` is accepted for API compatibility but ignored.
        Handlers are stored but never called during SSR.
        """
        if '_listeners' not in self.__dict__:
            self.__dict__['_listeners'] = {}
        self._listeners.setdefault(event, []).append(handler)

    def removeEventListener(self, event: str, handler, options=None):
        """
        Remove a previously-registered listener from the passive registry.

        Mirrors browser EventTarget.removeEventListener; `options` ignored.
        """
        listeners = self.__dict__.get('_listeners', {}).get(event, [])
        try:
            listeners.remove(handler)
        except ValueError:
            pass  # not registered — same no-op as browser behaviour

    def dispatchEvent(self, event_name: str, detail=None):
        """
        Server-side stub for EventTarget.dispatchEvent.

        Events are never dispatched during SSR; this exists purely for
        API surface parity so shared code paths don't raise AttributeError.
        Always returns True (as if the event was not cancelled).
        """
        return True

    def __html__(self):
        if getattr(self, '_detached', False):
            expr = getattr(self, '_if_expr', '')
            return f"<!-- if: {expr} -->"

        tag = self.tag

        attrs_dict = {}

        for key, value in self.attrs.items():
            # Strip template directive attributes
            if key in Element._DIRECTIVE_ATTRS:
                continue
            # Strip boolean-style {attr} leftovers
            if key.startswith('{') and key.endswith('}'):
                continue
            if key == 'cls':
                attrs_dict['class'] = value
            elif key.startswith('data_'):
                attrs_dict[key.replace('_', '-')] = value
            elif key.startswith('hx_'):
                attrs_dict[key.replace('_', '-')] = value
            else:
                attrs_dict[key] = value

        attrs_str = ' '.join(f'{k}="{v}"' for k, v in attrs_dict.items())
        children = self.children

        if self.is_void:
            return f"<{tag}{' ' + attrs_str if attrs_str else ''} />"

        children_str = ""
        for c in children:
            if isinstance(c, Element):
                children_str += c.__html__()
            else:
                children_str += str(c)

        if attrs_str:
            return f"<{tag} {attrs_str}>{children_str}</{tag}>"
        else:
            return f"<{tag}>{children_str}</{tag}>"

    @property
    def descendants(self):
        yield self
        for c in self.children:
            if isinstance(c, ElementString):
                yield c
                continue
            elif isinstance(c, Comment):
                yield c
                continue
            else:
                yield from c.descendants
    
    def replace(self, other_element:Element):
        self.tag = other_element.tag
        self.attrs = other_element.attrs
        self.children = other_element.children
        self.void_ = other_element.void_

    def replaceWith(self, *elements):
        parent = self.parentNode
        print("parent:::: ", parent)
        index = parent.children.index(self)
        parent.children[index+1:index+1] = list(elements)
        parent.children.pop(index)
        # Update parent references for inserted elements
        for el in elements:
            if hasattr(el, 'parent'):
                el.parent = parent
        print("children::::", parent.children)
    

    def appendChild(self, child):
        print(f"ELEMENT: appendChild of {self.__tag__}:", child)
        if isinstance(child, ServerFragment):
            # Mirror DOM DocumentFragment: move its root element in and empty the fragment
            root = child._consume()
            if root is not None:
                self.children.append(root)
                root.parent = self
        else:
            self.children.append(child)
            if hasattr(child, 'parent'):
                child.parent = self

    def prepend(self, child):
        self.children.insert(0, child)

    def insertBefore(self, new_node, reference_node):
        print("in insertBefore", self.children)
        self.children.insert(self.children.index(reference_node)
                             , new_node)
        print(self.children)
        new_node.parent = self  # self is the parent element, not self.parent
 
    def replaceChildren(self, children):
        self.children = children

    def cloneNode(self, deep:bool=True):

        new_node = Element(tag=self.tag, attrs=self.attrs, children=self.children, void_=self.void_)
        new_node.tag = self.tag
        new_node.attrs = self.attrs
        new_node.children = self.children
        new_node.void_ = self.void_

        if deep:
            new_children = []

            for c in self.children:
                new_children.append(c.cloneNode(deep=True))
            
            new_node.children = new_children
        
        return new_node

    def contains(self, element):
        ...
    def set_text_content(self, value):
        txt = ElementString(value, parent=self)
        for c in self.children:
            c.parent = None

        self.children = [txt]

    textContent = property(None, set_text_content)

def element_fn(tag, *c, void_=None, **kwargs):
    return Element(tag=tag.lower(), children=list(c), attrs=kwargs, void_=void_)

    
class ElementTreeBuilder(TreeBuilder):
    """
    Custom TreeBuilder that converts HTML into Element components.
    """
    
    NAME = "element"
    features = ["element", "html"]
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_element = None
        self.element_stack = []
        self.root = None
    
    def reset(self):
        """Reset the builder state."""
        self.current_element = None
        self.element_stack = []
        self.root = None
    
    def feed(self, markup):
        """Parse the markup and build an Element tree."""
        if isinstance(markup, bytes):
            markup = markup.decode('utf-8')
        
        # Use html.parser to tokenize, then convert to Element
        from html.parser import HTMLParser
        
        class ElementParser(HTMLParser):
            def __init__(self, builder):
                super().__init__()
                self.builder = builder
            
            def handle_starttag(self, tag, attrs):
                self.builder.handle_starttag(tag, dict(attrs))
            
            def handle_endtag(self, tag):
                self.builder.handle_endtag(tag)
            
            def handle_data(self, data):
                self.builder.handle_data(data)
        
        parser = ElementParser(self)
        parser.feed(markup)
    
    def handle_starttag(self, name, attrs):
        """Handle opening tags."""
        # Convert HTML attributes to a pythonic style
        # (e.g., 'class' -> 'cls', 'data-*' -> 'data_*')
        fasthtml_attrs = {}
        children = []
        
        for key, value in attrs.items():
            if key == 'class':
                fasthtml_attrs['cls'] = value
            elif key.startswith('data-'):
                # Convert data-foo to data_foo
                fasthtml_attrs[key.replace('_', '-')] = value
            else:
                fasthtml_attrs[key] = value
        
        tag_func = element_fn
        
        # Create element (children will be added later)
        element = {'tag': name, 'func': tag_func, 'attrs': fasthtml_attrs, 'children': []}
        
        if self.current_element is not None:
            self.element_stack.append(self.current_element)
        
        self.current_element = element
        
        if self.root is None:
            self.root = element
    
    def handle_endtag(self, name):
        """Handle closing tags."""
        if self.current_element and self.current_element['tag'] == name:
            # Build the Element component now that we have all children
            attrs = self.current_element['attrs']
            children = self.current_element['children']
            tag_func = self.current_element['func']
            
            # Create the component with children and attributes
            if children:
                component = element_fn(self.current_element['tag'], *children, **attrs)
            else:
                component = element_fn(self.current_element['tag'], **attrs)

            # set parent for ElementString children
            for string_child in [child for child in children if isinstance(child, ElementString)]:
                string_child.parent = component

            self.current_element['component'] = component

            # Pop back to parent
            if self.element_stack:
                parent = self.element_stack.pop()
                component.parent = parent
                parent['children'].append(component)
                self.current_element = parent
            else:
                # This is the root element
                component.parent = None
                self.current_element['component'] = component
                self.current_element = None
    
    def handle_data(self, data):
        """Handle text content."""
        data = data.strip()
        data = ElementString(value=data, parent=self.current_element)
        if data and self.current_element is not None:
            self.current_element['children'].append(data)
    
    def handle_comment(self, data):
        """Handle comment data."""
        data = data.strip()
        data = Comment(data=data, parent=self.current_element)
        if data and self.current_element is not None:
            self.current_element['children'].append(data)

    def get_result(self):
        """Return the built element tree."""
        if self.root and 'component' in self.root:
            return self.root
        return None
    

def html_to_element_tree(html_string):
    """Convert HTML string to Elemenents using custom TreeBuilder."""
    builder = ElementTreeBuilder()
    builder.feed(html_string)
    return builder.get_result()

def html_to_element(html_string):
    """Convert HTML string to Elements using custom TreeBuilder."""
    builder = ElementTreeBuilder()
    builder.feed(html_string)
    tree_root = builder.get_result()
    return tree_root['component']


class ServerFragment:
    """
    Server-side equivalent of the browser's DocumentFragment.

    On the client, __template__ is the .content (DocumentFragment) of the
    cloned <template> element.  Appending a DocumentFragment moves all its
    children into the target and empties it, so a subsequent append is a
    silent no-op.  _bind_node() on the client relies on this:

        child_instance = childcomponent_py.mount(node, ...)
        # mount() already appended __template__ to node above
        node.appendChild(child_instance.__template__)  # no-op — fragment empty

    ServerFragment reproduces that contract on the server:
      - wraps the root Element on construction
      - Element.appendChild() calls _consume() which moves the root into the
        target container and sets _root = None  (fragment is now empty)
      - any subsequent appendChild() finds _root is None → no-op  ✓

    This lets server_component._bind_node keep the same line that
    component.py uses on the client, with identical semantics.
    """

    def __init__(self, root: 'Element | None'):
        self._root = root

    @property
    def root(self) -> 'Element | None':
        return self._root

    @property
    def firstElementChild(self):
        return self._root
    
    @property
    def descendants(self):
        """Delegate to the wrapped root so _get_nodes() works before mount."""
        if self._root is not None:
            yield from self._root.descendants

    def _consume(self) -> 'Element | None':
        """Move the root out and empty this fragment (like browser DOM does)."""
        root, self._root = self._root, None
        return root

    def __repr__(self):
        return f"ServerFragment(root={self._root!r})"

    def appendChild(self, child:Node):
        if isinstance(child, ServerFragment):
            # Mirror DOM DocumentFragment: move its root element in and empty the fragment
            root = child._consume()
            if root is not None:
                self.children.append(root)
                root.parent = self
        else:
            self.children.append(child)
            if hasattr(child, 'parent'):
                child.parent = self
