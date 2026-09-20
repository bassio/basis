import inspect
from fastapi import Depends, Request, HTTPException

# The DB layer is an optional extra (``basis-framework[db]``): a plain install
# must still import the app/plugin mixins, so a missing sqlmodel degrades to an
# actionable error where the DB is actually USED rather than an ImportError here.
try:
    from sqlmodel import Session, select, delete, SQLModel
    from sqlalchemy.orm import joinedload, selectinload
    from sqlalchemy import inspect as sqlalchemy_inspect
except ImportError as exc:
    _DB_IMPORT_ERROR: ImportError | None = exc
    Session = select = delete = SQLModel = None
    joinedload = selectinload = sqlalchemy_inspect = None
else:
    _DB_IMPORT_ERROR = None

from basis.shared.context import db_session_var
from basis.shared.serialization import register_serializer


def _require_db() -> None:
    """Raise an actionable error when the optional DB dependencies are absent."""
    if _DB_IMPORT_ERROR is not None:
        raise RuntimeError(
            "The database layer needs the optional 'db' extra — install it with "
            "`uv add 'basis-framework[db]'` (or `pip install sqlmodel`)."
        ) from _DB_IMPORT_ERROR


if _DB_IMPORT_ERROR is None:
    @register_serializer(for_type=SQLModel)
    def _serialize_sqlmodel(obj):
        """Serialize a SQLModel record: model_dump plus any loaded relationships.

        Registered at the DB layer (not in core ``serialization.py``) so the shared
        serializer stays free of sqlalchemy/sqlmodel — the "db teaches the framework
        how to serialize its models" plugin pattern. The generic ``model_dump``
        fallback in :func:`~basis.shared.serialization.jsonable` covers models even
        without this handler.
        """
        data = obj.model_dump()
        try:
            mapper = sqlalchemy_inspect(obj.__class__)
            for rel in mapper.relationships.keys():
                if rel in obj.__dict__:
                    data[rel] = obj.__dict__[rel]
        except Exception:
            pass
        return data


async def get_db_session(request: Request):
    app = request.app
    if not hasattr(app, "get_session") or app.get_session is None:
        raise RuntimeError("No database session getter registered on Basis app.")
    
    get_session_func = app.get_session
    
    if inspect.isgeneratorfunction(get_session_func):
        gen = get_session_func()
        try:
            yield next(gen)
        finally:
            try:
                next(gen)
            except StopIteration:
                pass
    elif inspect.isasyncgenfunction(get_session_func):
        async for session in get_session_func():
            yield session
    else:
        res = get_session_func()
        if hasattr(res, "__enter__"):
            with res as session:
                yield session
        elif hasattr(res, "__aenter__"):
            async with res as session:
                yield session
        else:
            yield res


class RequestDBSession:
    """The request's database session, bound to ``db_session_var`` for the duration.

    Bound by the two dispatch entry points — ``render_page`` and the action
    handler — before anything else runs, so a store's ``apply_request`` hook and a
    guard read the *same* session without either of them opening one of its own,
    and nothing can hold a connection open past its request.

    Binding is driven through :func:`get_db_session`, the framework's one
    description of what ``app.get_session`` may be, so every shape it accepts
    works here too rather than a hand-rolled subset silently binding the wrong
    object.

    An app with no session getter binds nothing and stays usable: rendering must
    not require a database. :func:`get_db_session` raises in that case, and the
    named error belongs to the code that actually needs a session, so it is only
    driven when there is a getter to drive.
    """

    def __init__(self, request):
        self._request = request
        self._token = None
        self._generator = None

    async def __aenter__(self) -> "RequestDBSession":
        get_session = getattr(getattr(self._request, "app", None), "get_session", None)
        if get_session is None:
            return self
        self._generator = get_db_session(self._request)
        session = await anext(self._generator)
        if session is not None:
            self._token = db_session_var.set(session)
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._token is not None:
            db_session_var.reset(self._token)
            self._token = None
        if self._generator is not None:
            await self._generator.aclose()
            self._generator = None


