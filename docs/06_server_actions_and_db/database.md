# Database & SQLModel Integration

Basis provides seamless, isomorphic database models through `basis.shared.db`. You can define a single SQLModel class that acts as a SQLAlchemy ORM model on the server and a lightweight `dataclass` in PyScript on the client.

---

## 1. Defining Isomorphic Models

Import `SQLModel` and `Field` from `basis.shared.db`:

```python
from basis.shared.db import SQLModel, Field

class Item(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    price: float
    in_stock: bool = True
```

### Isomorphic Dual Behavior

```mermaid
graph LR
    Sub[class Item(SQLModel, table=True)]
    
    subgraph Server (FastAPI / SQLAlchemy)
        Sub -->|Imports real SQLModel| ServerORM[SQLAlchemy Table & Pydantic Validation]
    end

    subgraph Client (PyScript / Pyodide)
        Sub -->|Translates Field & Model| ClientDataclass[Standard Python dataclass with model_dump & model_validate]
    end
```

- **Server-Side**: Uses the real `SQLModel`, creating database tables and enforcing Pydantic type validation.
- **Client-Side**: Strips ORM metadata (e.g. `primary_key`, `foreign_key`) and converts the class into a standard Python `dataclass`, providing `model_dump()` and `model_validate()` without requiring heavyweight backend ORMs in WebAssembly.

---

## 2. Using `DBAppMixin` in Basis App

The `Basis` class inherits from `DBAppMixin`, providing built-in database helpers and automatic request-scoped session management (`db_session_var`).

```python
from basis import Basis
from basis.shared.db import SQLModel

app = Basis(db_url="sqlite:///./app.db")

@app.on_event("startup")
def on_startup():
    # Automatically creates all registered tables
    app.create_db_and_tables()
```

---

## 3. Database Operations in Server Actions

Within `@server_action` methods or FastAPI routes, query and mutate database models using standard SQLModel sessions:

```python
from basis.shared.store import ModelStore
from basis.shared.actions import server_action
from basis.shared.context import db_session_var
from sqlmodel import select

from models import Item

class ProductStore(ModelStore):
    def __init__(self):
        super().__init__("products", Item)

    @server_action
    async def create_product(self, title: str, price: float):
        session = db_session_var.get()
        new_item = Item(title=title, price=price)
        session.add(new_item)
        session.commit()
        session.refresh(new_item)
        
        # Update local items list
        self.items.append(new_item)
        return new_item
```

---

## 4. Reactive Model CRUD (`ModelStore`)

`ModelStore` provides standard reactive CRUD helper methods (`fetch_all()`, `fetch_one()`, `create()`, `update()`, `delete()`) that work seamlessly across server SSR and client browser components:

```python
# In a component event handler
async def delete_item(self, item_id: int):
    success = await product_store.delete(id=item_id)
    if success:
        print("Product removed")
```
