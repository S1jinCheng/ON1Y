from on1y.llm.client import resolve_chat_completions_url


def test_resolve_chat_completions_url_v1_suffix() -> None:
    assert (
        resolve_chat_completions_url("https://proxy.example.com/v1")
        == "https://proxy.example.com/v1/chat/completions"
    )


def test_resolve_chat_completions_url_deepseek_official() -> None:
    assert (
        resolve_chat_completions_url("https://api.deepseek.com")
        == "https://api.deepseek.com/chat/completions"
    )


def test_resolve_chat_completions_url_full_path() -> None:
    assert (
        resolve_chat_completions_url("https://proxy.example.com/v1/chat/completions")
        == "https://proxy.example.com/v1/chat/completions"
    )
