"""Uso, a partir da raiz do repositório: python -m unittest agent.test_tools"""

import unittest

import httpx2
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import ToolException

from agent.api_client import ApiRejectedError, ApiUnavailableError, StoreApiClient
from agent.test_support import ORDER_8_PHONE, OTHER_CUSTOMER_PHONE, ApiTestCase
from agent.tools import (
    NOT_PROVIDED_MESSAGE,
    UNAVAILABLE_MESSAGE,
    build_tools,
    customer_wrote_email,
    customer_wrote_phone,
)


def state_with(*customer_texts):
    return {"messages": [HumanMessage(text) for text in customer_texts]}


class SchemaTest(ApiTestCase):
    def schema_of(self, name):
        tool = next(tool for tool in self.tools if tool.name == name)
        return tool.tool_call_schema.model_json_schema()

    def test_category_is_a_closed_list_from_the_api(self):
        category = self.schema_of("search_products")["properties"]["category"]
        names = next(option["enum"] for option in category["anyOf"] if "enum" in option)
        self.assertIn("Violões", names)
        self.assertEqual(len(names), 9)

    def test_llm_cannot_see_or_fill_the_injected_state(self):
        for name in ("get_order_status", "list_customer_orders"):
            with self.subTest(name=name):
                self.assertNotIn("state", self.schema_of(name)["properties"])


class ApiClientTest(unittest.TestCase):
    def client_returning(self, status_code):
        transport = httpx2.MockTransport(lambda request: httpx2.Response(status_code, json={"detail": "x"}))
        return StoreApiClient(httpx2.Client(transport=transport, base_url="http://test"))

    def test_connection_failure_means_unavailable(self):
        def fail(request):
            raise httpx2.ConnectError("recusada")

        client = StoreApiClient(httpx2.Client(transport=httpx2.MockTransport(fail), base_url="http://test"))
        with self.assertRaises(ApiUnavailableError):
            client.list_categories()

    def test_status_codes(self):
        with self.assertRaises(ApiUnavailableError):
            self.client_returning(500).list_categories()
        with self.assertRaises(ApiRejectedError):
            self.client_returning(422).list_categories()
        self.assertIsNone(self.client_returning(404).get_order(1, "67999999999"))


class CustomerDataTest(unittest.TestCase):
    def test_phone_matches_regardless_of_formatting(self):
        for text in ("(67) 99654-7821", "pedido 8, tel 67 996547821", "+55 67 99654 7821"):
            with self.subTest(text=text):
                self.assertTrue(customer_wrote_phone(state_with(text), "67996547821"))

    def test_phone_must_come_from_the_customer(self):
        state = {"messages": [HumanMessage("meu pedido é o 8"), AIMessage("Seu telefone é 67996547821?")]}
        self.assertFalse(customer_wrote_phone(state, "67996547821"))

    def test_email_ignores_case(self):
        self.assertTrue(customer_wrote_email(state_with("é ANA@jmail.com"), "ana@jmail.com"))
        self.assertFalse(customer_wrote_email(state_with("sem e-mail"), "ana@jmail.com"))


class ToolsUnavailableApiTest(unittest.TestCase):
    def test_tools_guide_the_llm_when_the_api_is_down(self):
        def fail(request):
            raise httpx2.ConnectError("recusada")

        api = StoreApiClient(httpx2.Client(transport=httpx2.MockTransport(fail), base_url="http://test"))
        tool = next(t for t in build_tools(api, [{"name": "Violões"}]) if t.name == "list_promotions")
        with self.assertRaisesRegex(ToolException, UNAVAILABLE_MESSAGE):
            tool.invoke({})


class OrderToolsDirectTest(ApiTestCase):
    """Chama as funções por trás das tools, com um estado montado à mão."""

    def order_tool(self):
        return next(tool for tool in self.tools if tool.name == "get_order_status").func

    def test_phone_not_written_by_customer_is_blocked(self):
        with self.assertRaisesRegex(ToolException, NOT_PROVIDED_MESSAGE):
            self.order_tool()(8, "67996547821", state_with("cadê meu pedido 8?"))

    def test_other_customers_phone_gets_not_found(self):
        result = self.order_tool()(8, "67998123456", state_with(f"pedido 8, telefone {OTHER_CUSTOMER_PHONE}"))
        self.assertIn('"found": false', result)
        self.assertNotIn("BRJL5544332BR", result)

    def test_owner_gets_the_order(self):
        result = self.order_tool()(8, "67996547821", state_with(f"pedido 8, telefone {ORDER_8_PHONE}"))
        self.assertIn('"found": true', result)
        self.assertIn("BRJL5544332BR", result)


if __name__ == "__main__":
    unittest.main()
