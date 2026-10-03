import shutil
from pathlib import Path

import pytest

from navigator import config
from navigator.extract import llm

from .fake_llm import fake

FIX = Path(__file__).resolve().parent.parent / "fixtures"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    pack = tmp_path / "pack"
    shutil.copytree(FIX / "pack", pack)
    cfg = tmp_path / "config"
    shutil.copytree(config.ROOT / "config", cfg)
    monkeypatch.setattr(config, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(config, "CONFIG_DIR", cfg)
    monkeypatch.setattr(config, "LLM_MODE", "fake")
    import navigator.cli as cli
    monkeypatch.setattr(cli, "OUT", tmp_path / "out")
    monkeypatch.setattr(cli, "RULES_INTERNAL", tmp_path / "out" / "rules_internal.json")
    monkeypatch.setattr(cli, "ADDRS", tmp_path / "out" / "addresses_resolved.json")
    llm.set_fake(fake)
    yield tmp_path
    llm.set_fake(None)
