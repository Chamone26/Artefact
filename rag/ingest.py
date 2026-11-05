"""Transforma o manual em PDF nas seções usadas pela busca.

Uso, a partir da raiz do repositório: python -m rag.ingest

Roda antes de subir a API, como o ETL do banco. Depois de gerar um novo índice, reinicie a API.
"""

import json
import re
from pathlib import Path

import pymupdf

RAG_DIR = Path(__file__).parent
PDF_PATH = RAG_DIR / "raw_data" / "politicas_da_loja.pdf"
SECTIONS_PATH = RAG_DIR / "policy_sections.json"

PAGE_HEADER = re.compile(r"Empório da Música\s+Manual de Políticas e Procedimentos\s*")
PAGE_FOOTER = re.compile(r"\s*Página \d+\s*$")
SECTION_HEADING = re.compile(r"^(\d{1,2}(?:\.\d)?)\.? ([A-ZÀ-Ú].*)$", re.MULTILINE)

# Instruções para a equipe, não informações para o cliente. O que importa delas está no system prompt.
INTERNAL_SECTIONS = {"7.1", "7.2", "7.3", "10"}

# O manual grafa o e-mail de duas formas. A interpretação adotada está documentada no README.
TEXT_FIXES = {"contato@empóriodamusica.com.br": "contato@emporiodamusica.com.br"}

# Palavras que o cliente usa e o manual não, para a busca lexical encontrar a seção certa.
SECTION_KEYWORDS = {
    "1": "vende vendem trabalha acessorio instrumento produto",
    "1.2": "endereco onde fica localizacao rua telefone contato email whatsapp cnpj",
    "2": "horario abre abrir abertura fecha fechar aberto funciona funcionamento domingo sabado feriado",
    "3": "pagar pagamento aceita aceitam pix debito credito cartao boleto",
    "3.1": "parcelar parcela vezes juros cartao credito metade dividir combinar",
    "4.1": "arrependi arrepender devolver devolucao reembolso dinheiro volta desistir gostei",
    "4.2": "defeito quebrado estragado problema trocar troca",
    "4.3": "trocar troca outra cor modelo tamanho preferencia",
    "4.4": "trocar troca boquilha sax personalizado",
    "5.1": "frete entrega entregar gratis motoboy prazo campo grande",
    "5.2": "frete entrega entregar outra cidade correios sedex pac jadlog prazo",
    "5.3": "rastreio rastrear rastreamento codigo encomenda",
    "6.1": "promocao campanha black friday desconto quando",
    "6.2": "promocao acumula acumular desconto pix",
    "7": "whatsapp telefone atendimento contato",
    "8.1": "garantia prazo",
    "8.2": "garantia fabricante",
    "8.3": "garantia cobre queda quebrou",
    "9": "dados privacidade lgpd apagar excluir vendem compartilham",
}


def read_manual(pdf_path=PDF_PATH):
    """Devolve o texto do manual sem a capa, os cabeçalhos e os rodapés."""
    with pymupdf.open(pdf_path) as document:
        pages = [page.get_text() for page in document]
    cleaned = [PAGE_FOOTER.sub("", PAGE_HEADER.sub("", page)) for page in pages[1:]]
    text = "\n".join(cleaned)
    for wrong, right in TEXT_FIXES.items():
        text = text.replace(wrong, right)
    return text


def section_order(number):
    return tuple(int(part) for part in number.split("."))


def find_headings(text):
    """Encontra os títulos de seção, que seguem sempre em ordem crescente.

    A ordem descarta falsos títulos, como os itens "1. Saudação" de uma lista numerada.
    """
    headings = []
    for match in SECTION_HEADING.finditer(text):
        if not headings or section_order(match.group(1)) > section_order(headings[-1].group(1)):
            headings.append(match)
    return headings


def split_sections(text):
    """Divide o texto por título, levando o título da seção pai para cada subseção."""
    headings = find_headings(text)
    titles = {match.group(1): match.group(2).strip() for match in headings}
    sections = []
    for match, next_match in zip(headings, headings[1:] + [None]):
        number = match.group(1)
        end = next_match.start() if next_match else len(text)
        body = text[match.end():end].strip()
        # Títulos sem texto próprio, como "8. Garantia", já aparecem como pai das subseções.
        if number in INTERNAL_SECTIONS or not body:
            continue
        sections.append({
            "section": number,
            "title": titles[number],
            "parent": titles.get(number.split(".")[0]) if "." in number else None,
            "text": "\n".join(line.strip() for line in body.splitlines() if line.strip()),
            "keywords": SECTION_KEYWORDS.get(number, ""),
        })
    return sections


def build_index(sections_path=SECTIONS_PATH, pdf_path=PDF_PATH):
    sections = split_sections(read_manual(pdf_path))
    Path(sections_path).write_text(json.dumps(sections, ensure_ascii=False, indent=2), encoding="utf-8")
    return sections


def main():
    sections = build_index()
    print(f"Índice gerado em {SECTIONS_PATH}: {len(sections)} seções")
    for section in sections:
        print(f"  {section['section']:>4}  {section['title']}")


if __name__ == "__main__":
    main()
