"""``ShellConfig`` / slug rules — P0 of INIT-SHELL-PLAN.md."""

from __future__ import annotations

import pytest

from basis.cli.init.config import (
    PARADIGM_APP,
    PARADIGM_SITE,
    ShellConfig,
    slugify,
)


# --- slugify --------------------------------------------------------------

def test_slugify_lowercases_and_replaces_dashes():
    assert slugify("My-App") == "my_app"


def test_slugify_replaces_invalid_chars_with_underscore():
    assert slugify("my app!") == "my_app_"


def test_slugify_prefixes_leading_digit():
    assert slugify("123app") == "_123app"


def test_slugify_whitespace_only_is_empty():
    assert slugify("   ") == ""


# --- defaults -------------------------------------------------------------

def test_default_config_is_minimal_but_loadable_app_workbench():
    cfg = ShellConfig(project_name="myapp")
    assert cfg.paradigm == PARADIGM_APP
    assert cfg.titlebar is True
    assert cfg.statusbar is True
    assert cfg.activitybar is True
    assert cfg.sidebar_left is True
    assert cfg.sidebar_right is False
    assert cfg.sidebar_left_collapsible == "none"
    assert cfg.demo is True
    assert cfg.example_store is True
    assert cfg.example_plugin is True
    assert cfg.use_db is False


def test_package_slug_property_uses_slugify():
    cfg = ShellConfig(project_name="My Great App")
    assert cfg.package_slug == "my_great_app"


# --- validation -----------------------------------------------------------

def test_validate_requires_project_name():
    with pytest.raises(ValueError, match="Project name is required"):
        ShellConfig(project_name="").validate()


def test_validate_rejects_unknown_paradigm():
    with pytest.raises(ValueError, match="Unknown shell paradigm"):
        ShellConfig(project_name="x", paradigm="terminal").validate()


def test_validate_rejects_unknown_collapsible_mode():
    with pytest.raises(ValueError, match="collapse mode"):
        ShellConfig(project_name="x", sidebar_left_collapsible="slide").validate()


def test_validate_rejects_unknown_theme():
    with pytest.raises(ValueError, match="Unknown theme"):
        ShellConfig(project_name="x", theme="sepia").validate()


def test_validate_accepts_site_with_workbench_flags_unused():
    # part flags valid only for the other paradigm are simply unused, not errors
    ShellConfig(project_name="x", paradigm=PARADIGM_SITE, titlebar=True).validate()


# --- flags round-trip -----------------------------------------------------

def test_from_flags_applies_provided_fields_only():
    cfg = ShellConfig.from_flags(project_name="myapp", sidebar_right=True)
    assert cfg.project_name == "myapp"
    assert cfg.sidebar_right is True
    assert cfg.titlebar is True  # untouched default


def test_from_flags_rejects_unknown_field():
    with pytest.raises(ValueError, match="Unknown shell config option"):
        ShellConfig.from_flags(project_name="x", nope=True)


def test_to_flags_from_flags_roundtrip():
    cfg = ShellConfig(project_name="demo", paradigm=PARADIGM_SITE, footer=False, theme="light")
    assert ShellConfig.from_flags(**cfg.to_flags()) == cfg
