"""Calculate trending status from view history."""
from pipeline.models import Article


def calculate_trending_status(article: Article) -> Article:
    """Set is_newly_trending and view_delta_percentage from view_history."""
    view_history = article.view_history

    if not view_history or len(view_history) < 2:
        article.is_newly_trending = False
        article.view_delta_percentage = 0
        return article

    n = len(view_history)
    yesterday = view_history[n - 2]["views"]
    today = view_history[n - 1]["views"]

    if yesterday == 0:
        delta_pct = 100 if today > 0 else 0
    else:
        delta_pct = ((today - yesterday) / yesterday) * 100

    article.view_delta_percentage = int(delta_pct)
    article.is_newly_trending = delta_pct > 100
    return article
