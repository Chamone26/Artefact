"""Uso, a partir da raiz do repositório: python -m unittest rag.test_rag"""

import sys
import tempfile
import unittest
from pathlib import Path

from rag.ingest import INTERNAL_SECTIONS, build_index
from rag.search import PolicyIndex

# Pergunta -> seções aceitas. Estas guiaram a escolha das palavras-chave de rag/ingest.py.
TUNING_QUESTIONS = [
    ("Qual o endereço da loja?", {"1.2"}),
    ("Onde fica a loja?", {"1.2"}),
    ("Qual o telefone de vocês?", {"1.2", "7"}),
    ("Que horas vocês abrem no sábado?", {"2"}),
    ("A loja abre domingo?", {"2"}),
    ("Vocês funcionam no feriado?", {"2"}),
    ("Aceitam PIX?", {"3"}),
    ("Tem desconto no pix?", {"3", "6.2"}),
    ("Posso parcelar em 12 vezes?", {"3", "3.1"}),
    ("Qual a parcela mínima no cartão?", {"3", "3.1"}),
    ("Posso pagar metade no pix e metade no cartão?", {"3.1"}),
    ("Me arrependi da minha compra, posso devolver meu pedido?", {"4.1"}),
    ("Comprei e não gostei, consigo meu dinheiro de volta?", {"4.1"}),
    ("Quem paga o frete da devolução?", {"4.1"}),
    ("Meu violão veio com defeito, o que faço?", {"4.2"}),
    ("Quero trocar por outra cor", {"4.3"}),
    ("Posso trocar a boquilha do meu saxofone?", {"4.4"}),
    ("Quanto custa o frete para Campo Grande?", {"5.1"}),
    ("Entrega é grátis?", {"5.1"}),
    ("Quanto tempo demora o SEDEX?", {"5.2"}),
    ("Vocês entregam em outra cidade?", {"5.2"}),
    ("Como rastreio minha encomenda?", {"5.3"}),
    ("Quando é a Black Friday de vocês?", {"6.1"}),
    ("Promoção acumula com desconto no pix?", {"6.2"}),
    ("Qual a garantia dos instrumentos?", {"8.1", "8.2"}),
    ("A garantia cobre queda?", {"8.3", "4.2"}),
    ("Vocês vendem meus dados?", {"9"}),
    ("Como peço para apagar meus dados?", {"9"}),
    ("Vocês vendem palheta?", {"1"}),
]


# Escritas depois do ajuste das palavras-chave, para medir a busca em perguntas que ela nunca viu.
# Não ajuste as palavras-chave olhando estas perguntas: isso esconderia o resultado real.
HELD_OUT_QUESTIONS = [
    ("Vocês estão abertos na segunda de manhã?", {"2"}),
    ("Qual é o CEP de vocês?", {"1.2"}),
    ("Dá pra pagar com boleto?", {"3"}),
    ("Em quantas vezes sem juros posso dividir uma compra de 800 reais?", {"3", "3.1"}),
    ("Recebi o instrumento ontem e mudei de ideia, e agora?", {"4.1"}),
    ("O braço do meu baixo empenou depois de dois meses, quem resolve?", {"4.2", "8.1", "8.2"}),
    ("Vocês mandam para Dourados?", {"5.2"}),
    ("Um piano digital paga frete diferente?", {"5.2"}),
    ("Perdi o código para acompanhar a entrega", {"5.3"}),
    ("Se o estoque acabar na promoção, vocês seguram o preço para mim?", {"6.2"}),
]


def hits_in_top_3(index, questions):
    return sum(
        any(section["section"] in accepted for section in index.search(question, limit=3))
        for question, accepted in questions
    )


class RagTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp_dir = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp_dir.cleanup)
        cls.path = Path(tmp_dir.name) / "sections.json"
        cls.sections = build_index(cls.path)
        cls.by_number = {section["section"]: section for section in cls.sections}
        cls.index = PolicyIndex.load(cls.path)


class IngestTest(RagTestCase):
    def test_expected_sections(self):
        self.assertEqual(
            list(self.by_number),
            ["1", "1.1", "1.2", "2", "3", "3.1", "4", "4.1", "4.2", "4.3", "4.4", "5.1", "5.2", "5.3",
             "6.1", "6.2", "7", "8.1", "8.2", "8.3", "9"],
        )

    def test_internal_sections_stay_out_of_the_index(self):
        self.assertFalse(INTERNAL_SECTIONS & set(self.by_number))
        self.assertFalse(any("Tom de voz" in section["text"] for section in self.sections))

    def test_section_spanning_a_page_break_stays_whole(self):
        text = self.by_number["5.2"]["text"]
        self.assertIn("SEDEX (Correios)", text)
        self.assertIn("2 a 5 dias úteis", text)
        self.assertIn("recusar o recebimento", text)

    def test_headers_and_footers_are_removed(self):
        for section in self.sections:
            with self.subTest(section=section["section"]):
                self.assertNotIn("Página ", section["text"])
                self.assertNotIn("Manual de Políticas", section["text"])

    def test_subsection_keeps_parent_title(self):
        self.assertEqual(self.by_number["8.3"]["parent"], "Garantia")
        self.assertIsNone(self.by_number["2"]["parent"])

    def test_store_email_has_a_single_spelling(self):
        self.assertIn("contato@emporiodamusica.com.br", self.by_number["1.2"]["text"])


class SearchTest(RagTestCase):
    def test_tuning_questions_reach_the_target(self):
        self.assertGreaterEqual(hits_in_top_3(self.index, TUNING_QUESTIONS), 27)

    def test_held_out_questions_keep_the_measured_level(self):
        # Valor medido uma vez, antes de qualquer ajuste. É um piso contra regressões, não uma meta.
        self.assertGreaterEqual(hits_in_top_3(self.index, HELD_OUT_QUESTIONS), 7)

    def test_ignores_accents_and_plurals(self):
        expected = self.index.search("devolução")[0]["section"]
        self.assertEqual(self.index.search("DEVOLUCOES")[0]["section"], expected)

    def test_no_common_term_returns_nothing(self):
        self.assertEqual(self.index.search("xilofone quântico"), [])
        self.assertEqual(self.index.search("de para com"), [])

    def test_limit_and_result_fields(self):
        results = self.index.search("garantia", limit=2)
        self.assertEqual(len(results), 2)
        self.assertEqual(set(results[0]), {"section", "title", "parent", "text"})

    def test_missing_index_has_a_clear_error(self):
        with self.assertRaisesRegex(FileNotFoundError, "python -m rag.ingest"):
            PolicyIndex.load("nao_existe.json")

    def test_search_does_not_load_the_pdf_library(self):
        # A API só precisa do índice pronto: o PyMuPDF é usado apenas na ingestão.
        code = "import sys, rag.search; sys.exit('pymupdf' in sys.modules)"
        import subprocess

        self.assertEqual(subprocess.run([sys.executable, "-c", code]).returncode, 0)


if __name__ == "__main__":
    unittest.main()
