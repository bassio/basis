from basis.shared.store import Store
from basis.shared.component import Component
from basis.shared.dag import computed

class ThemeStore(Store):
    """
    A reactive store for design tokens.
    """
    def __init__(self, name="theme"):
        super().__init__(name)
        
        # Default Tokens (Premium / Productivity aesthetic)
        self.dark_mode = False
        
        # Colors
        self.accent_color = "#007acc"
        
        # Light Theme defaults
        self.bg_primary = "#ffffff"
        self.bg_secondary = "#f8f9fa"
        self.bg_tertiary = "#e9ecef"
        self.text_primary = "#212529"
        self.text_secondary = "#6c757d"
        self.border_color = "#dee2e6"
        self.hover_bg = "rgba(0, 0, 0, 0.05)"
        self.glass_bg = "rgba(255, 255, 255, 0.8)"
        
        # Shared tokens
        self.glass_blur = "12px"
        self.radius_sm = "0.25rem"
        self.radius_md = "0.5rem"
        self.radius_lg = "1rem"
        self.shadow_sm = "0 1px 2px 0 rgba(0, 0, 0, 0.05)"
        self.shadow_md = "0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)"

    def toggle_dark_mode(self):
        self.dark_mode = not self.dark_mode
        if self.dark_mode:
            self.bg_primary = "#1a1a1a"
            self.bg_secondary = "#252525"
            self.bg_tertiary = "#333333"
            self.text_primary = "#f8f9fa"
            self.text_secondary = "#adb5bd"
            self.border_color = "#404040"
            self.hover_bg = "rgba(255, 255, 255, 0.1)"
            self.glass_bg = "rgba(20, 20, 20, 0.7)"
        else:
            self.bg_primary = "#ffffff"
            self.bg_secondary = "#f8f9fa"
            self.bg_tertiary = "#e9ecef"
            self.text_primary = "#212529"
            self.text_secondary = "#6c757d"
            self.border_color = "#dee2e6"
            self.hover_bg = "rgba(0, 0, 0, 0.05)"
            self.glass_bg = "rgba(255, 255, 255, 0.8)"


class ThemeProvider(Component):
    """
    Component that injects reactive CSS variables into the page.
    """
    __tag__ = "ui-theme-provider"

    def style(self):
        return """
        ui-theme-provider {
            display: contents;
        }
        """

    @computed(dependencies=["$theme"])
    def tokens_css(self):
        # We can't use simple iteration because we want to be explicit 
        # and transform Python underscores to CSS hyphens.
        t = self.__class__.S['theme']
        rules = [
            f"--accent-color: {t.accent_color}",
            f"--bg-primary: {t.bg_primary}",
            f"--bg-secondary: {t.bg_secondary}",
            f"--bg-tertiary: {t.bg_tertiary}",
            f"--text-primary: {t.text_primary}",
            f"--text-secondary: {t.text_secondary}",
            f"--border-color: {t.border_color}",
            f"--hover-bg: {t.hover_bg}",
            f"--glass-bg: {t.glass_bg}",
            f"--glass-blur: {t.glass_blur}",
            f"--radius-sm: {t.radius_sm}",
            f"--radius-md: {t.radius_md}",
            f"--radius-lg: {t.radius_lg}",
            f"--shadow-sm: {t.shadow_sm}",
            f"--shadow-md: {t.shadow_md}",
        ]
        return ":root { " + "; ".join(rules) + "; }"

    def template(self):
        """
        <style id="theme-provider" text-content="{tokens_css}"></style>
        <slot></slot>
        """

# Global instance for convenience
theme = ThemeStore()
