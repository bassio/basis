import dataclasses
import re
import datetime
from typing import Any, Union, get_origin, get_args

try:
    # Handle Python 3.10+ UnionType if available
    from types import UnionType
except ImportError:
    UnionType = Union

class ValidationError(Exception):
    def __init__(self, errors: list[dict]):
        self._errors = errors
        super().__init__(str(errors))
        
    def errors(self) -> list[dict]:
        return self._errors

def _is_none_type(t: Any) -> bool:
    return t is type(None) or t is None

def _extract_types(field_type: Any) -> list[Any]:
    origin = get_origin(field_type)
    if origin in (Union, UnionType):
        return [t for t in get_args(field_type) if not _is_none_type(t)]
    return [field_type]

def _allows_none(field_type: Any) -> bool:
    origin = get_origin(field_type)
    if origin in (Union, UnionType):
        return any(_is_none_type(t) for t in get_args(field_type))
    return _is_none_type(field_type)

def coerce_value(value: Any, field_type: Any) -> tuple[Any, str | None]:
    if value is None or value == "":
        if _allows_none(field_type):
            return None, None
        if field_type is str:
            return "", None
        return None, "Field is required"

    types = _extract_types(field_type)
    if not types:
        return value, None

    last_err = None
    for t in types:
        if t is Any:
            return value, None
            
        if t is str:
            return str(value), None
            
        if t is int:
            try:
                if isinstance(value, str) and "." in value:
                    return int(float(value)), None
                return int(value), None
            except (ValueError, TypeError):
                last_err = "Input should be a valid integer"
                continue
                
        if t is float:
            try:
                return float(value), None
            except (ValueError, TypeError):
                last_err = "Input should be a valid number"
                continue
                
        if t is bool:
            if isinstance(value, str):
                val_lower = value.lower()
                if val_lower in ("true", "1", "yes", "on"):
                    return True, None
                if val_lower in ("false", "0", "no", "off", ""):
                    return False, None
            return bool(value), None
            
        if t is datetime.datetime:
            if isinstance(value, datetime.datetime):
                return value, None
            try:
                if isinstance(value, str) and not value.strip():
                    return None, None
                return datetime.datetime.fromisoformat(value), None
            except (ValueError, TypeError):
                last_err = "Input should be a valid datetime"
                continue
                
        if t is datetime.date:
            if isinstance(value, datetime.date):
                return value, None
            try:
                if isinstance(value, str) and not value.strip():
                    return None, None
                return datetime.date.fromisoformat(value), None
            except (ValueError, TypeError):
                last_err = "Input should be a valid date"
                continue

        try:
            return t(value), None
        except Exception:
            last_err = f"Input should be of type {t.__name__}"
            continue

    return None, last_err or "Invalid type"

def get_model_field_info(model_class: Any, field_name: str) -> tuple[Any, dict] | None:
    # 1. Check if it's a Pydantic/SQLModel class
    if hasattr(model_class, "model_fields"):
        if field_name not in model_class.model_fields:
            return None
        field_info = model_class.model_fields[field_name]
        metadata = {}
        for attr in ("gt", "ge", "lt", "le", "min_length", "max_length", "pattern", "multiple_of"):
            val = getattr(field_info, attr, None)
            if val is not None:
                metadata[attr] = val
        if hasattr(field_info, "metadata"):
            for m in field_info.metadata:
                for attr in ("gt", "ge", "lt", "le", "min_length", "max_length", "pattern", "multiple_of"):
                    val = getattr(m, attr, None)
                    if val is not None:
                        metadata[attr] = val
        return field_info.annotation, metadata

    # 2. Check if it's a dataclass
    elif dataclasses.is_dataclass(model_class):
        fields_dict = {f.name: f for f in dataclasses.fields(model_class)}
        if field_name not in fields_dict:
            return None
        field = fields_dict[field_name]
        return field.type, getattr(field, "metadata", {}) or {}

    return None

def validate_field(model_class: Any, field_name: str, value: Any) -> tuple[Any, str | None]:
    info = get_model_field_info(model_class, field_name)
    if info is None:
        return value, None

    field_type, metadata = info

    # 1. Coerce value to expected type
    coerced, err = coerce_value(value, field_type)
    if err:
        return None, err

    if coerced is None:
        return None, None

    # 2. Check Constraints
    if isinstance(coerced, str):
        if "min_length" in metadata and len(coerced) < metadata["min_length"]:
            return None, f"String should have at least {metadata['min_length']} characters"
        if "max_length" in metadata and len(coerced) > metadata["max_length"]:
            return None, f"String should have at most {metadata['max_length']} characters"
        if "pattern" in metadata:
            pattern = metadata["pattern"]
            if not re.match(pattern, coerced):
                return None, f"String should match pattern '{pattern}'"

    if isinstance(coerced, (int, float)):
        if "gt" in metadata and not (coerced > metadata["gt"]):
            return None, f"Number should be greater than {metadata['gt']}"
        if "ge" in metadata and not (coerced >= metadata["ge"]):
            return None, f"Number should be greater than or equal to {metadata['ge']}"
        if "lt" in metadata and not (coerced < metadata["lt"]):
            return None, f"Number should be less than {metadata['lt']}"
        if "le" in metadata and not (coerced <= metadata["le"]):
            return None, f"Number should be less than or equal to {metadata['le']}"
        if "multiple_of" in metadata and coerced % metadata["multiple_of"] != 0:
            return None, f"Number should be a multiple of {metadata['multiple_of']}"

    return coerced, None

def validate_model(model_instance: Any) -> None:
    model_class = model_instance.__class__
    if hasattr(model_class, "model_fields"):
        field_names = list(model_class.model_fields.keys())
    elif dataclasses.is_dataclass(model_class):
        field_names = [f.name for f in dataclasses.fields(model_class)]
    else:
        return

    errors = []
    for name in field_names:
        val = getattr(model_instance, name, None)
        coerced_val, err_msg = validate_field(model_class, name, val)
        if err_msg:
            errors.append({
                "type": "value_error",
                "loc": (name,),
                "msg": err_msg,
                "input": val
            })
        else:
            try:
                setattr(model_instance, name, coerced_val)
            except AttributeError:
                pass

    if errors:
        raise ValidationError(errors)
