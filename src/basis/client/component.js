// Registry of custom-element configs keyed by tag. Basis Python refreshes the
// entry on HMR re-imports so NEW elements render the updated template without
// needing to redefine the (already-registered) custom element.
globalThis.__basisElementConfigs = {};

class LightDomComponent extends HTMLElement {
  constructor() {
    super();
    // No call to this.attachShadow({ mode: 'open' }) is needed.
  }

  connectedCallback() {
  }
}

function CustomElementFactory(config) {

  if (config && config['pyTag']) {
    globalThis.__basisElementConfigs[config['pyTag']] = config;
  }

  let C = class extends HTMLElement
  {
    constructor() {
      super();

      // Prefer the freshest config (HMR may have refreshed the registry).
      const tag = (this.tagName || '').toLowerCase();
      this.config = globalThis.__basisElementConfigs[tag] || config;

      console.log(`JS: Initializing constructor for '${this.tagName}' element`);

      const shadow = this.config['__shadow__'];

      if (shadow) {

        this.attachShadow({ mode: "open" });
        
      }

    }

    setPyCls(cls){
      this.cls = cls;
    }

    connectedCallback() {
      
      console.log(`JS: ${this.tagName} added to page (connectedCallback())`);

      // Generic "this element just joined the live document" signal. Fires on
      // every connect — initial mount, an if-reveal re-insert, fallback moves.
      // The JS side stays dumb: Python (Basis) listens and decides what to do
      // (e.g. boot a @js_component that was hidden at SSR render time).
      this.dispatchEvent(new CustomEvent('basis:connected', {
        bubbles: true,
        detail: { tag: this.tagName.toLowerCase() }
      }));

      // Refresh from the registry so HMR template updates reach existing elements.
      const tag = (this.tagName || '').toLowerCase();
      if (globalThis.__basisElementConfigs[tag]) {
        this.config = globalThis.__basisElementConfigs[tag];
      }

      const shadow = this.config['__shadow__'];

      // ── Fresh Mount ──────────────────────────────────────────────────────
      const init_template = document.createElement('template');
      init_template.innerHTML = this.config['__templatestr__'];
      

      const attributesList = this.attributes;

      if (attributesList.length > 0){
        console.log(`JS: All attributes of ${this.tagName}:`, attributesList);
      }
      
      if (shadow) {
        
        const shadowRoot = this.shadowRoot;
        // Only populate an empty shadow root: re-connecting an existing element
        // (e.g. a hydration-fallback re-render that moves an already-mounted
        // subtree into the live DOM) must not duplicate the template.
        if (shadowRoot.childNodes.length === 0) {
          const templateContent = init_template.content
          shadowRoot.appendChild(document.importNode(templateContent, true));
        }

      }
      
      
    }

    disconnectedCallback() {
      
      console.log(`JS: ${this.tagName} removed from page (disconnectedCallback())`);

      // Mirror of the 'basis:connected' connect signal, for when this element
      // (or an ancestor subtree containing it) leaves the live document.
      //
      // DOM note: disconnectedCallback fires AFTER the node is already removed,
      // so an event dispatched on `this` can never bubble up to `document`.
      // Dispatch on `document` directly instead — Python listens there for the
      // bubbled basis:connected AND this basis:disconnected, then tests its own
      // target element's isConnected to decide whether IT is the one that left.
      //
      // Signal only: Basis never auto-destroys on disconnect — if-hide and
      // hydration-fallback moves legitimately disconnect then reconnect.
      document.dispatchEvent(new CustomEvent('basis:disconnected', {
        detail: { tag: this.tagName.toLowerCase() }
      }));
    }
  }

  Object.defineProperty (C, 'name', {value: config['pyClass']});

  // Return the class (constructor)
  return C;
}


globalThis.CustomElementFactory = CustomElementFactory;

