"""Conversa com o agente no terminal.

Com a API de dados no ar (python main.py), rode a partir da raiz do repositório:
    python -m agent.cli           conversa normal
    python -m agent.cli --debug   mostra também as tools chamadas, sem telefone e e-mail

Esta camada só lê e escreve no terminal. Uma interface visual pode substituí-la chamando Agent.respond.
"""

import argparse
import logging
import sys
import uuid

from agent.api_client import ApiUnavailableError
from agent.config import ConfigError, Settings
from agent.graph import create_agent

HELP = "Comandos: /nova (recomeça a conversa) e /sair (encerra)."
LOG_FILE = "agent.log"


def print_tool_calls(tool_calls):
    for call in tool_calls:
        status = " [erro]" if call.is_error else ""
        print(f"  [tool] {call.name}({call.args}){status}")


def main():
    parser = argparse.ArgumentParser(description="Agente de atendimento da Empório da Música")
    parser.add_argument("--debug", action="store_true", help="mostra as tools chamadas em cada resposta")
    args = parser.parse_args()

    # Os logs não podem se misturar à conversa: vão para o terminal só com --debug.
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        **({} if args.debug else {"filename": LOG_FILE, "encoding": "utf-8"}),
    )

    try:
        settings = Settings.from_env()
        agent = create_agent(settings)
    except ConfigError as error:
        sys.exit(f"Erro de configuração: {error}")
    except ApiUnavailableError as error:
        sys.exit(f"{error}\nA API de dados precisa estar no ar. Em outro terminal, rode: python main.py")

    print(f"Empório da Música (modelo: {settings.model}, data de referência: {settings.today})")
    print(HELP)
    session_id = str(uuid.uuid4())
    while True:
        try:
            message = input("\nVocê: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not message:
            continue
        if message == "/sair":
            return
        if message == "/nova":
            session_id = str(uuid.uuid4())
            print("Conversa reiniciada.")
            continue
        reply = agent.respond(session_id, message)
        if args.debug:
            print_tool_calls(reply.tool_calls)
        print(f"\nAgente: {reply.text}")


if __name__ == "__main__":
    main()
