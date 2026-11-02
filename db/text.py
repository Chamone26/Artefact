import re
import unicodedata


def normalize_text(text):
    """Deixa o texto comparável em buscas: 'Violão GN-15' vira 'violao gn15'."""
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    without_hyphens = without_accents.casefold().replace("-", "")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", without_hyphens).split())
