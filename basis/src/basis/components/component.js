class LightDomComponent extends HTMLElement {
  constructor() {
    super();
    // No call to this.attachShadow({ mode: 'open' }) is needed.
  }

  connectedCallback() {
  }
}

function CustomElementFactory(config) {

  let C = class extends HTMLElement
  {
    constructor() {
      super();

      this.config = config;

      console.log(`JS: Initializing constructor for '${this.tagName}' element`);

      this.attachShadow({ mode: "open" });

    }

    setPyCls(cls){
      this.cls = cls;
    }

    connectedCallback() {
      //console.log(`JS: ${this.tagName} added to page (connectedCallback())`);

      const shadow = this.config['__shadow__'];

      const init_template = document.createElement('template');
      init_template.innerHTML = this.config['__templatestr__'];
      

      const attributesList = this.attributes;

      if (attributesList.length > 0){
        console.log(`JS: All attributes of ${this.tagName}:`, attributesList);
      }
      
      if (shadow) {
        
        const shadowRoot = this.shadowRoot;
        const templateContent = init_template.content
        shadowRoot.appendChild(document.importNode(templateContent, true));

      }
      else {
        const fragment = init_template.content.cloneNode(true); // cloneNode(true) is essential for deep cloning all children      
        this.appendChild(fragment);
      }
      
      
    }
  }

  Object.defineProperty (C, 'name', {value: config['pyClass']});

  // Return the class (constructor)
  return C;
}


globalThis.CustomElementFactory = CustomElementFactory;

