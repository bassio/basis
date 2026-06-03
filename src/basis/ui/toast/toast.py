from basis.shared.store import Store
from basis.shared.component import Component
from dataclasses import dataclass
import sys

# Framework check for client-side timer
IS_CLIENT = "pyscript" in sys.modules

@dataclass
class ToastItem:
    id: str
    message: str
    variant: str
    title: str
    duration: int

class ToastStore(Store):
    """
    A reactive store managing the toast notification queue.
    """
    def __init__(self, name="toast"):
        super().__init__(name)
        self.toasts = []
        self._counter = 0

    def show(self, message, variant="info", title=None, duration=5000):
        """
        Add a new toast notification.
        Variants: 'info', 'success', 'warning', 'error'
        """
        self._counter += 1
        toast_id = f"toast-{self._counter}"
        new_toast = ToastItem(
            id=toast_id,
            message=str(message),
            variant=variant,
            title=title or "",
            duration=duration
        )
        # Trigger reactivity by replacing the list
        self.toasts = [*self.toasts, new_toast]
        return toast_id

    def add(self, *args, **kwargs):
        """Alias for show()"""
        return self.show(*args, **kwargs)

    def remove(self, toast_id):
        """Remove a toast by ID."""
        self.toasts = [t for t in self.toasts if t.id != toast_id]


class Toast(Component):
    """
    Individual toast notification component.
    """
    __tag__ = "ui-toast"
    
    id = ""
    message = ""
    variant = "info" 
    title = ""
    duration = 5000

    def style(self):
        """
        ui-toast {
            display: block;
            margin-bottom: 0.75rem;
            pointer-events: auto;
            animation: toast-in 0.4s cubic-bezier(0.16, 1, 0.3, 1) forwards;
        }

        .toast-body {
            display: flex;
            align-items: flex-start;
            gap: 0.85rem;
            padding: 1rem 1.25rem;
            background: var(--glass-bg, rgba(255, 255, 255, 0.85));
            backdrop-filter: blur(var(--glass-blur, 12px));
            -webkit-backdrop-filter: blur(var(--glass-blur, 12px));
            border: 1px solid var(--border-color, rgba(0,0,0,0.1));
            border-radius: var(--radius-lg, 0.75rem);
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
            min-width: 320px;
            max-width: 450px;
            color: var(--text-primary, #1a1a1a);
            position: relative;
            overflow: hidden;
            transition: transform 0.2s ease, opacity 0.2s ease;
        }

        /* Variant vertical indicator */
        .toast-body::before {
            content: '';
            position: absolute;
            left: 0;
            top: 0;
            bottom: 0;
            width: 5px;
        }

        .variant-info::before { background: #3b82f6; }
        .variant-success::before { background: #10b981; }
        .variant-warning::before { background: #f59e0b; }
        .variant-error::before { background: #ef4444; }

        .toast-content {
            flex: 1;
            padding-right: 0.5rem;
        }

        .toast-title {
            font-weight: 600;
            margin-bottom: 0.25rem;
            font-size: 0.95rem;
            color: var(--text-primary);
        }

        .toast-message {
            font-size: 0.875rem;
            opacity: 0.85;
            line-height: 1.5;
            color: var(--text-secondary);
        }

        .toast-close {
            background: none;
            border: none;
            color: var(--text-secondary, #6b7280);
            cursor: pointer;
            padding: 0.35rem;
            border-radius: 0.5rem;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.2s;
            margin-top: -0.25rem;
            margin-right: -0.5rem;
            opacity: 0.6;
        }

        .toast-close:hover {
            background: var(--hover-bg, rgba(0,0,0,0.05));
            opacity: 1;
            transform: scale(1.1);
        }

        @keyframes toast-in {
            from {
                opacity: 0;
                transform: translateY(20px) scale(0.9);
            }
            to {
                opacity: 1;
                transform: translateY(0) scale(1);
            }
        }

        .toast-out {
            opacity: 0 !important;
            transform: translateX(40px) scale(0.9) !important;
        }
        """

    def template(self):
        """
        <div class="toast-body variant-{variant}">
            <div class="toast-content">
                <div class="toast-title" if="{title}">{title}</div>
                <div class="toast-message">{message}</div>
            </div>
            <button class="toast-close" onclick="{close_handler}">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
            </button>
        </div>
        """

    def close_handler(self, event=None):
        """Handle the close action with animation."""
        if getattr(self, "_closing", False):
            return
        self._closing = True

        el = self.__element__
        if el:
            el.classList.add("toast-out")
        
        if IS_CLIENT:
            from pyscript import window, ffi
            
            def _delayed_remove():
                toast.remove(self.id)
            
            proxy = ffi.create_proxy(_delayed_remove)
            self._proxies.append(proxy)
            window.setTimeout(proxy, 350)
        else:
            toast.remove(self.id)

    def __init__(self):
        super().__init__()
        self._proxies = []
        self._timer_started = False

        if IS_CLIENT:
            from pyscript import window, ffi
            
            def _check_and_start_timer():
                # We check if id has been hydrated yet
                if not self.id:
                    # Not hydrated yet, wait another tick
                    retry_proxy = ffi.create_proxy(_check_and_start_timer)
                    self._proxies.append(retry_proxy)
                    window.setTimeout(retry_proxy, 50)
                    return

                if self._timer_started:
                    return
                
                try:
                    d = int(self.duration)
                    if d > 0:
                        self._timer_started = True
                        def _auto_close():
                            self.close_handler()
                        
                        proxy = ffi.create_proxy(_auto_close)
                        self._proxies.append(proxy)
                        window.setTimeout(proxy, d)
                except:
                    pass
            
            # Start the hydration check
            init_proxy = ffi.create_proxy(_check_and_start_timer)
            self._proxies.append(init_proxy)
            window.setTimeout(init_proxy, 50)


class ToastContainer(Component):
    """
    Manager component that renders all active toasts.
    """
    __tag__ = "ui-toast-container"

    def style(self):
        """
        ui-toast-container {
            position: fixed;
            bottom: 2rem;
            right: 2rem;
            z-index: 10000;
            display: flex;
            flex-direction: column-reverse;
            pointer-events: none;
            gap: 0.5rem;
        }
        """

    def template(self):
        """
        <div class="ui-toast-stack">
            <ui-toast 
                for="t" in="{$toast.toasts}" 
                key="{t.id}"
                id="{t.id}"
                message="{t.message}"
                variant="{t.variant}"
                title="{t.title}"
                duration="{t.duration}">
            </ui-toast>
        </div>
        """

# Singleton instance
toast = ToastStore()
