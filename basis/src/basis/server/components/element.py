from bs4.builder import TreeBuilder
from dataclasses import dataclass, field

voids = {'area', 'base', 'br', 'col', 'command', 'embed', 'hr', 'img', 'input', 'keygen', 'link', 'meta', 'param', 'source', 'track', 'wbr', '!doctype'}

class Comment(object):
    data:str
    parent:Element|None = None
    nodeName:str = field(default= "#comment", init=False, repr=False)
    
    def __html__(self):
        return """<!--{self.data}-->"""

@dataclass
class ElementString(object):
    value:str
    parent:Element|None = None
    nodeName:str = field(default= "#text", init=False, repr=False)

    def wholeText(self):
        return self.value

    def get_value(self):
        return self.value
    
    def set_value(self, value):
        self.value = value

    textContent = property(get_value, set_value)
    
    def __str__(self):
        return self.value
    
    def __repr__(self):
        return f'"{self.value}"'
        
    @property
    def parentElement(self):
        return self.parent
    
    @property
    def descendants(self):
        return []

@dataclass
class Element(object):
    tag:str
    attrs:dict
    children:list
    void_:bool|None = field(default=None, repr=False)
    _detached:bool = field(default=False, repr=False)
    _if_expr:str|None = field(default=None, repr=False)

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
        return self.parent['component']

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
        #print("parent:::: ", self.parentElement, self.parent)
        index = self.parentElement.children.index(self)
        self.parentElement.children[index+1:index+1] = elements
        self.parentElement.children.pop(index)

    def appendChild(self, child):
        self.children.append(child)

    def prepend(self, child):
        self.children.insert(0, child)

    def replaceChildren(self, children):
        self.children = children

    def contains(self, element):
        ...

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
