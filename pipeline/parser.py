"""Parse the Wikimedia Featured Feed JSON into Article objects."""
from pipeline.models import Article


class FeaturedArticlesParser:
    def __init__(self, featured_feed: dict):
        self.featured_feed = featured_feed
        self.feed_date_str = featured_feed["mostread"]["date"].rstrip("Z")

    def parse(self) -> list[Article]:
        articles = []
        for rank_counter, item in enumerate(
            self.featured_feed["mostread"]["articles"], start=1
        ):
            articles.append(self._parse_article(item, rank_counter))
        return articles

    def _parse_article(self, item: dict, rank_counter: int) -> Article:
        return Article(
            date=self.feed_date_str,
            title=item["title"],
            normalized_title=item["titles"]["normalized"],
            view_count=item["views"],
            rank=rank_counter,
            mystery_rank=item["rank"],
            link=item["content_urls"]["desktop"]["page"],
            thumbnail=item.get("thumbnail", {}).get("source"),
            extract=item["extract_html"],
            view_history=item.get("view_history", []),
        )
