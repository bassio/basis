import copy

from basis.shared.bindings import SelfBinding
from basis.shared.store import Store
from basis.shared.base_component import BaseComponent
from basis.shared.element import Element, ElementString, Comment, ServerFragment

from basis.server.tree_builder import html_to_element_tree



class ServerComponent(BaseComponent):
    
    @classmethod
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    #@server
    @classmethod
    def _initialize_blueprint(cls):
        ###Server
        blueprint_tree = html_to_element_tree(cls.__templatestr__)
        setattr(cls, "__blueprint__", blueprint_tree)

    @classmethod
    def _analyze_template(cls):
        blueprint_tree = getattr(cls, "__blueprint__", None)
        if blueprint_tree:
            root_element = blueprint_tree['component']
            
            # Reuse _get_nodes for consistent indexing
            nodes = cls._get_nodes(root_element)
            
            for node_index, node in enumerate(nodes):
                blueprints = cls._analyze_node(node, node_index)
                if blueprints:
                    cls.__binding_blueprints__.extend(blueprints)

    @classmethod
    def _get_nodes_all(cls, element):
        nodes = []
        if element:
            for d in element.descendants:
                nodes.append(d)
        return nodes

    @classmethod
    def _get_nodes_skip_loops(cls, element):
        nodes = []
        if element:
            def walk(node):
                if isinstance(node, Element):
                    yield node
                    # Skip descending into loop subtrees
                    if 'for' in node.attrs and 'in' in node.attrs:
                        return
                    for c in node.children:
                        yield from walk(c)
                
                elif isinstance(node, ServerFragment):
                    # ServerFragments are virtual containers: walk children but do not yield self
                    for c in node.children:
                        yield from walk(c)
                
                else:
                    # Text/Comment nodes: yield self (no children to walk)
                    yield node
            
            for n in walk(element):
                nodes.append(n)
        
        return nodes

    @classmethod
    def _get_nodes(cls, element, skip_loop_descendants=True):
        if skip_loop_descendants:
            return cls._get_nodes_skip_loops(element)
        return cls._get_nodes_all(element)


    @classmethod
    def clone_blueprint(cls):
        raw = cls.__blueprint__
        print(cls, raw)
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
