import html
import re

from dataclasses import dataclass, field
voids = {'area', 'base', 'br', 'col', 'command', 'embed', 'hr', 'img', 'input', 'keygen', 'link', 'meta', 'param', 'source', 'track', 'wbr', '!doctype'}

#: Raw-text elements (HTML spec): their content is literal raw text — no
#: character references, no tags; only the matching closing tag terminates it.
#: Entity-escaping their text (e.g. ``&`` → ``&amp;``) corrupts the content,
#: because the browser does NOT decode entities inside them. Contrast
#: ``<textarea>``/``<title>`` (RCDATA — entities ARE decoded, so escaping
#: round-trips) and normal elements like ``<pre>`` (markup — must escape).
_RAW_TEXT_TAGS = frozenset({"script", "style"})

#: The raw-text closing sequences that would terminate the element early,
#: matched case-insensitively (the HTML parser's end-tag match is
#: case-insensitive). ``<\/`` is not a raw-text close in HTML, and ``\/`` is
#: valid inside script/style string & regex content, so it round-trips.
_RAW_TEXT_CLOSE = re.compile(r"</(?=(?:script|style)\b)", re.IGNORECASE)


def _guard_raw_text(value: str) -> str:
    """Neutralize the raw-text closing sequence so *value* can't close its
    element early, leaving everything else literal (no entity escaping)."""
    return _RAW_TEXT_CLOSE.sub(r"<\\/", value)

class Node(object):
    parent:'Node|None' = None

    @property
    def parentNode(self):
        if isinstance(self.parent, dict):
            return self.parent['component']
        return self.parent

    @property
    def nextSibling(self):
        all_siblings = self.parentNode.childNodes
        idx = all_siblings.index(self)
        try:
            return self.parentNode.childNodes[idx+1]
        except IndexError:
            return None

    def after(self, *nodes):
        parent = self.parentNode

        try:
            index = parent.children.index(self)
        except ValueError:
            # self is not currently in the parent's children list
            # (e.g. an IfBinding node that was removed); append at the end.
            print(f"after(): {self!r} not found in parent.children — appending at end")
            index = len(parent.children) - 1
            
        expanded = []
        for n in nodes:
            if type(n).__name__ == 'ServerFragment':
                expanded.extend(n._consume())
            else:
                n.remove() # Ensure it's detached from previous parent
                expanded.append(n)
                
        parent.children[index+1:index+1] = expanded
        # Update parent references for inserted elements
        for n in expanded:
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

@dataclass(eq=False)
class Comment(Node):
    parent:'Element|None' = None
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

@dataclass(eq=False)
class ElementString(Node):
    value:str
    nodeName:str = field(default= "#text", init=False, repr=False)
    parent:'Element|None' = None
    
    def wholeText(self):
        return self.value

    def get_value(self):
        return self.value
    
    def set_value(self, value):
        self.value = value

    textContent = property(get_value, set_value)
    
    def __html__(self):
        # Text is escaped at serialization time only — mirroring the browser,
        # where textContent stores the raw string and the HTML output escapes
        # it. Without this, a TextBinding value containing markup (e.g. a code
        # sample "<b>hi</b>") would be written raw into the SSR HTML and the
        # browser would parse it back as real elements.
        return html.escape(self.value, quote=False)

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

