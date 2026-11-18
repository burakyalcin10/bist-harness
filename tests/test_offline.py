"""The harness runs without the internet and calls no cloud AI service.

An end-to-end harness run (the teacher as a fake model, every tool in process on the
synthetic snapshot) happens while a socket patch refuses every connection that does not
go to the loopback interface. A text search confirms that no cloud AI SDK is imported
anywhere in ``src/``.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from pathlib import Path

import pytest

from bist_harness.eval import run_eval
from bist_harness.finetune import questions as fq
from bist_harness.finetune.teacher import TeacherClient
from bist_harness.harness import machine

from .test_finetune_build import TODAY_RANGE, synthetic

SRC = Path(__file__).resolve().parents[1] / "src"
CLOUD_SDK = re.compile(
    r"^\s*(?:import|from)\s+"
    r"(openai|anthropic|google\.generativeai|google\.genai|cohere|mistralai)\b",
    re.MULTILINE,
)


class NetworkBlocked(OSError):
    pass


def _loopback(host) -> bool:
    if host in ("localhost", "", None):
        return True
    try:
        return ipaddress.ip_address(str(host).split("%")[0]).is_loopback
    except ValueError:  # a host name that is not localhost
        return False


@pytest.fixture
def no_network(monkeypatch):
    """Refuse every non-loopback connection and name lookup; record the attempts."""
    attempts = []
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def guard(address):
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(address, tuple) and not _loopback(host):
            attempts.append(host)
            raise NetworkBlocked(f"offline test: connection to a non-loopback host {host!r}")

    def connect(self, address):
        guard(address)
        return real_connect(self, address)

    def connect_ex(self, address):
        guard(address)
        return real_connect_ex(self, address)

    def getaddrinfo(host, *args, **kwargs):
        if not _loopback(host):
            attempts.append(host)
            raise NetworkBlocked(f"offline test: name lookup of {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    return attempts


def test_the_patch_refuses_remote_hosts_and_allows_loopback(no_network):
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("192.0.2.1", 80), timeout=1)  # TEST-NET-1, never routed
    with pytest.raises(NetworkBlocked):
        socket.getaddrinfo("example.com", 443)
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    try:
        client = socket.create_connection(server.getsockname(), timeout=1)
        client.close()
    finally:
        server.close()
    assert no_network == ["192.0.2.1", "example.com"]


@pytest.mark.parametrize("family", ["technical_reversal_dated", "price_summary"])
def test_a_full_harness_run_needs_no_network(no_network, tmp_path, family):
    with synthetic(tmp_path):
        question = next(
            q
            for q in fq.generate(4, today_range=TODAY_RANGE)
            # AKBNK: a synthetic stock the quality gate lets through
            if q.family == family and q.gold.intent.get("ticker") == "AKBNK"
        )
        teacher = TeacherClient(question.gold, question_id=question.question_id)
        analysis = machine.run_analysis(
            question.text, teacher, call_tool=run_eval._server_call_tool, today=question.today
        )
    assert no_network == []
    assert analysis.outcome  # the run reached an outcome
    assert any(record.turn == "tool_call" for record in teacher.turns)  # tools really ran
    assert any(record.turn == "explanation" for record in teacher.turns)


def test_no_cloud_ai_sdk_is_imported_in_src():
    found = [
        f"{path.relative_to(SRC)}: {match.group(1)}"
        for path in SRC.rglob("*.py")
        for match in CLOUD_SDK.finditer(path.read_text(encoding="utf-8"))
    ]
    assert found == []


def test_the_sdk_search_would_find_an_import():
    sample = "import json\nfrom openai import OpenAI\n    import anthropic\nimport cohere_like\n"
    assert [m.group(1) for m in CLOUD_SDK.finditer(sample)] == ["openai", "anthropic"]
