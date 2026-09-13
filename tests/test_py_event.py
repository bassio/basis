"""Unit tests for ``basis.shared.js.py_event`` / ``PythonEventWrapper``.

The decorator is the payload half of the JS event boundary: a handler receives the raw JS
event unless it is wrapped, in which case a ``CustomEvent``'s ``detail`` becomes Python
data and an async handler is scheduled. Its inputs are faked here because a JS event is
whatever the browser hands over — any object with a ``detail``.
"""

import asyncio

from basis.shared.js import PythonEventWrapper, py_event


class FakeDetail:
    """A JS detail object: ``to_py()`` is the conversion the boundary performs."""

    def __init__(self, value):
        self.value = value

    def to_py(self):
        return self.value


class FakeEvent:
    """A ``CustomEvent``: a payload plus the properties handlers read off the event."""

    def __init__(self, detail=None, **props):
        if detail is not None:
            self.detail = detail
        self.type = props.pop("type", "click")
        for name, value in props.items():
            setattr(self, name, value)


def test_detail_becomes_python_for_a_positional_event():
    """The template-callback shape: ``handler(self, event)``."""
    seen = []

    @py_event
    def handler(component, event):
        seen.append((component, event.detail))

    handler("the component", FakeEvent(FakeDetail({"id": 7})))

    assert seen == [("the component", {"id": 7})]


def test_detail_becomes_python_for_a_keyword_event():
    """The binding shape: ``handler(event=...)``."""
    seen = []

    @py_event
    def handler(**kwargs):
        seen.append(kwargs["event"].detail)

    handler(event=FakeEvent(FakeDetail([1, 2, 3])))

    assert seen == [[1, 2, 3]]


def test_the_event_keeps_its_other_properties():
    seen = []

    @py_event
    def handler(event):
        seen.append((event.type, event.key))

    handler(FakeEvent(FakeDetail({}), type="keydown", key="Escape"))

    assert seen == [("keydown", "Escape")]


def test_an_event_without_detail_passes_through():
    """Plain DOM events carry no payload; the wrapper must not invent one."""
    seen = []

    @py_event
    def handler(event):
        seen.append(event)

    event = FakeEvent()

    handler(event)

    assert seen == [event]
    assert not isinstance(seen[0], PythonEventWrapper)


def test_a_detail_without_to_py_is_passed_as_is():
    seen = []

    @py_event
    def handler(event):
        seen.append(event.detail)

    handler(FakeEvent(detail="already python"))

    assert seen == ["already python"]


def test_an_already_wrapped_event_is_not_wrapped_twice():
    seen = []

    @py_event
    def handler(event):
        seen.append(event)

    wrapped = PythonEventWrapper(FakeEvent(FakeDetail({"a": 1})))
    handler(wrapped)

    assert seen == [wrapped]


def test_the_target_is_unwrapped_once_and_first():
    """Only the event argument is replaced — the component stays the component."""
    seen = []

    @py_event
    def handler(component, event):
        seen.append((component, type(event).__name__))

    handler("the component", FakeEvent(FakeDetail({})))

    assert seen == [("the component", "PythonEventWrapper")]


def test_wrapping_is_marked_so_it_is_not_reapplied():
    """``_create_function_proxy`` reads this to avoid stacking wrappers."""

    @py_event
    def handler(event):
        return None

    assert handler.__is_py_event__ is True


def test_an_async_handler_is_scheduled_not_dropped():
    """The browser is not waiting on a coroutine, so it has to be driven by the loop."""
    calls = []

    @py_event
    async def handler(event):
        calls.append(event.detail)

    async def scenario():
        handler(FakeEvent(FakeDetail({"done": True})))
        await asyncio.sleep(0)  # let the scheduled task run

    asyncio.run(scenario())

    assert calls == [{"done": True}]
