from suitest_lifecycle.llm_bridge import ChainedLlmClient, SamplingLlmClient


class _StubClient:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.calls = 0

    def _complete(self, prompt, *, system=None, max_tokens=4096):
        self.calls += 1
        return self.answer


def test_chain_uses_first_client_when_it_answers() -> None:
    first, second = _StubClient("dari-sampling"), _StubClient("dari-bridge")
    chain = ChainedLlmClient([first, second])
    assert chain._complete("p") == "dari-sampling"
    assert second.calls == 0


def test_chain_falls_back_on_empty_answer() -> None:
    first, second = _StubClient(""), _StubClient("dari-bridge")
    chain = ChainedLlmClient([first, second])
    assert chain._complete("p") == "dari-bridge"
    assert first.calls == 1 and second.calls == 1


def test_sampling_client_returns_empty_on_error(monkeypatch) -> None:
    from suitest_lifecycle import sampling

    def _boom(prompt, **kwargs):
        raise sampling.SamplingError("timeout")

    monkeypatch.setattr(sampling, "create_message", _boom)
    client = SamplingLlmClient()
    assert client._complete("p") == ""  # konvensi: "" = gagal, biar chain lanjut


def test_chain_has_llm_capability_methods() -> None:
    chain = ChainedLlmClient([_StubClient("[]")])
    # method capability warisan base harus ada (dipakai orchestrator/exporter)
    assert hasattr(chain, "propose_edge_cases")
    assert hasattr(chain, "generate_frontend_body")


def test_resolve_llm_prefers_sampling_when_client_supports(monkeypatch) -> None:
    from suitest_lifecycle import llm_bridge, mcp_server

    monkeypatch.setattr(mcp_server, "client_supports_sampling", lambda: True)
    monkeypatch.setattr(
        llm_bridge, "resolve_remote", lambda config: llm_bridge.RemoteLlmClient("http://x", "t")
    )
    client = llm_bridge.resolve_llm(config=None)
    assert isinstance(client, llm_bridge.ChainedLlmClient)
    assert isinstance(client._clients[0], llm_bridge.SamplingLlmClient)


def test_resolve_llm_without_sampling_or_bridge_returns_none(monkeypatch) -> None:
    from suitest_lifecycle import llm_bridge, mcp_server

    monkeypatch.setattr(mcp_server, "client_supports_sampling", lambda: False)
    monkeypatch.setattr(llm_bridge, "resolve_remote", lambda config: None)
    assert llm_bridge.resolve_llm(config=None) is None


def test_describe_llm_source() -> None:
    from suitest_lifecycle.llm_bridge import (
        ChainedLlmClient,
        RemoteLlmClient,
        SamplingLlmClient,
        describe_llm_source,
    )

    sampler = SamplingLlmClient()
    sampler.last_model = "claude-fable-5"
    assert describe_llm_source(sampler) == {"llm_source": "sampling", "model": "claude-fable-5"}
    assert describe_llm_source(RemoteLlmClient("http://x", "t")) == {
        "llm_source": "bridge",
        "model": None,
    }
    assert describe_llm_source(None) == {"llm_source": "deterministic", "model": None}
    chain = ChainedLlmClient([sampler])
    assert describe_llm_source(chain)["llm_source"] == "sampling"
