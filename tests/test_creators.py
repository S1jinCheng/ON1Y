from on1y.ingestion.rss import FeedConfig
from on1y.knowledge.creators import (
    creator_filter_sql,
    creator_key_from_feed,
    creator_key_from_feed_label,
    is_sidebar_creator_feed,
    is_subscription_feed,
    is_zhihu_collection_feed,
    subscription_feed_groups,
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
