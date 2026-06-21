from on1y.books.cover import cover_proxy_allowed, normalize_cover_url


def test_normalize_cover_url_protocol_relative():
    assert normalize_cover_url("//img1.doubanio.com/view/subject/s/public/s1.jpg") == (
        "https://img1.doubanio.com/view/subject/s/public/s1.jpg"
    )


def test_normalize_cover_url_http_to_https():
    assert normalize_cover_url("http://img1.doubanio.com/x.jpg") == "https://img1.doubanio.com/x.jpg"


def test_cover_proxy_allowed_douban_and_google():
    assert cover_proxy_allowed("https://img9.doubanio.com/view/subject/l/public/s1.jpg")
    assert cover_proxy_allowed("https://lh3.googleusercontent.com/books/abc")
    assert not cover_proxy_allowed("https://evil.example.com/cover.jpg")


def test_cover_proxy_allowed_zlib_hosts():
    assert cover_proxy_allowed("https://zh.z-lib.help/img/covers/x.jpg")
    assert cover_proxy_allowed("https://1lib.sk/covers/x.jpg")
    assert cover_proxy_allowed(
        "https://s3proxy-alp2-covers.cdn-zlib.sk/covers299/collections/genesis/abc.jpg"
    )
    assert cover_proxy_allowed("https://covers.z-lib.sk/cover.jpg")


def test_books_cover_route_is_public():
    from on1y.web.auth_http import _PUBLIC_API_PREFIXES

    assert "/api/books/cover" in _PUBLIC_API_PREFIXES

