"""Tests for GUI configuration initialization and migration."""

import configparser
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


@pytest.fixture
def gui_utils(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    platformdirs_stub = ModuleType("platformdirs")
    platformdirs_stub.user_config_dir = lambda _app_name: str(config_dir)
    monkeypatch.setitem(sys.modules, "platformdirs", platformdirs_stub)

    utils_path = Path(__file__).resolve().parents[2] / "src/gui/utils.py"
    spec = importlib.util.spec_from_file_location("gui_utils_for_test", utils_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_load_config_repairs_an_empty_config_file(gui_utils):
    config_path = gui_utils.get_app_config_dir() / gui_utils.CONFIG_FILE
    config_path.write_text("", encoding="utf-8")

    config = gui_utils.load_config()

    assert config.get("General", "language") == "zh"
    assert config.get("General", "last_image_path") == ""
    assert config.get("AdvancedSettings", "log_level") == "INFO"

    persisted = configparser.ConfigParser()
    persisted.read(config_path, encoding="utf-8")
    assert persisted.has_section("General")
    assert persisted.has_section("AdvancedSettings")


def test_load_config_preserves_existing_values_while_adding_defaults(gui_utils):
    config_path = gui_utils.get_app_config_dir() / gui_utils.CONFIG_FILE
    config_path.write_text("[AdvancedSettings]\nlog_level = DEBUG\n", encoding="utf-8")

    config = gui_utils.load_config()

    assert config.get("AdvancedSettings", "log_level") == "DEBUG"
    assert config.get("AdvancedSettings", "loader_address") == "0x80360000"
    assert config.get("General", "language") == "zh"
