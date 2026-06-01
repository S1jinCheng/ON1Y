"""Tests for Clash proxy rotation helpers."""

from on1y.utils.clash import _next_proxy


def test_next_proxy_cycles() -> None:
    nodes = ["DIRECT", "香港 A", "日本 B", "美国 C"]
    assert _next_proxy(nodes, "香港 A") == "日本 B"
    assert _next_proxy(nodes, "美国 C") == "香港 A"


def test_next_proxy_skips_direct() -> None:
    nodes = ["DIRECT", "节点1", "节点2"]
    assert _next_proxy(nodes, "节点1") == "节点2"