@dataclass(eq=False)
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
    _DIRECTIVE_ATTRS = frozenset({'if', 'for', 'in', 'bind', 'key', 'text-content'})

    @property
    def __tag__(self) -> str:
        return self.tag

    @property
    def tagName(self) -> str:
        return self.tag
    
    @property
    def parentElement(self):
        return self.parentNode

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
            if attr in self.attrs:
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

        attrs_str = ' '.join(
            f'{k}="{html.escape(str(v), quote=True)}"' for k, v in attrs_dict.items()
        )
        children = self.children

        if self.is_void:
            return f"<{tag}{' ' + attrs_str if attrs_str else ''} />"

        children_str = ""
        if tag in _RAW_TEXT_TAGS:
            # Raw-text element (script/style): per the HTML spec the content is
            # literal raw text — no character references, no tags — so text is
            # emitted verbatim (NOT html.escape'd), guarding only the closing
            # sequence. The browser reads this back exactly as written; the
            # client DOM (textContent) already behaves the same way.
            for c in children:
                if isinstance(c, ElementString):
                    children_str += _guard_raw_text(c.value)
                else:
                    # Comment / (unusual) nested element: str() verbatim.
                    children_str += str(c)
        else:
            for c in children:
                if isinstance(c, Element):
                    children_str += c.__html__()
                elif isinstance(c, ElementString):
                    # Text serializes escaped (see ElementString.__html__).
                    children_str += c.__html__()
                else:
                    # Comment / DocumentType: str() renders their markup verbatim.
                    children_str += str(c)

        if attrs_str:
            return f"<{tag} {attrs_str}>{children_str}</{tag}>"
        else:
            return f"<{tag}>{children_str}</{tag}>"

    @property
    def outerHTML(self):
        return self.__html__()

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

    def querySelectorAll(self, selectors:str):
        if selectors == "*":
            yield from self.descendants
        else:
            raise NotImplementedError()

    def replace(self, other_element:'Element'):
        # If the other element is already in a tree, remove it
        other_element.remove()
        
        self.tag = other_element.tag
        self.attrs = other_element.attrs
        self.children = other_element.children
        self.void_ = other_element.void_
        
        # Ensure children point to this element now
        for c in self.children:
            c.parent = self

    def replaceWith(self, *elements):
        parent = self.parentNode
        index = parent.children.index(self)
        
        expanded = []
        for el in elements:
            if type(el).__name__ == 'ServerFragment':
                expanded.extend(el._consume())
            else:
                el.remove() # Ensure it's detached from previous parent
                expanded.append(el)
                
        parent.children[index+1:index+1] = expanded
        parent.children.pop(index)
        # Update parent references for inserted elements
        for el in expanded:
            el.parent = parent
    

    def appendChild(self, child):
        
        child.remove()

        if type(child).__name__ == 'ServerFragment':
            # Mirror DOM DocumentFragment: move its root element in and empty the fragment
            children_to_move = child._consume()
            for c in children_to_move:
                self.children.append(c)
                c.parent = self
        else:
            self.children.append(child)
            child.parent = self

    def prepend(self, child):

        child.remove()

        self.children.insert(0, child)

        child.parent = self

    def insertBefore(self, new_node, reference_node):

        #In the browser DOM, insertBefore(newNode, null)
        #is a valid operation that defaults to appendChild(newNode).
        if reference_node is None:
            self.appendChild(new_node)
            return

        new_node.remove()
        
        
        idx = self.children.index(reference_node)
        
        if type(new_node).__name__ == 'ServerFragment':
            children_to_move = new_node._consume()
            for c in reversed(children_to_move):
                self.children.insert(idx, c)
                c.parent = self
        else:
            self.children.insert(idx, new_node)
            new_node.parent = self
 
    def replaceChildren(self, *children):
        expanded = []
        for c in children:
            if type(c).__name__ == 'ServerFragment':
                expanded.extend(c._consume())
            else:
                expanded.append(c)
        
        for c in self.children:
            c.parent = None
            
        self.children = []
        for c in expanded:
            c.remove()
            self.children.append(c)
            c.parent = self

    def cloneNode(self, deep:bool=True):
        new_attrs = self.attrs.copy()
        new_node = Element(tag=self.tag, attrs=new_attrs, children=[], void_=self.void_)

        if deep:
            new_children = []
            for c in self.children:
                cloned_child = c.cloneNode(deep=True)
                cloned_child.parent = new_node
                new_children.append(cloned_child)
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


class DocumentType(Node):
    parent:None = None
    name:str = "html"

    def __init__(self, name="html"):
        self.name = name

    def __html__(self):
        return f"<!DOCTYPE {self.name}>"


class ServerFragment(Node):
    """
    Server-side equivalent of the browser's DocumentFragment.

    Inherits from Node. On the client, __template__ is the .content (DocumentFragment) of the
    cloned <template> element. Appending a DocumentFragment moves all its
    children into the target and empties it, so a subsequent append is a
    silent no-op. _bind_node() on the client relies on this.

    ServerFragment reproduces that contract on the server:
      - Can contain multiple children.
      - Element.appendChild() calls _consume() which moves all children into the
        target container and empties the fragment.
      - any subsequent appendChild() finds no children → no-op ✓
    """

    def __init__(self, root: 'Element | None' = None, children: list = None):
        if children is not None:
            self.children = list(children)
        elif root is not None:
            self.children = [root]
        else:
            self.children = []
            
        for c in self.children:
            if hasattr(c, 'parent'):
                c.parent = self

    @property
    def nodeName(self):
        return "#document-fragment"

    @property
    def root(self) -> 'Element | None':
        return self.children[0] if self.children else None

    @property
    def firstElementChild(self):
        return self.children[0] if self.children else None
    
    @property
    def descendants(self):
        """Yield descendants of all children."""
        for c in self.children:
            if hasattr(c, 'descendants'):
                yield from c.descendants

    def _consume(self) -> list:
        """Move all children out and empty this fragment (like browser DOM does)."""
        children = self.children[:]
        self.children = []
        return children

    def __repr__(self):
        return f"ServerFragment(children={len(self.children)})"

    def appendChild(self, child:Node):
        if type(child).__name__ == 'ServerFragment':
            # Mirror DOM DocumentFragment: move its children in and empty the fragment
            children_to_move = child._consume()
            for c in children_to_move:
                self.children.append(c)
                if hasattr(c, 'parent'):
                    c.parent = self
        else:
            self.children.append(child)
            if hasattr(child, 'parent'):
                child.parent = self

    def __html__(self):
        children_str = ""
        for c in self.children:
            if hasattr(c, '__html__'):
                children_str += c.__html__()
            else:
                children_str += str(c)
        return children_str
