"""Busca lexical (BM25) nas seções do manual.

Por que BM25, e não embeddings: em um teste com 29 perguntas, ele acertou mais que um modelo de
embeddings multilíngue e que a combinação dos dois, sem exigir download de modelo. Detalhes em
docs/agente.md. A implementação é curta porque o índice tem cerca de 20 seções e cabe em memória.
"""

import json
import math
from collections import Counter
from pathlib import Path

from db.utils import normalize_text

SECTIONS_PATH = Path(__file__).parent / "policy_sections.json"

BM25_K1 = 1.5
BM25_B = 0.75
STOPWORDS = set(
    "a o as os de do da dos das e em um uma para por com que no na nos nas se ao aos "
    "eu meu minha voce voces qual quais como quanto quando onde ou mais".split()
)
RESULT_FIELDS = ("section", "title", "parent", "text")


def stem(token):
    """Reduz plurais comuns, para 'devoluções' encontrar 'devolução'."""
    if token.endswith("oes"):
        return token[:-3] + "ao"
    if token.endswith("s") and len(token) > 3:
        return token[:-1]
    return token


def tokenize(text):
    return [stem(token) for token in normalize_text(text).split() if token not in STOPWORDS]


class PolicyIndex:
    def __init__(self, sections):
        self.sections = sections
        # O título conta duas vezes porque resume o assunto da seção melhor que o corpo do texto.
        self.documents = [
            Counter(tokenize(f"{s['title']} {s['title']} {s['parent'] or ''} {s['text']} {s['keywords']}"))
            for s in sections
        ]
        self.lengths = [sum(document.values()) for document in self.documents]
        self.average_length = sum(self.lengths) / len(self.lengths)
        self.document_frequency = Counter(term for document in self.documents for term in document)

    @classmethod
    def load(cls, path=SECTIONS_PATH):
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Índice não encontrado em {path}. Gere-o com: python -m rag.ingest")
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def _score(self, terms, position):
        document = self.documents[position]
        length_ratio = self.lengths[position] / self.average_length
        score = 0.0
        for term in terms:
            frequency = document[term]
            if frequency:
                documents = len(self.documents)
                matches = self.document_frequency[term]
                idf = math.log(1 + (documents - matches + 0.5) / (matches + 0.5))
                score += idf * frequency * (BM25_K1 + 1) / (frequency + BM25_K1 * (1 - BM25_B + BM25_B * length_ratio))
        return score

    def search(self, query, limit=3):
        """Devolve até `limit` seções, da mais à menos relevante. Sem nenhum termo em comum, devolve vazio."""
        terms = tokenize(query)
        scored = [(self._score(terms, position), position) for position in range(len(self.sections))]
        ranked = sorted((item for item in scored if item[0] > 0), key=lambda item: (-item[0], item[1]))
        return [
            {field: self.sections[position][field] for field in RESULT_FIELDS}
            for _, position in ranked[:limit]
        ]
