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
