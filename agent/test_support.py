"""Apoio aos testes: API real em memória e um modelo com respostas roteirizadas, sem rede nem chave."""

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from agent.api_client import StoreApiClient
from agent.tools import build_tools
from api.main import app, get_store
from api.store import Store
from db.etl import build_database

ORDER_8_PHONE = "(67) 99654-7821"
OTHER_CUSTOMER_PHONE = "(67) 99812-3456"
ORDER_15_PHONE = "(67) 99901-2345"


class ApiTestCase(unittest.TestCase):
    """Sobe a API em memória, sobre um banco temporário gerado pelo ETL."""

    @classmethod
    def setUpClass(cls):
        tmp_dir = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp_dir.cleanup)
        db_path = Path(tmp_dir.name) / "test.db"
        build_database(db_path)
        app.dependency_overrides[get_store] = lambda: Store(db_path)
        cls.addClassCleanup(app.dependency_overrides.clear)
        cls.api = StoreApiClient(TestClient(app))
        cls.tools = build_tools(cls.api, cls.api.list_categories())


class ScriptedModel:
    """Substitui o ChatAnthropic: devolve as respostas na ordem e guarda o que recebeu."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.received = []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.received.append(list(messages))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def tool_call(name, call_id="1", **args):
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": call_id}])
