import pytest
from unittest.mock import MagicMock
from sqlmodel import SQLModel, Field
from typing import Optional
from basis.shared.bindings import FormModelBinding
from basis.shared.component import Component
from basis.shared.validation import ValidationError, validate_model

class DummyVisit(SQLModel):
    id: Optional[int] = Field(default=None, primary_key=True)
    patient_id: int = Field(default=0, ge=1)
    notes: str = Field(default="", min_length=5)

class DummyComponent(Component):
    __tag__ = "dummy-comp"
    
    new_visit: DummyVisit = None
    new_visit_errors: dict = None
    
    def template(self):
        """
        <form bind="{new_visit}">
            <input type="text" name="notes" />
            <input type="number" name="patient_id" />
            <button type="submit">Submit</button>
        </form>
        """
        pass

def test_form_model_binding_compilation():
    comp = DummyComponent.initialize(MagicMock())
    
    # Check that FormModelBinding blueprint exists in blueprints
    form_blueprints = [bp for bp in comp.__class__.__binding_blueprints__ if bp.binding_class == FormModelBinding]
    assert len(form_blueprints) == 1
    blueprint = form_blueprints[0]
    assert blueprint.kwargs['target_expression'] == 'new_visit'
    assert blueprint.kwargs['validate_on'] == 'input'

class MockNode:
    def __init__(self, tag_name="form", attrs=None):
        self.tagName = tag_name
        self.attributes = attrs or {}
        self.childNodes = []
        self._listeners = {}

    def getAttribute(self, attr):
        return self.attributes.get(attr, "")

    def hasAttribute(self, attr):
        return attr in self.attributes

    def addEventListener(self, event, handler):
        self._listeners[event] = handler

    def removeEventListener(self, event, handler):
        if event in self._listeners:
            del self._listeners[event]

    def dispatchEvent(self, event):
        pass

class MockEvent:
    def __init__(self, target):
        self.target = target
        self._prevented = False

    def preventDefault(self):
        self._prevented = True

def test_form_model_binding_interaction():
    comp_instance = DummyComponent.initialize(MagicMock())
    comp_instance.new_visit = DummyVisit(patient_id=1, notes="Initial value")
    comp_instance.new_visit_errors = {}
    
    form_node = MockNode("form", {"bind": "{new_visit}"})
    notes_input = MockNode("input", {"name": "notes", "type": "text"})
    notes_input.value = "Initial value"
    notes_input.form = form_node
    
    patient_id_input = MockNode("input", {"name": "patient_id", "type": "number"})
    patient_id_input.value = "1"
    patient_id_input.form = form_node
    
    form_node.childNodes = [notes_input, patient_id_input]
    
    # Create the binding manually
    binding = FormModelBinding(
        component_instance=comp_instance,
        node=form_node,
        ast_trees={},
        target_expression="new_visit",
        validate_on="input"
    )
    binding.activate()  # lifecycle: attach listeners (from_blueprint is pure)

    # Verify listeners are attached
    assert "input" in form_node._listeners
    assert "blur" in form_node._listeners
    assert "submit" in form_node._listeners
    
    # Bypass init validation to set an invalid value directly on the model
    comp_instance.new_visit.notes = "abc"
    
    # Simulate submitting invalid form
    submit_event = MockEvent(form_node)
    form_node._listeners["submit"](submit_event)
    assert submit_event._prevented is True
    assert comp_instance.new_visit_errors.get("notes") is not None
    
    # Set it to a valid value
    notes_input.value = "Longer notes"
    event = MockEvent(notes_input)
    form_node._listeners["input"](event)
    
    # Verify error cleared and value updated on model
    assert "notes" not in comp_instance.new_visit_errors
    assert comp_instance.new_visit.notes == "Longer notes"
    
    # Simulate typing invalid string in numeric field (patient_id = -1)
    patient_id_input.value = "-1"
    event = MockEvent(patient_id_input)
    form_node._listeners["input"](event)
    assert comp_instance.new_visit_errors.get("patient_id") is not None
    
    # Correct it to "5"
    patient_id_input.value = "5"
    form_node._listeners["input"](event)
    assert "patient_id" not in comp_instance.new_visit_errors
    assert comp_instance.new_visit.patient_id == 5
    
    # Test programmatic/two-way binding: update model and run binding.update()
    comp_instance.new_visit.notes = "Programmatic update"
    binding.update()
    assert notes_input.value == "Programmatic update"
    
    # Simulate submitting valid form
    submit_event = MockEvent(form_node)
    form_node._listeners["submit"](submit_event)
    assert submit_event._prevented is False
