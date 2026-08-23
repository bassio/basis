from basis.shared.component import Component

class Accordion(Component):
    __tag__ = "ui-accordion"
    
    def style(self):
        """
        .ui-accordion {
            display: flex;
            flex-direction: column;
            width: 100%;
        }
        """

    def template(self):
        """
        <div class="ui-accordion">
            <slot></slot>
        </div>
        """

class AccordionItem(Component):
    __tag__ = "ui-accordion-item"
    name = "default-group"
    title = ""

    def style(self):
        """
        .ui-accordion-item {
            border-bottom: 1px solid var(--border-color, #e5e7eb);
        }
        
        .ui-accordion-trigger {
            display: flex;
            flex: 1;
            align-items: center;
            justify-content: space-between;
            padding-top: 1rem;
            padding-bottom: 1rem;
            font-size: 0.875rem; /* 14px */
            font-weight: 500;
            transition: all 0.2s;
            cursor: pointer;
            list-style: none; /* Removes Safari/Chrome marker */
            background: none;
            border: none;
            width: 100%;
            text-align: left;
            color: var(--text-primary, inherit);
            outline: none;
        }

        /* Hide the native triangle in webkit browsers */
        .ui-accordion-trigger::-webkit-details-marker {
            display: none;
        }

        .ui-accordion-trigger:hover {
            text-decoration: underline;
        }

        .accordion-icon {
            height: 1rem;
            width: 1rem;
            flex-shrink: 0;
            transition: transform 0.2s ease-out;
            color: var(--text-secondary, #6b7280);
        }

        /* When details is open, rotate the chevron */
        details[open] > .ui-accordion-trigger > .accordion-icon {
            transform: rotate(180deg);
        }

        .ui-accordion-content {
            font-size: 0.875rem;
            padding-bottom: 1rem;
            color: var(--text-secondary, #4b5563);
            animation: accordion-down 0.2s ease-out;
        }

        @keyframes accordion-down {
            from {
                opacity: 0;
                transform: translateY(-4px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
        """

    def template(self):
        """
        <details class="ui-accordion-item" name="{name}">
            <summary class="ui-accordion-trigger">
                <span class="trigger-content">{title}</span>
                <svg class="accordion-icon" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="6 9 12 15 18 9"></polyline>
                </svg>
            </summary>
            <div class="ui-accordion-content">
                <slot></slot>
            </div>
        </details>
        """
