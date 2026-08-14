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

      // Refresh from the registry so HMR template updates reach existing elements.
      const tag = (this.tagName || '').toLowerCase();
      if (globalThis.__basisElementConfigs[tag]) {
        this.config = globalThis.__basisElementConfigs[tag];
      }

      const shadow = this.config['__shadow__'];
      const pyClassName = this.config['pyClassName'];

      // ── SSR Hydration Detection ──────────────────────────────────────────
      // If the first element child carries a data-basis-component marker that
      // matches this element's Python class, the content was server-rendered.
      // In that case we call .hydrate(this) so PyScript wires up reactivity
      // against the existing DOM rather than inserting a fresh template clone.
      const firstChild = this.firstElementChild;
      const ssrMarker = firstChild && firstChild.dataset && firstChild.dataset.basisComponent;
      const isSSR = ssrMarker === pyClassName;

      if (isSSR) {
        console.log(`JS: ${this.tagName} — SSR content detected, triggering hydration`);
        // PyScript picks this up via the custom event, or the Python mount_app
        // entry checks for data-basis-component and calls .hydrate() directly.
        this.dispatchEvent(new CustomEvent('basis:hydrate', {
          bubbles: true,
          detail: { pyClassName, element: this }
        }));
        return;
      }

      // ── Fresh Mount (no SSR) ─────────────────────────────────────────────
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
      else {
        const shadowRoot = this.shadowRoot;

        const templateContent = init_template.content
        const fragment = templateContent.cloneNode(true); // cloneNode(true) is essential for deep cloning all children      
        //shadowRoot.appendChild(document.importNode(templateContent, true));
        //this.appendChild(document.importNode(templateContent, true));

      }
      
      
    }
  }

  Object.defineProperty (C, 'name', {value: config['pyClass']});

  // Return the class (constructor)
  return C;
}


globalThis.CustomElementFactory = CustomElementFactory;

