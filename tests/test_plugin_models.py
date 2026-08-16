import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Field, create_engine, Session
from basis.server.app import Basis
from basis.server.plugin import BasisPlugin

from sqlalchemy.pool import StaticPool

# Setup database engine
engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

def get_test_session():
    with Session(engine) as session:
        yield session

def test_plugin_model_registry_and_expose():
    app = Basis()
    app.get_session = get_test_session
    
    plugin = BasisPlugin(prefix="/chat")
    
    # 1. Test registration of a model with @plugin.model decorator
    @plugin.model
    class User(SQLModel, table=True):
        id: int | None = Field(default=None, primary_key=True)
        username: str

    # 2. Test registration + REST endpoints via @plugin.expose decorator
    @plugin.expose("/messages/", one=False)
    @plugin.expose("/messages/{id}", one=True)
    @plugin.expose("/messages/", method="POST")
    @plugin.expose("/messages/{id}", method="DELETE", one=True)
    @plugin.expose("/messages/{id}", method="PATCH")
    class Message(SQLModel, table=True):
        id: int | None = Field(default=None, primary_key=True)
        text: str
        user_id: int

    # Check plugin tracking
    assert User in plugin.models
    assert Message in plugin.models

    # Include plugin in app
    app.include_plugin(plugin)

    # Check app merging
    assert User in app.models
    assert Message in app.models

    # Initialize the database and tables using the new helper method
    app.create_db_and_tables(engine)

    client = TestClient(app)

    # 1. Test POST (create Message)
    response = client.post("/chat/messages/", json={"text": "Hello, Basis!", "user_id": 1})
    assert response.status_code == 200
    msg_data = response.json()
    assert msg_data["id"] == 1
    assert msg_data["text"] == "Hello, Basis!"
    assert msg_data["user_id"] == 1

    # Add another one
    response = client.post("/chat/messages/", json={"text": "Second message", "user_id": 1})
    assert response.status_code == 200

    # 2. Test GET (all Messages)
    response = client.get("/chat/messages/")
    assert response.status_code == 200
    all_msgs = response.json()
    assert len(all_msgs) == 2
    assert all_msgs[0]["text"] == "Hello, Basis!"
    assert all_msgs[1]["text"] == "Second message"

    # 3. Test GET (single Message)
    response = client.get("/chat/messages/1")
    assert response.status_code == 200
    assert response.json()["text"] == "Hello, Basis!"

    # Test GET (single Message - not found)
    response = client.get("/chat/messages/999")
    assert response.status_code == 404

    # 4. Test PATCH (update Message)
    response = client.patch("/chat/messages/1", json={"text": "Hello, Basis (Updated)!"})
    assert response.status_code == 200
    assert response.json()["text"] == "Hello, Basis (Updated)!"

    # Verify update in GET
    response = client.get("/chat/messages/1")
    assert response.json()["text"] == "Hello, Basis (Updated)!"

    # 5. Test DELETE (single Message)
    response = client.delete("/chat/messages/1")
    assert response.status_code == 200
    assert response.json()["detail"] == "Deleted successfully"
    assert response.json()["record"]["text"] == "Hello, Basis (Updated)!"

    # Verify deleted
    response = client.get("/chat/messages/1")
    assert response.status_code == 404
