from bs4.builder import TreeBuilder
from dataclasses import dataclass, field

voids = {'area', 'base', 'br', 'col', 'command', 'embed', 'hr', 'img', 'input', 'keygen', 'link', 'meta', 'param', 'source', 'track', 'wbr', '!doctype'}

@dataclass
class ElementString(object):
    value:str
    parent:Element|None = None
        
    def __str__(self):
        return self.value
    
    def __repr__(self):
        return f'"{self.value}"'

        
@dataclass
class Element(object):
    tag:str
    attrs:dict
    children:list
    void_:bool|None = field(default=None, repr=False)
    _detached:bool = field(default=False, repr=False)
    _if_expr:str|None = field(default=None, repr=False)

    @property
    def is_void(self):
        if self.void_ == None:
            return self.tag in voids
        else:
            return self.void_

    def __html__(self):
        if getattr(self, '_detached', False):
            expr = getattr(self, '_if_expr', '')
            return f"<!-- if: {expr} -->"

        tag = self.tag

        attrs_dict = {}

        for key, value in self.attrs.items():
            if key == 'cls':
                attrs_dict['class'] = value
            elif key.startswith('data_'):
                # Convert data-foo to data_foo
                attrs_dict[key.replace('-', '_')] = value
            elif key.startswith('hx_'):
                # Convert htmx attributes
                attrs_dict[key.replace('-', '_')] = value
            else:
                attrs_dict[key] = value

        attrs_str = ' '.join(f'{k}=\"{v}\"' for k, v in attrs_dict.items())
        children = self.children
        
        if self.is_void:
            return f"<{tag} {attrs_str} />"

            
        children_str = ""

        if len(self.children) > 0:
            for c in children:
                if isinstance(c, Element):
                    children_str += c.__html__()
                else:
                    children_str += c

        if attrs_str == '':
            return f"<{tag}>{children_str}</{tag}>"
        else:        
            return f"<{tag} {attrs_str}>{children_str}</{tag}>"

    @property
    def descendants(self):
        yield self
        for c in self.children:
            if isinstance(c, ElementString):
                yield c
                continue
            else:
                yield from c.descendants
    
    def replace_with(self, other_element:Element):
        self.tag = other_element.tag
        self.attrs = other_element.attrs
        self.children = other_element.children
        self.void_ = other_element.void_

def element_fn(tag, *c, void_=None, **kwargs):
    return Element(tag=tag.lower(), children=c, attrs=kwargs, void_=void_)

    
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
