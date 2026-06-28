from basis.shared.component import Component
from basis.shared.store import Store
from basis.shared.dag import computed

class BasisAwait(Component):
    __tag__ = "basis-await"
    store = ""

    def __init__(self):
        super().__init__()
        self._subscribed_store = None

    def __init_fields__(self):
        super().__init_fields__()
        self._update_store_subscription(self.store)

    def __setattr__(self, name, value):
        old_value = getattr(self, name, None)
        super().__setattr__(name, value)
        if name == "store" and value != old_value:
            self._update_store_subscription(value)

    def _update_store_subscription(self, store_name):
        # Unsubscribe from previous store
        if self._subscribed_store:
            prev_store = Store._registry.get(self._subscribed_store)
            if prev_store:
                prev_store.remove_subscription(self, "loading")
                prev_store.remove_subscription(self, "error")
            
            # Clean up old dependencies from the DAG
            for node_name in ["_show_loading", "_show_error", "_show_content"]:
                node = self._dag.nodes.get(node_name)
                if node:
                    deps_to_remove = [d for d in node.dependencies if d.name.startswith("$")]
                    for d in deps_to_remove:
                        node.dependencies.remove(d)
                        d.dependents.discard(node)

        self._subscribed_store = store_name

        if store_name:
            # Set up DAG dependencies dynamically
            loading_dep = f"${store_name}.loading"
            error_dep = f"${store_name}.error"
            
            dep_loading_node = self._dag.nodes.get(loading_dep) or self._dag.get_or_create_state(loading_dep)
            dep_error_node = self._dag.nodes.get(error_dep) or self._dag.get_or_create_state(error_dep)
            
            for node_name in ["_show_loading", "_show_error", "_show_content"]:
                node = self._dag.nodes.get(node_name)
                if node:
                    node.add_dependency(dep_loading_node)
                    node.add_dependency(dep_error_node)

            store = Store._registry.get(store_name)
            if store:
                store.add_subscription(self, "loading")
                store.add_subscription(self, "error")
            else:
                # Store not loaded/initialized yet. Use pending subscriptions.
                if store_name not in Store._pending_subscriptions:
                    Store._pending_subscriptions[store_name] = []
                Store._pending_subscriptions[store_name].append((self, "loading"))
                Store._pending_subscriptions[store_name].append((self, "error"))

            # Force recalculation of computed nodes
            for node_name in ["_show_loading", "_show_error", "_show_content"]:
                node = self._dag.nodes.get(node_name)
                if node:
                    node.stale = True
                    node.update()

    @computed(dependencies=[])
    def _show_loading(self):
        if self._subscribed_store:
            store = Store._registry.get(self._subscribed_store)
            if store:
                return getattr(store, "loading", False)
        return True

    @computed(dependencies=[])
    def _show_error(self):
        if self._subscribed_store:
            store = Store._registry.get(self._subscribed_store)
            if store:
                return not getattr(store, "loading", False) and getattr(store, "error", None) is not None
        return False

    @computed(dependencies=[])
    def _show_content(self):
        if self._subscribed_store:
            store = Store._registry.get(self._subscribed_store)
            if store:
                return not getattr(store, "loading", False) and getattr(store, "error", None) is None
        return False

    def template(self):
        """
        <div class="basis-await-container">
            <div class="basis-await-loading" if="{_show_loading}">
                <slot name="loading"><div class="basis-default-spinner"></div></slot>
            </div>
            <div class="basis-await-error" if="{_show_error}">
                <slot name="error"><p>Something went wrong.</p></slot>
            </div>
            <div class="basis-await-content" if="{_show_content}">
                <slot></slot>
            </div>
        </div>
        """

    def style(self):
        """
        .basis-await-container {
            display: contents;
        }
        .basis-await-loading, .basis-await-error, .basis-await-content {
            display: contents;
        }
        .basis-default-spinner {
            display: inline-block;
            width: 24px;
            height: 24px;
            border: 3px solid rgba(0, 0, 0, 0.1);
            border-radius: 50%;
            border-top-color: var(--accent-color, #007acc);
            animation: basis-spin 1s ease-in-out infinite;
        }
        @keyframes basis-spin {
            to { transform: rotate(360deg); }
        }
        """
