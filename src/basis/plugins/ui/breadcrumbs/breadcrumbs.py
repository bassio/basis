from basis.shared.component import Component
from basis.shared.reactive import computed

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
        result = []
        for idx, item in enumerate(raw_items):
            label = item.get("label", "") if isinstance(item, dict) else str(item)
            href = item.get("href", "") if isinstance(item, dict) else ""
            result.append({
                "label": label,
                "href": href,
                "is_last": idx == length - 1
            })
        return result


    def style(self):
        """
        ui-breadcrumbs {
            display: inline-block;
        }

        .ui-breadcrumbs-list {
            display: flex;
            align-items: center;
            flex-wrap: wrap;
            list-style: none;
            padding: 0;
            margin: 0;
            gap: 0.5rem;
            font-size: 0.75rem;
            font-family: var(--font-mono, monospace);
            letter-spacing: 0.06em;
            text-transform: uppercase;
            color: var(--text-muted, #767c90);
        }

        .ui-breadcrumbs-item {
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
        }

        .ui-breadcrumbs-link a {
            color: var(--text-muted, #767c90);
            text-decoration: none;
            font-weight: 500;
            transition: color 0.15s ease;
        }

        .ui-breadcrumbs-link a:hover {
            color: var(--accent-color, #7f6df2);
        }

        .ui-breadcrumbs-text {
            color: var(--text-secondary, #a9afc0);
            font-weight: 500;
        }

        .ui-breadcrumbs-item:last-child .ui-breadcrumbs-text {
            color: var(--text-muted, #767c90);
            opacity: 0.8;
        }

        .ui-breadcrumbs-separator {
            color: var(--border-color, #3a4256);
            display: inline-flex;
            align-items: center;
            user-select: none;
            font-size: 0.75rem;
            opacity: 0.6;
        }
        """

    def template(self):
        """
        <nav class="ui-breadcrumbs" aria-label="Breadcrumb">
            <ol class="ui-breadcrumbs-list">
                <li class="ui-breadcrumbs-item" for="item" in="{processed_items}" key="label">
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
