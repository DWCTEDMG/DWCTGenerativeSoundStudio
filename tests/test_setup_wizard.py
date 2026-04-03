from edmg_studio_backend.services.setup_wizard import (
    _7zip_cli_download_candidates,
    _resolve_7zip_cli_download,
)


def test_resolve_7zip_cli_download_supports_legacy_relative_links():
    page_url = "https://7-zip.org/download.html"
    html = '<a href="a/7zr.exe">Download</a>'

    url, fname = _resolve_7zip_cli_download(page_url, html)

    assert url == "https://7-zip.org/a/7zr.exe"
    assert fname == "7zr.exe"


def test_resolve_7zip_cli_download_supports_absolute_links():
    page_url = "https://7-zip.org/download.html"
    html = (
        '<a href="https://github.com/ip7z/7zip/releases/download/26.00/7zr.exe">'
        "Download</a>"
    )

    url, fname = _resolve_7zip_cli_download(page_url, html)

    assert url == "https://github.com/ip7z/7zip/releases/download/26.00/7zr.exe"
    assert fname == "7zr.exe"


def test_7zip_cli_download_candidates_prefer_direct_latest_url():
    candidates = _7zip_cli_download_candidates("https://7-zip.org/download.html")

    assert candidates[0] == ("https://github.com/ip7z/7zip/releases/latest/download/7zr.exe", "7zr.exe")
