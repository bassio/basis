# Forms & Validation

Basis provides a specialized binding system that makes working with forms and data models virtually boilerplate-free. Using `FormModelBinding`, you can bind an entire HTML `<form>` to an `SQLModel` or standard Python `dataclass`, and Basis will automatically handle two-way data sync, event interception, and model validation.

---

## 1. Binding a Form to a Model

To use form binding, apply the `bind="{model_instance}"` attribute to a `<form>` element.

When Basis sees `bind` on a `<form>`, it does **not** treat it as a simple value binding. Instead, it activates `FormModelBinding`, which recursively scans the form for any `<input>`, `<textarea>`, or `<select>` elements that have a `name` attribute.

```python
from basis.shared.component import Component
from basis.shared.db import SQLModel, Field

class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    username: str
    age: int

class UserProfileForm(Component):
    """
    <form bind="{user}" validate-on="input">
        <div>
            <label>Username:</label>
            <input type="text" name="username" />
            <span class="error" if="{user_errors.username}">{user_errors.username}</span>
        </div>
        
        <div>
            <label>Age:</label>
            <input type="number" name="age" />
            <span class="error" if="{user_errors.age}">{user_errors.age}</span>
        </div>
        
        <button type="submit">Save Profile</button>
    </form>
    """
    
    # Type hints are read by Basis to automatically instantiate the model 
    # if it doesn't exist yet!
    user: User
    
    # user_errors will be automatically created and populated by the form binding!
    
    async def submit(self):
        # By the time this runs, self.user is already updated and validated.
        print(f"Saving user {self.user.username}, age {self.user.age}")
```

### How it works:
1. **Auto-instantiation**: Basis uses the Python type hint (`user: User`) to know which model class to instantiate.
2. **Input matching**: The `<input name="username">` automatically binds to `self.user.username`.
3. **Event interception**: When the user types, the `input` event updates the model and triggers Pydantic/SQLModel type validation on that specific field.

---

## 2. Validation & The `{model}_errors` Dictionary

The framework automatically manages a reactive dictionary containing validation errors, named by appending `_errors` to your bound model variable. 

If you bind `<form bind="{user}">`, Basis maintains `{user_errors}`.
If you bind `<form bind="{registration}">`, Basis maintains `{registration_errors}`.

When a field fails validation (e.g., passing a string into an `int` field, or violating a Pydantic constraint), the error message is placed in the dictionary under the field's name (e.g. `user_errors.age = "Input should be a valid integer"`).

### Validation Timing (`validate-on`)

You can control when validation triggers using the `validate-on` attribute on the `<form>`:

- `validate-on="input"` (default): Validates on every keystroke.
- `validate-on="blur"`: Validates when an input loses focus.
- `validate-on="submit"`: Only validates when the user attempts to submit the form.

Regardless of this setting, validation **always** runs comprehensively when the `submit` event fires.

---

## 3. Form Submission

When a `<form bind="{model}">` is submitted:

1. Basis intercepts the `submit` event and calls `event.preventDefault()`.
2. It runs a full `validate_model(target_obj)` pass over all fields.
3. If errors are found, they populate `{model}_errors`, the DOM updates to show error messages, and submission halts.
4. If validation passes, you can handle the data knowing it perfectly conforms to your SQLModel definitions.
5. If the form has a `novalidate` attribute, validation on submit is bypassed.

---

## 4. Binding to Global Stores

You can also bind forms directly to models managed inside global stores using the `$store` syntax:

```html
<form bind="{$auth.user_profile}">
    <!-- Inputs automatically map to $auth.user_profile.username etc -->
    <input name="username" />
    <span if="{$auth.user_profile_errors.username}">
        {$auth.user_profile_errors.username}
    </span>
</form>
```

In this case, the errors dictionary is placed directly onto the store instance (`$auth.user_profile_errors`), making form validation state accessible anywhere in the application.
