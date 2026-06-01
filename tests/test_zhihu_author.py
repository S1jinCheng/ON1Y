"""Tests for Zhihu author metadata helpers."""

from on1y.utils.zhihu_author import author_meta_from_content, author_meta_from_user


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