def create_expose_wrapper(modelcls, method: str = "GET", one: bool = False, relations:list[str]|None=None):
    """
    Creates a FastAPI route handler for a model class based on the method.
    """
    _require_db()
    from basis.shared.serialization import jsonable
    method = method.upper()

    if method == "GET":
        def get_wrapper(request: Request, session: Session = Depends(get_db_session)):
            expressions = []
            for fname, fvalue in request.path_params.items():
                if hasattr(modelcls, fname):
                    field = getattr(modelcls, fname)
                    expressions.append(field == fvalue)
            
            for fname, fvalue in request.query_params.items():
                if hasattr(modelcls, fname):
                    field = getattr(modelcls, fname)
                    expressions.append(field == fvalue)

            
            options = []

            if relations and len(relations) > 0:
                for rel in relations:
                    # Inspect the relationship attribute on your model class
                    rel_prop = sqlalchemy_inspect(modelcls).relationships[rel]
                    relation = getattr(modelcls, rel)
                    if rel_prop.direction.name in ("ONETOMANY", "MANYTOMANY"):
                        options.append(selectinload(relation))
                    elif rel_prop.direction.name == "MANYTOONE":
                        options.append(joinedload(relation))

                select_statement = select(modelcls).options(*options).where(*expressions)
                results = session.exec(select_statement)
            
            else:
                select_statement = select(modelcls).where(*expressions)
                results = session.exec(select_statement)
            
            if one:
                res = results.first()
                if res is None:
                    raise HTTPException(status_code=404, detail="Record not found")
                return jsonable(res)
            else:
                return [jsonable(x) for x in results.all()]
            
        return get_wrapper

    elif method == "POST":
        def post_wrapper(data: modelcls, session: Session = Depends(get_db_session)):
            session.add(data)
            session.commit()
            session.refresh(data)
            return jsonable(data)
        return post_wrapper

    elif method == "PUT" or method == "PATCH":
        def put_wrapper(request: Request, data: modelcls, session: Session = Depends(get_db_session)):
            expressions = []
            for fname, fvalue in request.path_params.items():
                if hasattr(modelcls, fname):
                    field = getattr(modelcls, fname)
                    expressions.append(field == fvalue)
            
            if not expressions:
                raise HTTPException(status_code=400, detail="Missing path parameters to identify the record to update")
            
            select_statement = select(modelcls).where(*expressions)
            results = session.exec(select_statement)
            db_record = results.first()
            if db_record is None:
                raise HTTPException(status_code=404, detail="Record not found")
            
            # Update fields excluding unset (allows partial updates / PATCH behavior)
            update_data = data.model_dump(exclude_unset=True) if hasattr(data, "model_dump") else data.dict(exclude_unset=True)
            for key, value in update_data.items():
                setattr(db_record, key, value)
            
            session.add(db_record)
            session.commit()
            session.refresh(db_record)

            return jsonable(db_record)
            
        return put_wrapper

    elif method == "DELETE":
        def delete_wrapper(request: Request, session: Session = Depends(get_db_session)):
            expressions = []
            for fname, fvalue in request.path_params.items():
                if hasattr(modelcls, fname):
                    field = getattr(modelcls, fname)
                    expressions.append(field == fvalue)
            
            if not expressions:
                raise HTTPException(status_code=400, detail="Missing path parameters to identify the record to delete")
            
            select_statement = select(modelcls).where(*expressions)
            results = session.exec(select_statement)
            
            if one:
                db_record = results.first()
                if db_record is None:
                    raise HTTPException(status_code=404, detail="Record not found")
                session.delete(db_record)
                session.commit()
                return {"detail": "Deleted successfully", "record": jsonable(db_record)}
            else:
                db_records = results.all()
                if not db_records:
                    raise HTTPException(status_code=404, detail="No matching records found to delete")
                for db_record in db_records:
                    session.delete(db_record)
                session.commit()
                return {"detail": f"Deleted {len(db_records)} records successfully", "records": [jsonable(db_record) for db_record in db_records]}
        return delete_wrapper
    
    else:
        raise ValueError(f"Unsupported HTTP method for expose: {method}")


class ModelRegistryMixin(object):
    def model(self, modelcls=None):
        """
        Decorator to register a SQLModel data model on this plugin or app.
        Can be used as @plugin.model or @plugin.model().
        """
        def decorator(cls):
            if not hasattr(self, "models"):
                self.models = set()
            self.models.add(cls)
            return cls

        if modelcls is not None:
            return decorator(modelcls)
        return decorator

    def expose(self, url: str, method: str = "GET", one: bool = False, relations: list[str]|None = None):
        """
        Decorator to register a SQLModel data model and expose it as a REST endpoint.
        """
        def expose_decorator(modelcls):
            if not hasattr(modelcls, "__endpoints__"):
                modelcls.__endpoints__ = {}
            
            prefix = getattr(self, "prefix", "")
            full_url = url
            if prefix:
                full_url = f"{prefix.rstrip('/')}/{url.lstrip('/')}"
            
            modelcls.__endpoints__[(method.upper(), one)] = full_url

            if not hasattr(self, "models"):
                self.models = set()
            self.models.add(modelcls)

            wrapper = create_expose_wrapper(modelcls, method=method, one=one, relations=relations)

            if hasattr(self, "add_api_route"):
                # Basis app
                self.add_api_route(url, wrapper, methods=[method])
            elif hasattr(self, "router"):
                # BasisPlugin
                self.router.add_api_route(url, wrapper, methods=[method])
            else:
                raise RuntimeError(f"Cannot expose model on object of type {type(self)}")

            return modelcls

        return expose_decorator

    def create_db_and_tables(self, engine):
        """
        Utility to create database tables for all models registered on this app/plugin.
        """
        _require_db()
        SQLModel.metadata.create_all(engine)


class DBAppMixin(ModelRegistryMixin):
    pass
