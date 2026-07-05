import threading

import pytest

from suitest_lifecycle import mcp_server
from suitest_lifecycle.sampling import SamplingError, create_message


def _fake_client(answer_text: str, model: str = "claude-fable-5"):
    """Jawab request sampling pertama yang server tulis, seperti client MCP."""

    def _respond(sent: dict) -> None:
        response = {
            "jsonrpc": "2.0",
            "id": sent["id"],
            "result": {
                "model": model,
                "role": "assistant",
                "content": {"type": "text", "text": answer_text},
            },
        }
        with mcp_server._client_response_event:
            mcp_server._client_responses[sent["id"]] = response
            mcp_server._client_response_event.notify_all()

    return _respond


def test_create_message_roundtrip(monkeypatch) -> None:
    sent_messages: list[dict] = []

    def _capture_write(message: dict) -> None:
        sent_messages.append(message)
        threading.Thread(target=_fake_client("HASIL"), args=(message,)).start()

    monkeypatch.setattr(mcp_server, "_write_message", _capture_write)

    result = create_message(prompt="halo", system="sys", max_tokens=100, timeout=5.0)

    assert result.text == "HASIL"
    assert result.model == "claude-fable-5"
    req = sent_messages[0]
    assert req["method"] == "sampling/createMessage"
    assert req["params"]["messages"][0]["content"]["text"] == "halo"
    assert req["params"]["systemPrompt"] == "sys"
    assert req["params"]["maxTokens"] == 100


def test_create_message_timeout(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "_write_message", lambda m: None)  # client bisu
    with pytest.raises(SamplingError, match="timeout"):
        create_message(prompt="halo", timeout=0.1)
