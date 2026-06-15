from basis.shared.component import Component

class Sidebar(Component):
    __tag__ = "ui-sidebar"
    side = "left"
    collapsible = "offcanvas" # or "icon"
    
    def style(self):
        """
        .ui-sidebar {
            display: flex;
            flex-direction: column;
            --sidebar-width: 16rem; /* 256px */
            --sidebar-width-icon: 3.5rem; /* 56px */
            background-color: var(--bg-secondary, #f8f9fa);
            transition: width 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            height: 100%;
            overflow: hidden;
            width: var(--sidebar-width);
            flex-shrink: 0;
            box-sizing: border-box;
            color: var(--text-primary, #2e2e2e);
            position: relative;
        }

        .ui-sidebar[side="left"] {
            border-right: 1px solid var(--border-color, #dcdcdc);
        }
        .ui-sidebar[side="right"] {
            border-left: 1px solid var(--border-color, #dcdcdc);
        }

        .ui-sidebar[data-state="collapsed"] {
            width: 0;
            border: none;
        }
        
        .ui-sidebar[data-state="collapsed"][collapsible="icon"] {
            width: var(--sidebar-width-icon);
            border: 1px solid var(--border-color, #dcdcdc);
        }
        """

    def template(self):
        """
        <div class="ui-sidebar">
            <slot></slot>
        </div>
        """

class SidebarHeader(Component):
    __tag__ = "ui-sidebar-header"

    def style(self):
        """
        .ui-sidebar-header {
            display: flex;
            flex-direction: column;
            box-sizing: border-box;
            padding: 0.75rem;
            flex-shrink: 0;
            gap: 0.5rem;
        }
        """

    def template(self):
        """
        <div class="ui-sidebar-header">
            <slot></slot>
        </div>
        """

class SidebarContent(Component):
    __tag__ = "ui-sidebar-content"

    def style(self):
        """
        .ui-sidebar-content {
            display: flex;
            flex-direction: column;
            flex: 1 1 auto;
            min-height: 0;
            overflow-y: auto;
            overflow-x: hidden;
            box-sizing: border-box;
            padding: 0.5rem;
            gap: 0.75rem;
        }
        
        /* Custom Scrollbar for Sidebar */
        .ui-sidebar-content::-webkit-scrollbar {
            width: 6px;
        }
        .ui-sidebar-content::-webkit-scrollbar-thumb {
            background-color: var(--border-color, #dcdcdc);
            border-radius: 4px;
        }
        """

    def template(self):
        """
        <div class="ui-sidebar-content">
            <slot></slot>
        </div>
        """

class SidebarGroup(Component):
    __tag__ = "ui-sidebar-group"

    def style(self):
        """
        .ui-sidebar-group {
            display: flex;
            flex-direction: column;
            box-sizing: border-box;
            width: 100%;
            gap: 0.25rem;
        }
        """

    def template(self):
        """
        <div class="ui-sidebar-group">
            <slot></slot>
        </div>
        """

class SidebarGroupLabel(Component):
    __tag__ = "ui-sidebar-group-label"

    def style(self):
        """
        .ui-sidebar-group-label {
            display: flex;
            align-items: center;
            box-sizing: border-box;
            padding: 0.25rem 0.5rem;
            font-size: 0.75rem; /* 12px */
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-secondary, #7a7a7a);
            transition: opacity 0.2s ease;
            white-space: nowrap;
        }
        /* Make text overflow hidden */
        """
        
    def template(self):
        """
        <div class="ui-sidebar-group-label">
            <slot></slot>
        </div>
        """

class SidebarGroupContent(Component):
    __tag__ = "ui-sidebar-group-content"

    def style(self):
        """
        .ui-sidebar-group-content {
            display: flex;
            flex-direction: column;
            box-sizing: border-box;
            width: 100%;
        }
        """

    def template(self):
        """
        <div class="ui-sidebar-group-content">
            <slot></slot>
        </div>
        """

class SidebarMenu(Component):
    __tag__ = "ui-sidebar-menu"
    
    def style(self):
        """
        .ui-sidebar-menu {
            display: flex;
            flex-direction: column;
            gap: 0.125rem;
            width: 100%;
            margin: 0;
            padding: 0;
            list-style: none;
        }
        """
    def template(self):
        """
        <div class="ui-sidebar-menu">
            <slot></slot>
        </div>
        """

class SidebarMenuButton(Component):
    __tag__ = "ui-sidebar-menu-button"
    active = "false"
    
    def style(self):
        """
        :host {
            display: flex;
            width: 100%;
        }
        .sidebar-menu-button {
            display: flex;
            align-items: center;
            width: 100%;
            gap: 0.5rem;
            border-radius: 0.375rem;
            padding: 0.375rem 0.5rem;
            font-size: 0.875rem;
            font-weight: 500;
            background: transparent;
            color: var(--text-secondary, #7a7a7a);
            border: none;
            cursor: pointer;
            text-align: left;
            transition: background-color 0.2s, color 0.2s;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        
        .sidebar-menu-button[active="true"]  {
            background-color: var(--hover-bg, #f5f5f5);
            color: var(--text-primary, #2e2e2e);
            font-weight: 600;
        }
        
        .sidebar-menu-button:hover {
            background-color: var(--hover-bg, #f5f5f5);
            color: var(--text-primary, #2e2e2e);
        }
        """
    def template(self):
        """
        <button class="sidebar-menu-button" data-active="{active}">
            <slot></slot>
        </button>
        """

class SidebarFooter(Component):
    __tag__ = "ui-sidebar-footer"

    def style(self):
        """
        .ui-sidebar-footer {
            display: flex;
            flex-direction: column;
            box-sizing: border-box;
            padding: 0.75rem;
            flex-shrink: 0;
            border-top: 1px solid var(--border-color, #dcdcdc);
        }
        """
        
    def template(self):
        """
        <div class="ui-sidebar-footer">
            <slot></slot>
        </div>
        """

class SidebarTrigger(Component):
    __tag__ = "ui-sidebar-trigger"
    target = ""
    
    def toggle(self, event):
        sidebar = None
        if self.target:
            from pyscript import document
            sidebar = document.querySelector(self.target)
        else:
            sidebar = self.node.closest("ui-sidebar")


        if sidebar:
            state = sidebar.getAttribute("data-state") or "expanded"
            new_state = "expanded" if state == "collapsed" else "collapsed"
            sidebar.setAttribute("data-state", new_state)

    def style(self):
        """
        .ui-sidebar-trigger {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 2rem;
            height: 2rem;
            border-radius: 0.375rem;
            background: transparent;
            color: var(--text-secondary, #7a7a7a);
            border: none;
            cursor: pointer;
            transition: all 0.2s;
        }
        .ui-sidebar-trigger:hover {
            background-color: rgba(73, 80, 87, 0.15);
            color: var(--text-primary, #2e2e2e);
            transform: scale(1.05);
        }
        """

    def template(self):
        """
        <button type="button" class="ui-sidebar-trigger" onclick="{toggle}">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-panel-left"><rect width="18" height="18" x="3" y="3" rx="2" ry="2"></rect><line x1="9" y1="3" x2="9" y2="21"></line></svg>
        </button>
        """
