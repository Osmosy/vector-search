"""Контракт плагина Hermes: инструменты, ответы и отсутствие ложных маркеров сбоя."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "integrations" / "hermes-plugin" / "__init__.py"


@pytest.fixture
def plugin(monkeypatch, tmp_path):
    monkeypatch.setenv("VSEARCH_LEDGER", str(tmp_path / "ledger.jsonl"))
    monkeypatch.setenv("VSEARCH_SRC", str(Path(__file__).resolve().parents[1] / "src"))
    spec = importlib.util.spec_from_file_location("vsearch_hermes_plugin", PLUGIN)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeCtx:
    def __init__(self) -> None:
        self.tools: list[str] = []

    def register_tool(self, **kwargs) -> None:
        self.tools.append(kwargs["name"])


def test_registers_three_tools(plugin) -> None:
    ctx = FakeCtx()
    plugin.register(ctx)
    assert ctx.tools == ["vsearch_fetch", "vsearch_check", "vsearch_status"]


def test_success_payload_has_no_failure_markers(plugin, tmp_path) -> None:
    # Hermes считает ответ сбоем, если в первых 500 символах есть "error"/"failed".
    from vsearch.ledger import Ledger

    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.add(url="https://a.example/x", status=200, content_type="text/html",
               text="Текст страницы. " * 50)

    status = plugin.vsearch_status({})
    assert '"failed"' not in status[:500].lower()
    assert '"error"' not in status[:500].lower()
    assert json.loads(status)["ok"] is True

    dossier = {
        "questions": ["текст страницы"],
        "claims": [{"id": 1, "text": "текст страницы", "source_ids": [1],
                    "quote": "Текст страницы. Текст страницы."}],
        "sufficiency": {"answered": True, "gaps": []},
    }
    checked = plugin.vsearch_check({"dossier": dossier})
    assert '"error"' not in checked[:500].lower()
    assert json.loads(checked)["ok"] is True


def test_failed_read_returns_ok_false(plugin) -> None:
    # Несуществующий домен: чтение обязано вернуть отказ, а не упасть.
    result = json.loads(plugin.vsearch_fetch({"url": "http://127.0.0.1/x"}))
    assert result["ok"] is False
    assert "error" in result


def test_check_rejects_bad_sufficiency(plugin, tmp_path) -> None:
    from vsearch.ledger import Ledger

    Ledger(tmp_path / "ledger.jsonl").add(
        url="https://a.example/x", status=200, content_type="text/html", text="Текст. " * 60
    )
    dossier = {
        "questions": ["x"],
        "claims": [{"id": 1, "text": "x", "source_ids": [1], "quote": "Текст. Текст. Текст."}],
        "sufficiency": {"answered": True, "gaps": ["не хватает"]},
    }
    result = json.loads(plugin.vsearch_check({"dossier": dossier}))
    assert result["ok"] is False
    assert any("противоречие" in p for p in result["problems"])
