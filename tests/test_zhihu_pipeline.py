"""Zhihu pipeline helpers and storage tests."""

from on1y.ingestion.enqueue import enqueue_url
from on1y.models.enums import ContentType, ExtractStatus, SourceType
from on1y.models.raw import RawItemCreate
from on1y.utils.platform import PLATFORM_ZHIHU


def test_claim_next_pending_for_platform_zhihu(storage) -> None:
    enqueue_url(storage, "https://example.com/generic", source=SourceType.MANUAL)
    enqueue_url(
        storage,
        "https://www.zhihu.com/question/1/answer/2",
        source=SourceType.RSS,
    )
    pending = storage.claim_next_pending_for_platform(PLATFORM_ZHIHU)
    assert pending is not None
    assert "zhihu.com" in pending.url
    storage.mark_pending_done(pending.id)

    generic = storage.claim_next_pending()
    assert generic is not None
    assert generic.url == "https://example.com/generic"


def test_count_pending_for_platform(storage) -> None:
    enqueue_url(storage, "https://www.zhihu.com/p/1", source=SourceType.RSS)
    enqueue_url(storage, "https://zhuanlan.zhihu.com/p/2", source=SourceType.RSS)
    assert storage.count_pending_for_platform(PLATFORM_ZHIHU) == 2


def test_list_raw_ids_without_distill_platform_filter(storage) -> None:
    storage.upsert_raw_item(
        RawItemCreate(
            url="https://www.zhihu.com/question/1/answer/1",
            platform=PLATFORM_ZHIHU,
            source=SourceType.MANUAL,
            raw_title="Zhihu",
            body_text="这是一段足够长的知乎正文内容用于测试蒸馏筛选逻辑。" * 3,
            content_type=ContentType.ARTICLE,
            extract_status=ExtractStatus.OK,
        )
    )
    storage.upsert_raw_item(
        RawItemCreate(
            url="https://example.com/other",
            platform="generic",
            source=SourceType.MANUAL,
            raw_title="Other",
            body_text="Another long enough article body for distill filter testing here. " * 3,
            content_type=ContentType.ARTICLE,
            extract_status=ExtractStatus.OK,
        )
    )
    ids = storage.list_raw_ids_without_distill(limit=10, platform=PLATFORM_ZHIHU)
    assert len(ids) == 1
    raw = storage.get_raw_by_id(ids[0])
    assert raw is not None
    assert raw.platform == PLATFORM_ZHIHU


def test_parse_zhihu_follow_line() -> None:
    from on1y.ingestion.zhihu_feeds import parse_follow_line

    assert parse_follow_line("activities:foo-bar") == ("activities", "foo-bar")
    assert parse_follow_line("collection:12345") == ("collection", "12345")
    assert parse_follow_line("https://www.zhihu.com/people/alice/activities") == (
        "activities",
        "alice",
    )
    assert parse_follow_line("bob-user") == ("activities", "bob-user")
    assert parse_follow_line("# comment") is None


def test_is_playwright_antibot_error() -> None:
    from on1y.browser.playwright_client import is_playwright_antibot_error

    assert is_playwright_antibot_error("安全验证 page")
    assert is_playwright_antibot_error("blocked automated browser")
    assert not is_playwright_antibot_error("network timeout")
