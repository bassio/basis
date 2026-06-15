import inspect
from fastapi import Depends, Request, HTTPException
from sqlmodel import Session, select, delete
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy import inspect as sqlalchemy_inspect

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


def create_expose_wrapper(modelcls, method: str = "GET", one: bool = False, relations:list[str]|None=None):
    """
    Creates a FastAPI route handler for a model class based on the method.
    """
    from basis.shared.db import _make_serializable
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
                return _make_serializable(res)
            else:
                return [_make_serializable(x) for x in results.all()]
            
        return get_wrapper

    elif method == "POST":
        def post_wrapper(data: modelcls, session: Session = Depends(get_db_session)):
            session.add(data)
            session.commit()
            session.refresh(data)
            return _make_serializable(data)
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
            return _make_serializable(db_record)
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
                return {"detail": "Deleted successfully", "record": _make_serializable(db_record)}
            else:
                db_records = results.all()
                if not db_records:
                    raise HTTPException(status_code=404, detail="No matching records found to delete")
                for db_record in db_records:
                    session.delete(db_record)
                session.commit()
                return {"detail": f"Deleted {len(db_records)} records successfully", "records": [_make_serializable(db_record) for db_record in db_records]}
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
        from sqlmodel import SQLModel
        SQLModel.metadata.create_all(engine)


class DBAppMixin(ModelRegistryMixin):
    pass
