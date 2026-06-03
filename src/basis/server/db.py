from functools import wraps
from string import Formatter
from fastapi import Depends, Request
from sqlmodel import Session

class DBAppMixin(object):
    def expose(self, url:str, method:str="GET", one:bool=False):
        def expose_decorator(modelcls):
            def wrapper(request:Request, session: Session = Depends(self.get_session)):

                #parsed_url = list(Formatter().parse(url))
                #fnames = [fname for _, fname, _, _ in parsed_url if fname is not None]

                expressions = []

                for i, (fname, fvalue) in enumerate(request.path_params.items()):
                    if hasattr(modelcls, fname):
                        field = getattr(modelcls, fname)
                        is_primary_key = modelcls.model_fields[fname].primary_key

                        expression = (field == fvalue)
                        
                        expressions.append(expression)
                
                from sqlmodel import select, delete


                if method == "GET":
                    select_statement = select(modelcls).where(*expressions)

                    print(request.path_params)

                    results = session.exec(select_statement)

                    if one:
                        result = results.one()
                    else:
                        result = results.all()
                    
                    return result

                elif method == "DELETE":
                    delete_statement = delete(modelcls).where(*expressions)
                    #session.execute(delete_statement)
                    #session.commit()

                elif method == "POST":
                    pass
                    

            self.add_api_route(url, wrapper, methods=[method])

            return modelcls

        return expose_decorator

        