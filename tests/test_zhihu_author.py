"""Tests for Zhihu author metadata helpers."""

from on1y.utils.zhihu_author import author_meta_from_content, author_meta_from_user, enrich_zhihu_author_meta


def test_author_meta_from_user() -> None:
    meta = author_meta_from_user(
        {
            "name": "张三",
            "avatar_url": "https://pic1.zhimg.com/v2-abc_l.jpg",
            "url_token": "zhang-san",
        }
    )
    assert meta["author"] == "张三"
    assert "zhimg.com" in meta["author_avatar"]
    assert meta["author_url"] == "https://www.zhihu.com/people/zhang-san"


def test_author_meta_from_content() -> None:
    meta = author_meta_from_content(
        {
            "type": "answer",
            "author": {"name": "李四", "avatar_url": "https://picx.zhimg.com/x.jpg", "url_token": "li-si"},
        }
    )
    assert meta["author"] == "李四"


def test_enrich_zhihu_author_meta_prefers_api(monkeypatch) -> None:
    def fake_fetch(_url: str, **kwargs):
        return {
            "author": "作者A",
            "author_avatar": "https://pic1.zhimg.com/author-a_l.jpg",
            "author_url": "https://www.zhihu.com/people/author-a",
        }

    monkeypatch.setattr(
        "on1y.utils.zhihu_author.fetch_author_meta_for_url",
        fake_fetch,
    )
    meta = enrich_zhihu_author_meta(
        {
            "author": "导航栏",
            "author_avatar": "https://pic1.zhimg.com/my-self_l.jpg",
        },
        "https://www.zhihu.com/question/1/answer/2",
    )
    assert meta["author"] == "作者A"
    assert "author-a" in meta["author_avatar"]
