# Basis framework

## Core Concept

Basis is a full-stack Python web framework that uses FastAPI on the backend and PyScript on the frontend. It allows developers to build interactive web applications using python-based Custom Elements, bypassing the need for JavaScript frameworks like React or Vue, while maintaining a reactive, component-based architecture.

## Project Structure

The source code is primarily housed within basis/src/basis/, structured into distinct tiers:

components/component.py (Frontend / Built for PyScript): This is the core browser-side module. It provides the Component base class which parses HTML templates (either from docstrings or .html files) and dynamically registers Custom Web Elements (window.customElements.define) in the DOM using PyScript's JavaScript FFI.

server/app.py (Backend): Provides Basis, a subclass of FastAPI. It includes utility methods for mounting Python web components directories automatically and dynamically generating pyscript.json for the client to download its component code and HTML/CSS assets.

server/components/server_component.py (Server-Side Rendering): Contains ServerComponent, an SSR-equivalent class layout used to construct element trees on the backend via html parsing before sending them down to the client.

shared/bindings.py: A shared module that defines the simple dataclasses describing the different Binding types mapping Python models to UI changes.

## Core Architecture

The Basis framework employs a fine-grained, dependency-tracked reactivity system, mirroring approaches found in modern compile-free / lightweight frameworks but built entirely on top of Python and PyScript. At its core, the reactive system uses a combination of DOM walking, AST parsing, and direct property observation to minimize DOM updates.

## The Reactivity & Binding System

Basis operates reactivity completely in Python using a structural binding mechanism rather than a Virtual DOM:

- Initialization: When a Component mounts or is initialized, it dynamically traverses the DOM (using document.createTreeWalker) and categorizes bindings based on syntax (TextBinding, EventBinding, AttributeBinding, LoopBinding, and ChildBinding).
- Reactive State: The Component.__setattr__ method is overridden. When a bound field changes, it queues a microtask (window.queueMicrotask) and calls .react([name]).
- Targeted DOM Updates: The .react() method iterates exclusively over the specific bindings linked to the changed properties and directly mutates the TextContent, Element Attributes, or iteratively updates DOM nodes inside tracked lists, keeping DOM updates highly targeted and performant.

## Reactivity Flow

Template Parsing via TreeWalker: In the component's initialization phase (init_bindings), the framework walks through the DOM template nodes (document.createTreeWalker) and categorizes each DOM element into one or more Binding classes.

Abstract Syntax Trees (AST): Basis supports expressions inside templates (e.g. {item.name + '!'}). It intercepts these bindings, extracts the Python expression using Formatter, and builds an Abstract Syntax Tree (AST) using Python's ast module. The extract_dependencies function determines which component fields
 are involved in the expression, ensuring the binding only reacts when its specific dependencies modify.

Bindings: The framework maintains a registry of various Binding types, for example:
- TextBinding: Manages text nodes with expressions.
- AttributeBinding: Binds dynamic values to HTML attributes.
- EventBinding: Synchronizes DOM events (e.g., onclick) with component methods.
- ModelBinding: Provides two-way data-binding (bind="..."), generating event proxies that assign values back to the component instance field.
- IfBinding, LoopBinding, KeyedLoopBinding: Structural directives to inject/remove or iterate over template fragments.
- ChildBinding: Maintains a reference to instances of custom child components embedded in a template.

Reactivity Triggers (react): Modifying a property triggers the overridden setattr.
This invokes the react(names) method which cross-references the modified field names with the dependencies listed in __bindings__. The update mechanism surgically targets bound nodes: updating node.textContent for texts, node.setAttribute for properties, and intelligently re-rendering specific items inside loop iterations. State changes are batched efficiently over a browser EventLoop microtask queue using window.queueMicrotask().

