import sys
import dataclasses
from typing import Any

# Framework check
IS_CLIENT = "pyscript" in sys.modules
IS_SERVER = not IS_CLIENT

if IS_SERVER:
    # ---------------------------------------------------------
    # SERVER SIDE: Pass straight through to actual SQLModel
    # ---------------------------------------------------------
    from sqlmodel import SQLModel, Field, Relationship

else:
    # ---------------------------------------------------------
    # CLIENT SIDE: Pure standard library dataclass translation
    # ---------------------------------------------------------

    def Field(default: Any = None, **kwargs: Any) -> Any:
        """
        Translates SQLModel.Field into a standard dataclass field.
        Safely strips out server-side keys like primary_key, foreign_key, index, etc.
        """
        if "default_factory" in kwargs:
            return dataclasses.field(default_factory=kwargs["default_factory"])
        
        return dataclasses.field(default=default)

    def Relationship(*args: Any, **kwargs: Any) -> Any:
        """
        Translates SQLModel.Relationship into an empty dataclass field.
        On the client, relationships are typically populated manually via JSON 
        or left as None/empty lists.
        """
        return dataclasses.field(default=None)

    class SQLModel:
        """
        The client-side base class. When inherited, it automatically 
        transforms the subclass into a standard Python dataclass.
        """
        def __init_subclass__(cls, table: bool = False, **kwargs: Any):
            super().__init_subclass__()
            # Automatically apply the dataclass decorator to the user's model
            dataclasses.dataclass(cls, kw_only=True)

        def model_dump(self) -> dict:
            """Mimic Pydantic/SQLModel dict export using dataclasses."""
            return dataclasses.asdict(self)

        @classmethod
        def model_validate(cls, obj: Any) -> Any:
            """
            Hydrate class instance from dict, filtering out fields 
            not defined on the client class.
            """
            if not isinstance(obj, dict):
                raise ValueError("model_validate requires a dictionary")
            
            # Filter keys to only those defined as fields on the dataclass
            fields = {f.name for f in dataclasses.fields(cls)}
            filtered_obj = {k: v for k, v in obj.items() if k in fields}
            return cls(**filtered_obj)


def _make_serializable(val: Any, seen: set | None = None) -> Any:
    if seen is None:
        seen = set()

    if val is None:
        return None
    if isinstance(val, (str, int, float, bool)):
        return val

    val_id = id(val)
    if val_id in seen:
        return None

    new_seen = seen | {val_id}

    if isinstance(val, (list, tuple, set)):
        return [_make_serializable(x, new_seen) for x in val]
    elif isinstance(val, dict):
        return {k: _make_serializable(v, new_seen) for k, v in val.items()}
    elif hasattr(val, "model_dump") or (hasattr(val, "dict") and callable(val.dict)):
        if hasattr(val, "model_dump"):
            data = val.model_dump()
        else:
            data = val.dict()

        # Check if it has SQLAlchemy relationships loaded
        try:
            from sqlalchemy import inspect as sqlalchemy_inspect
            mapper = sqlalchemy_inspect(val.__class__)
            relationships = mapper.relationships.keys()
            for rel in relationships:
                if rel in val.__dict__:
                    data[rel] = val.__dict__[rel]
        except Exception:
            pass
        return _make_serializable(data, new_seen)
    elif hasattr(val, "__dict__"):
        return _make_serializable({k: v for k, v in val.__dict__.items() if not k.startswith("_")}, new_seen)
    return val


        