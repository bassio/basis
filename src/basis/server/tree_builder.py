from bs4.builder import TreeBuilder
from basis.shared.element import Element, ElementString, Comment, element_fn
from basis.shared.hydration import hydration_mode_is_canonical

# ---------------------------------------------------------------------------
# Canonical text handling (Phase A — deterministic hydration)
# ---------------------------------------------------------------------------
# The legacy tree-builder stripped leading/trailing whitespace from every text
# chunk and dropped empty ones.  That corrupted SSR output (e.g. ``Best: ``
# became ``Best:``) and made the server tree structurally different from the
# browser DOM (which preserves whitespace text nodes).
#
# The canonical mode keeps text exactly as authored and merges contiguous
# chunks into a single ``ElementString`` per text run (matching browser
# text-node boundaries).  Whitespace-only text nodes stay in the tree — they
# are excluded from hydration IDs by *policy* (see
# ``basis/shared/hydration.py``), not by deletion — so the server tree and the
# client DOM are structurally identical.
#
# Which mode is active is decided by ``hydration_mode_is_canonical()``
# (``BASIS_HYDRATION=canonical`` or ``set_hydration_mode()``); it is resolved
# at parse time so the A/B toggle applies to each tree build.


class ElementTreeBuilder(TreeBuilder):
    """
    Custom TreeBuilder that converts HTML into Element components.
    """
    
    NAME = "element"
    features = ["element", "html"]
    
    def __init__(self, *args, preserve_text=None, **kwargs):
        super().__init__(*args, **kwargs)
        if preserve_text is None:
            preserve_text = hydration_mode_is_canonical()
        self.preserve_text = preserve_text
        self.reset()
    
    def reset(self):
        """Reset the builder state."""
        self.current_element = None
        self.element_stack = []
        self.root = None
        # --- Tree ID State ---
        self.path_stack = ["r"]  # Root prefix
        self.index_stack = [0]   # Current index at each depth
        # --- Canonical text-run state (preserve_text mode) ---
        # True when the most recent event in the current parent was text, so
        # contiguous chunks merge into one ElementString (browser behaviour).
        self._text_run_open = False

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

            def handle_comment(self, data):
                # Route comments through the builder so canonical mode preserves
                # them as Comment nodes (splitting text runs exactly like the
                # browser).  Legacy mode drops them, matching its current
                # behaviour so the live SSR path is unchanged.
                if self.builder.preserve_text:
                    self.builder.handle_comment(data)

        parser = ElementParser(self)
        parser.feed(markup)
    
    def handle_starttag(self, name, attrs):
        """Handle opening tags."""
        # A new element ends any open text run at this level.
        self._text_run_open = False
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
        # Closing a tag ends any open text run in the (now-current) parent.
        self._text_run_open = False
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
        """Handle text content.

        ``preserve_text=False`` (legacy, default): strip leading/trailing
        whitespace and drop empty chunks — the original behaviour, retained so
        the live SSR path stays byte-for-byte unchanged until parity is
        confirmed.

        ``preserve_text=True`` (canonical, Phase A): preserve the text exactly
        as authored and merge adjacent chunks into a single ``ElementString``
        per text run (matching browser text-node boundaries).  Whitespace-only
        text nodes remain in the tree.
        """
        if self.current_element is None:
            return

        if not self.preserve_text:
            # --- LEGACY behaviour (unchanged) ---
            data = data.strip()
            if data == "":
                return
            self.current_element['children'].append(
                ElementString(value=data, parent=self.current_element)
            )
            return

        # --- Canonical behaviour (Phase A) ---
        children = self.current_element['children']
        if (
            self._text_run_open
            and children
            and isinstance(children[-1], ElementString)
            and data
        ):
            # Contiguous chunk from the same text run: merge into one node,
            # mirroring how the browser coalesces text into a single Text node.
            children[-1].value += data
        elif data:
            children.append(ElementString(value=data, parent=self.current_element))
        # Mark this run as open so the NEXT chunk (if any) merges.
        self._text_run_open = True
    
    def handle_comment(self, data):
        """Handle comment data."""
        # A comment node sits between text runs: end any open run.
        self._text_run_open = False
        data = data.strip()
        data = Comment(data=data, parent=self.current_element)
        if data and self.current_element is not None:
            self.current_element['children'].append(data)

    def get_result(self):
        """Return the built element tree."""
        if self.root and 'component' in self.root:
            return self.root
        return None
    

def html_to_element_tree(html_string, preserve_text=None):
    """Convert HTML string to Elements using custom TreeBuilder.

    ``preserve_text`` selects canonical text handling; ``None`` uses
    ``PRESERVE_TEXT_DEFAULT`` (legacy until parity is confirmed).
    """
    builder = ElementTreeBuilder(preserve_text=preserve_text)
    builder.feed(html_string)
    return builder.get_result()

def html_to_element(html_string, preserve_text=None):
    """Convert HTML string to Elements using custom TreeBuilder."""
    builder = ElementTreeBuilder(preserve_text=preserve_text)
    builder.feed(html_string)
    tree_root = builder.get_result()
    return tree_root['component']

