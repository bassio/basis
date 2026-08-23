from basis.shared.component import Component

class Card(Component):
    """
    A container card component.
    """
    __tag__ = "ui-card"

    def style(self):
        """
        ui-card {
            display: flex;
            flex-direction: column;
            width: 100%;
            background: var(--bg-secondary, #1e2431);
            border: 1px solid var(--border-color, #2d3245);
            border-radius: var(--radius-lg, 10px);
            overflow: hidden;
            box-shadow: var(--shadow-sm, 0 1px 3px rgba(0,0,0,0.1));
            transition: border-color 0.2s ease, box-shadow 0.2s ease;
            box-sizing: border-box;
        }
        ui-card:hover {
            border-color: var(--border-hover, #3d4663);
        }
        .ui-card {
            display: flex;
            flex-direction: column;
            width: 100%;
            height: 100%;
            box-sizing: border-box;
        }
        """

    def template(self):
        """
        <div class="ui-card">
            <slot></slot>
        </div>
        """

class CardHeader(Component):
    """
    Header section of a Card.
    """
    __tag__ = "ui-card-header"

    def style(self):
        """
        ui-card-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 12px 16px;
            border-bottom: 1px solid var(--border-soft, #2b3245);
        }
        .ui-card-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            width: 100%;
            box-sizing: border-box;
        }
        """

    def template(self):
        """
        <div class="ui-card-header">
            <slot></slot>
        </div>
        """

class CardTitle(Component):
    """
    Title inside a CardHeader.
    """
    __tag__ = "ui-card-title"

    def style(self):
        """
        ui-card-title {
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--text-secondary, #a3a8b8);
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }
        .ui-card-title {
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--text-secondary, #a3a8b8);
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }
        """

    def template(self):
        """
        <span class="ui-card-title">
            <slot></slot>
        </span>
        """

class CardContent(Component):
    """
    Main content area of a Card.
    """
    __tag__ = "ui-card-content"

    def style(self):
        """
        ui-card-content {
            display: flex;
            flex-direction: column;
            padding: 16px;
            gap: 12px;
            color: var(--text-primary);
        }
        .ui-card-content {
            display: flex;
            flex-direction: column;
            padding: 16px;
            gap: 12px;
            color: var(--text-primary);
            width: 100%;
            box-sizing: border-box;
        }
        """

    def template(self):
        """
        <div class="ui-card-content">
            <slot></slot>
        </div>
        """

class CardFooter(Component):
    """
    Footer section of a Card.
    """
    __tag__ = "ui-card-footer"

    def style(self):
        """
        ui-card-footer {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 10px 16px;
            border-top: 1px solid var(--border-soft, #2b3245);
            font-size: 0.8rem;
            color: var(--text-muted, #767c90);
        }
        .ui-card-footer {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 10px 16px;
            border-top: 1px solid var(--border-soft, #2b3245);
            font-size: 0.8rem;
            color: var(--text-muted, #767c90);
            width: 100%;
            box-sizing: border-box;
        }
        """

    def template(self):
        """
        <div class="ui-card-footer">
            <slot></slot>
        </div>
        """

