from bs4.builder import TreeBuilder
from basis.shared.element import Element, ElementString, Comment, element_fn

class ElementTreeBuilder(TreeBuilder):
    """
    Custom TreeBuilder that converts HTML into Element components.
    """
    
    NAME = "element"
    features = ["element", "html"]
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.reset()
    
    def reset(self):
        """Reset the builder state."""
        self.current_element = None
        self.element_stack = []
        self.root = None
        # --- Tree ID State ---
        self.path_stack = ["r"]  # Root prefix
        self.index_stack = [0]   # Current index at each depth

    def _generate_current_id(self):
        """Combines the current path and the current index at this depth."""
        parent_path = ":".join(self.path_stack)
        current_idx = self.index_stack[-1]
        return f"{parent_path}:{current_idx}"
    
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
                #fasthtml_attrs['cls'] = value
                fasthtml_attrs['class'] = value
            elif key.startswith('data-'):
                # Convert data-foo to data_foo
                fasthtml_attrs[key.replace('_', '-')] = value
            else:
                fasthtml_attrs[key] = value
        
        tag_func = element_fn

        #commented for now
        #element_id = self._generate_current_id()
        #fasthtml_attrs['data-hydration-id'] = element_id

        # Create element (children will be added later)
        element = {'tag': name, 'func': tag_func, 'attrs': fasthtml_attrs, 'children': []}
        
        if self.current_element is not None:
            self.element_stack.append(self.current_element)
        
        self.current_element = element
        
        if self.root is None:
            self.root = element

        # --- Descend Tree Logic ---
        # We push the current ID (without index) into path stack for children
        # We use the index as part of the path name for the next level
        this_level_id_fragment = str(self.index_stack[-1])
        self.path_stack.append(this_level_id_fragment)
        # Push a fresh counter for this element's children
        self.index_stack.append(0)
        
    def handle_endtag(self, name):
        """Handle closing tags."""
        if self.current_element and self.current_element['tag'] == name:
            # Build the Element component now that we have all children
            attrs = self.current_element['attrs']
            children = self.current_element['children']
            tag_func = self.current_element['func']
            
            # Finished processing children, so go back up
            self.index_stack.pop()
            self.path_stack.pop()
            # Increment the index of the PARENT so the next sibling gets +1
            self.index_stack[-1] += 1

            # Create the component with children and attributes
            if children:
                component = element_fn(self.current_element['tag'], *children, **attrs)
            else:
                component = element_fn(self.current_element['tag'], **attrs)

            # set parent for ElementString children
            for string_child in [child for child in children if isinstance(child, ElementString)]:
                string_child.parent = component

            #component._hydration_id = attrs['data-hydration-id']

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
        if data != "": # check for and eliminate empty ElementString("") in the tree
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

