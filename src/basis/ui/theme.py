from basis.shared.store import Store
from basis.shared.component import Component
from basis.shared.reactive import computed


class ThemeStore(Store):
    """
    A reactive store for design tokens.
    """
    def __init__(self, name="theme"):
        super().__init__(name)
        self.dark_mode = False

        # Background
        self.bg_primary = "light-dark(#F6F6F7, #1E2431)"     # page / canvas
        self.bg_secondary = "light-dark(#FFFFFF, #242B3A)"   # panels: sidebar, titlebar, statusbar
        self.bg_tertiary = "light-dark(#F0F0F2, #2B3344)"    # elevated: tab bar, cards

        # Text
        self.text_primary = "light-dark(#1E2431, #ECEEF2)"
        self.text_secondary = "light-dark(#61636E, #A9AFC0)"
        self.text_muted = "light-dark(#93949D, #767C90)"

        # Accent
        self.accent_color = "light-dark(#6E5FD8, #9384F5)"
        self.accent_bg = "light-dark(#EBE9F8, rgba(147, 132, 245, 0.16))"
        self.accent_text = "light-dark(#5847C9, #B7ACF8)"

        # Borders
        self.border_color = "light-dark(#E1E1E4, #3A4256)"
        self.border_soft = "light-dark(#EAEAED, #2E3546)"

        self.hover_bg = "light-dark(rgba(0, 0, 0, 0.04), rgba(255, 255, 255, 0.08))"

        # Typography
        self.font_sans = "'Inter', sans-serif"
        self.font_serif = "'Source Serif 4', serif"    # note titles / voice
        self.font_mono = "'IBM Plex Mono', monospace"  # metadata, status bar, paths

        # Shared tokens
        self.radius_sm = "0.25rem"
        self.radius_md = "0.5rem"
        self.radius_lg = "1rem"
        self.shadow_sm = "0 1px 2px 0 rgba(0, 0, 0, 0.05)"
        self.shadow_md = "0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)"


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
            f"--text-muted: {t.text_muted}",
            f"--accent-color: {t.accent_color}",
            f"--accent-bg: {t.accent_bg}",
            f"--accent-text: {t.accent_text}",
            f"--border-color: {t.border_color}",
            f"--border-soft: {t.border_soft}",
            f"--hover-bg: {t.hover_bg}",
            f"--font-sans: {t.font_sans}",
            f"--font-serif: {t.font_serif}",
            f"--font-mono: {t.font_mono}",
            f"--radius-sm: {t.radius_sm}",
            f"--radius-md: {t.radius_md}",
            f"--radius-lg: {t.radius_lg}",
            f"--shadow-sm: {t.shadow_sm}",
            f"--shadow-md: {t.shadow_md}",
        ]

        joined_rules = "; ".join(rules)
        return ":root { color-scheme: light dark; " + joined_rules + "}"


    def template(self):
        """
        <style id="theme-provider" text-content="{tokens_css}"></style>
        <slot></slot>
        """

# Global instance for convenience
theme = ThemeStore()
