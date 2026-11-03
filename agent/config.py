"""Configuração do agente, lida de variáveis de ambiente ou do arquivo .env (veja .env.example)."""

import os
from dataclasses import dataclass
from datetime import date

from dotenv import load_dotenv

DEFAULT_MODEL = "claude-haiku-5-5"
DEFAULT_API_URL = "http://127.0.0.1:8000"

# Os pedidos vão até 2026-03-22. Com a data real, todo pedido em aberto pareceria muito atrasado,
# então o agente trabalha com uma data de referência logo depois do último pedido.
DEFAULT_TODAY = "2026-03-25"

# Cada rodada de tools gasta dois passos do grafo (nó agent + nó tools). 15 passos permitem até 6
# rodadas e a resposta final, o que sobra para um atendimento normal. O número foi medido em
# agent/test_graph.py (test_step_limit_ends_with_a_normal_reply).
DEFAULT_RECURSION_LIMIT = 15


class ConfigError(Exception):
    """Configuração ausente ou inválida. A mensagem diz ao desenvolvedor como corrigir."""


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    model: str
    api_url: str
    today: date
    recursion_limit: int

    @classmethod
    def from_env(cls):
        load_dotenv()
        api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise ConfigError("ANTHROPIC_API_KEY não definida. Copie .env.example para .env e preencha a chave.")
        raw_today = os.getenv("AGENT_TODAY") or DEFAULT_TODAY
        raw_limit = os.getenv("AGENT_RECURSION_LIMIT") or DEFAULT_RECURSION_LIMIT
        try:
            today = date.fromisoformat(raw_today)
            recursion_limit = int(raw_limit)
        except ValueError as error:
            raise ConfigError(f"AGENT_TODAY deve ser AAAA-MM-DD e AGENT_RECURSION_LIMIT, um inteiro: {error}") from error
        return cls(
            anthropic_api_key=api_key,
            model=os.getenv("AGENT_MODEL") or DEFAULT_MODEL,
            api_url=os.getenv("AGENT_API_URL") or DEFAULT_API_URL,
            today=today,
            recursion_limit=recursion_limit,
        )
