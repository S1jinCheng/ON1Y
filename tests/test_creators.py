from on1y.ingestion.rss import FeedConfig
from on1y.knowledge.creators import (
    bilibili_following_groups,
    creator_filter_sql,
    creator_key_from_feed,
    creator_key_from_feed_label,
    discover_twitter_author_groups,
    is_sidebar_creator_feed,
    is_subscription_feed,
    is_zhihu_collection_feed,
    normalize_twitter_author_url,
    subscription_feed_groups,
    twitter_author_key_from_url,
    zhihu_author_url,
)


def test_zhihu_person_key_from_feed_url_preserves_dot():
    feed = FeedConfig(
        url="http://127.0.0.1:12000/zhihu/people/activities/quanshi.zhang",
        label="zhihu-activities-quanshi-zhang",
    )
    assert creator_key_from_feed(feed) == "zhihu-person:quanshi.zhang"


def test_zhihu_collection_feed_not_sidebar_creator():
    feed = FeedConfig(
        url="http://127.0.0.1:12000/zhihu/collection/809894830",
        label="zhihu-collection-809894830",
    )
    assert is_zhihu_collection_feed(feed)
    assert not is_sidebar_creator_feed(feed)


def test_bilibili_following_groups_from_feeds(monkeypatch):
    from on1y.ingestion.rss import FeedConfig

    feeds = [
        FeedConfig(
            url="https://rsshub.app/bilibili/user/video/12345",
            label="bili-up-test-up",
            display_name="测试UP",
        )
    ]
    monkeypatch.setattr("on1y.knowledge.creators.load_feeds", lambda: feeds)
    groups = bilibili_following_groups()
    key = "bili:https://space.bilibili.com/12345"
    assert key in groups
    assert groups[key]["name_hint"] == "测试UP"
    assert groups[key]["subscribed"] is True
    assert "feed:bili-up-test-up" not in subscription_feed_groups()


def test_bilibili_rss_feed_not_sidebar_creator():
    feed = FeedConfig(
        url="https://rsshub.app/bilibili/user/video/1484421164",
        label="bili-up-1484421164",
    )
    from on1y.knowledge.creators import is_bilibili_rss_feed, is_sidebar_creator_feed

    assert is_bilibili_rss_feed(feed)
    assert not is_sidebar_creator_feed(feed)
    groups = subscription_feed_groups()
    assert "feed:bili-up-1484421164" not in groups


def test_zhihu_person_filter_uses_author_url_and_feed_labels():
    clause, params = creator_filter_sql("zhihu-person:quanshi.zhang")
    assert "author_url" in clause
    assert zhihu_author_url("quanshi.zhang") in params
    assert "zhihu-activities-quanshi-zhang" in params
    assert "zhihu-answers-quanshi-zhang" in params


def test_zhihu_collection_filter():
    clause, params = creator_filter_sql("zhihu-collection:809894830")
    assert params == ["zhihu-collection-809894830"]


def test_hotlist_not_subscription_feed():
    assert not is_subscription_feed("hotlist-zhihu")


def test_merge_activities_answers_same_person_key():
    a = creator_key_from_feed_label("zhihu-activities-duo-qi-zuo-41")
    b = creator_key_from_feed_label("zhihu-answers-duo-qi-zuo-41")
    assert a == b == "zhihu-person:duo-qi-zuo-41"


def test_normalize_twitter_author_url():
    assert normalize_twitter_author_url("https://twitter.com/Alice/") == "https://x.com/Alice"
    assert normalize_twitter_author_url("https://x.com/bob/status/1") == ""
    assert twitter_author_key_from_url("https://twitter.com/bob") == "twitter:https://x.com/bob"


def test_twitter_creator_filter_matches_url_variants():
    clause, params = creator_filter_sql("twitter:https://x.com/elonmusk")
    assert "author_url" in clause
    assert "https://x.com/elonmusk" in params
    assert "https://twitter.com/elonmusk" in params


def test_discover_twitter_author_groups():
    groups = discover_twitter_author_groups(
        {
            "https://x.com/alice": {"author": "Alice", "count": 3, "avatar": ""},
        }
    )
    assert "twitter:https://x.com/alice" in groups
    assert groups["twitter:https://x.com/alice"]["name_hint"] == "Alice"


def test_finalize_creator_sidebar_rows_filters_and_sorts() -> None:
    from on1y.knowledge.creators import finalize_creator_sidebar_rows

    rows = finalize_creator_sidebar_rows(
        [
            {"key": "bili:1", "name": "影视飓风", "platform": "bilibili", "item_count": 5},
            {"key": "feed:yt-a", "name": "影视飓风", "platform": "youtube", "item_count": 8},
            {"key": "feed:yt-b", "name": "Alpha", "platform": "youtube", "item_count": 4},
            {"key": "twitter:x", "name": "Bob", "platform": "twitter", "item_count": 2},
        ]
    )
    names = [row["name"] for row in rows]
    assert names == ["Alpha", "影视飓风"]
    assert all(int(row["item_count"]) > 3 for row in rows)
