"""The offline fallback page — the document that has to work when nothing else does.

Served at :data:`~basis.plugins.mobile.pwa.OFFLINE_URL` and precached at install; a
navigation with no network and no cached copy of its own route lands here. It stands in
for a page whose runtime could not boot, so it cannot depend on that runtime — which is
exactly what a :class:`~basis.shared.page.StaticPage` is: the framework renders the whole
document (chrome, theme tokens, the plugins' ``$head`` links) and ships no client at all.

That is also why there is no second document here and no colour policy of the plugin's
own: the card is an ordinary component reading the theme's ``--*`` tokens, and the
document around it is the framework's.
"""

from basis.shared.component import Component, scoped
from basis.shared.page import StaticPage
from basis.shared.reactive import computed


class OfflineCard(Component):
    """The fallback's content: whose app this is, what happened, and the way back.

    The display name follows the declaration — ``title``, else ``short_name``, else a
    neutral stand-in — so an install that only named itself briefly still reads as itself.

    ``<ui-theme-provider>`` rides in the card because the page mounts no app root: it is
    what turns the active theme into the ``--*`` tokens the stylesheet reads (and stamps
    ``color-scheme``), so a dark-mode install gets a dark fallback without the plugin
    resolving a single color.
    """

    @scoped
    def style(self):
        """
        :scope, :scope ui-theme-provider {
            display: contents;
        }

        .offline-card {
            box-sizing: border-box;
            min-height: 100vh;
            min-height: 100dvh;
            display: grid;
            place-content: center;
            justify-items: center;
            gap: 0.75rem;
            /* The house padding pattern: the viewport's gutter scale plus the device's
               safe areas. The tokens come from the framework's viewport base CSS and the
               theme provider; the raw ``env()`` fallback keeps an unthemed render padded
               rather than notched. */
            padding-block: calc(var(--page-gutter, 1.5rem) + var(--safe-area-top, env(safe-area-inset-top, 0px)))
                          calc(var(--page-gutter, 1.5rem) + var(--safe-area-bottom, env(safe-area-inset-bottom, 0px)));
            padding-inline: calc(var(--page-gutter, 1.5rem) + var(--safe-area-left, env(safe-area-inset-left, 0px)))
                           calc(var(--page-gutter, 1.5rem) + var(--safe-area-right, env(safe-area-inset-right, 0px)));
            background: var(--bg-primary, #ffffff);
            color: var(--text-primary, #1e2431);
            font-family: var(--font-sans, system-ui, -apple-system, "Segoe UI", sans-serif);
            text-align: center;
        }

        h1 {
            margin: 0;
            font-size: 1.375rem;
        }

        p {
            margin: 0;
            max-width: 30rem;
            line-height: 1.5;
            color: var(--text-secondary, #61636e);
            text-wrap: balance;
        }

        a {
            color: var(--accent-text, #5847c9);
            font-weight: 600;
        }
        """

    @computed(dependencies=["$pwa"])
    def app_name(self):
        """The app's name as the user knows it, or a neutral stand-in."""
        pwa = self.__class__.S.get("pwa")
        return (
            getattr(pwa, "title", None)
            or getattr(pwa, "short_name", None)
            or "This app"
        )

    def template(self):
        """
        <div class="offline-card">
            <ui-theme-provider></ui-theme-provider>
            <h1>You&rsquo;re offline</h1>
            <p>{app_name} needs a connection for this page. It will load again once you are back online.</p>
            <a href="{$pwa.start_url}">Try again</a>
        </div>
        """


class OfflinePage(StaticPage):
    """The fallback document: the card under the framework's page chrome.

    ``stores`` names what the card reads and nothing else — the theme (its ``--*`` tokens),
    the app's declaration (its identity) and ``$head`` (the manifest / icon / theme-color
    links the plugins contribute, which is why the fallback wears the app's head even
    though it boots no client).
    """

    title = "Offline"
    root_component = OfflineCard
    stores = ("theme", "head", "pwa")
