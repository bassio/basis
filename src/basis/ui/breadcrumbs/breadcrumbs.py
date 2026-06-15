from basis.shared.component import Component
from basis.shared.dag import computed

class Breadcrumbs(Component):
    """
    A horizontal navigation breadcrumbs trail.
    
    Attributes:
        items:     List of dicts: [{"label": "Home", "href": "/"}, {"label": "Notes"}]
        separator: Character or icon separator (default: "/")
    """
    __tag__ = "ui-breadcrumbs"

    items = []
    separator = "/"

    @computed(dependencies=["items"])
    def processed_items(self):
        raw_items = self.items or []
        length = len(raw_items)
        return [
            {
                "label": item.get("label", ""),
                "href": item.get("href", ""),
                "is_last": idx == length - 1
            }
            for idx, item in enumerate(raw_items)
        ]

    def style(self):
        """
        ui-breadcrumbs {
            display: block;
        }

        .ui-breadcrumbs-list {
            display: flex;
            align-items: center;
            flex-wrap: wrap;
            list-style: none;
            padding: 0;
            margin: 0;
            gap: 0.35rem;
            font-size: 0.85rem;
            color: var(--text-secondary, #6c757d);
        }

        .ui-breadcrumbs-item {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
        }

        .ui-breadcrumbs-link a {
            color: var(--text-secondary, #6c757d);
            text-decoration: none;
            font-weight: 500;
            transition: color 0.15s ease;
        }

        .ui-breadcrumbs-link a:hover {
            color: var(--accent-color, #007acc);
        }

        .ui-breadcrumbs-text {
            color: var(--text-primary, #212529);
            font-weight: 600;
        }

        .ui-breadcrumbs-separator {
            color: var(--border-color, #dee2e6);
            display: inline-flex;
            align-items: center;
            user-select: none;
            font-size: 0.75rem;
        }
        """

    def template(self):
        """
        <nav class="ui-breadcrumbs" aria-label="Breadcrumb">
            <ol class="ui-breadcrumbs-list">
                <li class="ui-breadcrumbs-item" for="item" in="{processed_items()}" key="label">
                    <basis-link class="ui-breadcrumbs-link" href="{item['href']}" if="{item['href'] and not item['is_last']}">
                        {item['label']}
                    </basis-link>
                    <span class="ui-breadcrumbs-text" if="{not item['href'] or item['is_last']}">
                        {item['label']}
                    </span>
                    <span class="ui-breadcrumbs-separator" if="{not item['is_last']}">
                        {separator}
                    </span>
                </li>
            </ol>
        </nav>
        """
