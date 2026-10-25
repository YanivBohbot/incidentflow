from bs4 import BeautifulSoup

from incidentflow.knowledge.official_sources import (
    main_content_soup_strainer,
    remove_leading_page_chrome,
)


def test_main_content_strainer_excludes_navigation_and_footer() -> None:
    html = """
    <nav>Products Documentation Sign in</nav>
    <main><h1>Connection pool overview</h1><p>Inspect connection utilization.</p></main>
    <footer>Company Careers</footer>
    """

    parsed = BeautifulSoup(html, "html.parser", parse_only=main_content_soup_strainer())
    content = parsed.get_text(" ", strip=True)

    assert "Connection pool overview" in content
    assert "Inspect connection utilization." in content
    assert "Products Documentation" not in content
    assert "Company Careers" not in content


def test_remove_leading_page_chrome_drops_breadcrumbs_only_at_the_start() -> None:
    page_content = (
        "Docs Home / DevelopmentDocs Home / Development\n"
        "MongoDB PerformanceCopy pageConnection monitoring guidance."
    )

    assert remove_leading_page_chrome(page_content) == "Connection monitoring guidance."
    assert remove_leading_page_chrome("Mention Copy page in the article body.") == (
        "Mention Copy page in the article body."
    )
