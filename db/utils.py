"""Itens compartilhados entre o ETL e quem consome o banco, sem depender do pandas."""

import re
import unicodedata
from pathlib import Path

DB_PATH = Path(__file__).parent / "emporio.db"


def normalize_text(text: str) -> str:
    """Normaliza texto para buscas, removendo acentos e hífens e padronizando espaços.

    Args:
        text: Texto original a normalizar.

    Returns:
        Texto em minúsculas, sem acentos e com caracteres não alfanuméricos
        substituídos por espaços. Hífens são removidos sem inserir espaço.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    without_hyphens = without_accents.casefold().replace("-", "")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", without_hyphens).split())
