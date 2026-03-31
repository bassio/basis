from dataclasses import dataclass
from typing import Any

@dataclass
class Binding(object):
    component_instance:"Component"
    node:object

    @property
    def component_class(self):
        return self.component_instance.__class__

@dataclass
class SelfBinding(Binding):
    ...

@dataclass
class TextBinding(Binding):
    content:str
    fields:list[str]


@dataclass
class AttributeBinding(Binding):
    attr:str
    content:str
    fields:list[str]
    

@dataclass
class KeyedLoopBinding(Binding):
    loop_target: str
    loop_source: str
    key: str
    element: object | Any
    clone: object | Any

@dataclass
class ModelBinding(Binding):
    field: str

    @property
    def fields(self):
        return [self.field]

@dataclass
class IfBinding(Binding):
    expr: str
    anchor: object
    is_visible: bool
    fields: list
    

@dataclass
class EventBinding(Binding):
    event:str
    target_fn:str

    @property
    def element(self):
        return self.node

    @property
    def fields(self):
        return [self.target_fn]
    

@dataclass
class ChildBinding(Binding):
    childclass:str
    

