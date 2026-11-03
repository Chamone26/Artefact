"""Uso, a partir da raiz do repositório: python -m unittest agent.test_graph

Testa o grafo inteiro com um modelo roteirizado e a API real em memória. Só o LLM é simulado, então
estes testes verificam o fluxo, não a qualidade das decisões do modelo.
"""

import contextlib
import io
import json
import logging
import unittest
from datetime import date

import anthropic
import httpx2
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from agent.config import DEFAULT_RECURSION_LIMIT
from agent.graph import (
    INCOMPLETE_REPLY,
    MODEL_ERROR_REPLY,
    STEP_LIMIT_REPLY,
    Agent,
    AgentReply,
    ToolCallRecord,
    build_graph,
)
from agent.prompt import build_system_prompt
from agent.scenarios import Scenario, Turn, check_turn, run_scenarios
from agent.test_support import ORDER_8_PHONE, ApiTestCase, ScriptedModel, tool_call

RECURSION_LIMIT = DEFAULT_RECURSION_LIMIT


def tool_results(messages):
    return [message for message in messages if isinstance(message, ToolMessage)]


class GraphTestCase(ApiTestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)  # os avisos esperados não devem poluir a saída dos testes
        self.addCleanup(logging.disable, logging.NOTSET)

    def agent_with(self, *responses, recursion_limit=RECURSION_LIMIT):
        self.model = ScriptedModel(*responses)
        graph = build_graph(self.model, self.tools, "prompt de teste", InMemorySaver())
        return Agent(graph, recursion_limit)


class ToolFlowTest(GraphTestCase):
    def test_answer_without_tools(self):
        reply = self.agent_with(AIMessage("Olá!")).respond("s1", "oi")
        self.assertEqual(reply.text, "Olá!")
        self.assertEqual(reply.tool_calls, [])

    def test_tool_result_reaches_the_model(self):
        agent = self.agent_with(tool_call("search_products", query="Takamine GD20"), AIMessage("R$ 2.199,00"))
        reply = agent.respond("s1", "quanto custa o Takamine GD20?")
        self.assertEqual(reply.text, "R$ 2.199,00")
        self.assertEqual([call.name for call in reply.tool_calls], ["search_products"])
        result = json.loads(tool_results(self.model.received[1])[0].content)
        self.assertEqual(result["products"][0]["final_price_brl"], 2199.0)

    def test_parallel_tools_each_get_a_result(self):
        both = AIMessage("", tool_calls=[
            {"name": "list_promotions", "args": {}, "id": "a"},
            {"name": "list_categories", "args": {}, "id": "b"},
        ])
        agent = self.agent_with(both, AIMessage("pronto"))
        agent.respond("s1", "promoções e categorias?")
        self.assertEqual({m.tool_call_id for m in tool_results(self.model.received[1])}, {"a", "b"})

    def test_invalid_arguments_return_to_the_model_as_error(self):
        agent = self.agent_with(tool_call("search_products", category="Inexistente"), AIMessage("ok"))
        reply = agent.respond("s1", "teste")
        self.assertEqual(reply.text, "ok")
        self.assertTrue(reply.tool_calls[0].is_error)
        self.assertEqual(tool_results(self.model.received[1])[0].status, "error")

    def test_empty_search_carries_a_hint(self):
        agent = self.agent_with(tool_call("search_products", query="saxofone"), AIMessage("não temos"))
        agent.respond("s1", "tem saxofone?")
        self.assertIn("hint", json.loads(tool_results(self.model.received[1])[0].content))


    def test_text_search_warns_that_results_are_partial(self):
        agent = self.agent_with(tool_call("search_products", query="ukulele iniciante"), AIMessage("ok"))
        agent.respond("s1", "ukulele para iniciante?")
        self.assertIn("note", json.loads(tool_results(self.model.received[1])[0].content))

    def test_filter_only_search_has_no_warning(self):
        agent = self.agent_with(tool_call("search_products", category="Ukuleles"), AIMessage("ok"))
        agent.respond("s1", "ukuleles?")
        self.assertNotIn("note", json.loads(tool_results(self.model.received[1])[0].content))


class OrderAuthorizationTest(GraphTestCase):
    def test_owner_reaches_the_order_through_the_graph(self):
        agent = self.agent_with(tool_call("get_order_status", order_id=8, phone=ORDER_8_PHONE), AIMessage("Enviado"))
        agent.respond("s1", f"pedido 8, telefone {ORDER_8_PHONE}")
        self.assertIn("BRJL5544332BR", tool_results(self.model.received[1])[0].content)

    def test_phone_invented_by_the_model_is_blocked_by_the_graph(self):
        agent = self.agent_with(tool_call("get_order_status", order_id=8, phone=ORDER_8_PHONE), AIMessage("preciso do telefone"))
        reply = agent.respond("s1", "cadê meu pedido 8?")
        result = tool_results(self.model.received[1])[0]
        self.assertEqual(result.status, "error")
        self.assertNotIn("BRJL5544332BR", result.content)
        self.assertTrue(reply.tool_calls[0].is_error)

    def test_phone_from_a_previous_message_is_accepted(self):
        agent = self.agent_with(
            AIMessage("Qual o pedido?"),
            tool_call("get_order_status", order_id=8, phone=ORDER_8_PHONE),
            AIMessage("Enviado"),
        )
        agent.respond("s1", f"meu telefone é {ORDER_8_PHONE}")
        agent.respond("s1", "é o pedido 8")
        self.assertEqual(tool_results(self.model.received[2])[0].status, "success")

    def test_records_do_not_contain_personal_data(self):
        agent = self.agent_with(tool_call("get_order_status", order_id=8, phone=ORDER_8_PHONE), AIMessage("ok"))
        reply = agent.respond("s1", f"pedido 8, telefone {ORDER_8_PHONE}")
        self.assertEqual(reply.tool_calls[0].args, {"order_id": 8, "phone": "***"})


class MemoryTest(GraphTestCase):
    def test_same_session_keeps_history(self):
        agent = self.agent_with(AIMessage("Oi!"), AIMessage("Tudo bem"))
        agent.respond("s1", "primeira")
        agent.respond("s1", "segunda")
        contents = [m.content for m in self.model.received[1] if isinstance(m, HumanMessage)]
        self.assertEqual(contents, ["primeira", "segunda"])

    def test_sessions_are_isolated(self):
        agent = self.agent_with(AIMessage("Oi!"), AIMessage("Oi!"))
        agent.respond("s1", "segredo")
        agent.respond("s2", "outra pessoa")
        contents = [m.content for m in self.model.received[1] if isinstance(m, HumanMessage)]
        self.assertEqual(contents, ["outra pessoa"])

    def test_phone_from_another_session_is_blocked(self):
        agent = self.agent_with(
            AIMessage("ok"),
            tool_call("get_order_status", order_id=8, phone=ORDER_8_PHONE),
            AIMessage("preciso do telefone"),
        )
        agent.respond("s1", f"telefone {ORDER_8_PHONE}")
        agent.respond("s2", "cadê o pedido 8?")
        self.assertEqual(tool_results(self.model.received[2])[0].status, "error")

    def test_system_prompt_is_sent_but_not_stored(self):
        agent = self.agent_with(AIMessage("a"), AIMessage("b"))
        agent.respond("s1", "um")
        agent.respond("s1", "dois")
        system_messages = [m for m in self.model.received[1] if m.type == "system"]
        self.assertEqual(len(system_messages), 1)


class SafetyStopsTest(GraphTestCase):
    def incomplete(self, stop_reason):
        return AIMessage(
            "",
            tool_calls=[{"name": "list_promotions", "args": {}, "id": "x"}],
            response_metadata={"stop_reason": stop_reason},
        )

    def test_tools_of_incomplete_responses_are_not_executed(self):
        for stop_reason in ("max_tokens", "refusal"):
            with self.subTest(stop_reason=stop_reason):
                reply = self.agent_with(self.incomplete(stop_reason)).respond("s1", "oi")
                self.assertEqual(reply.text, INCOMPLETE_REPLY)
                self.assertEqual(reply.tool_calls, [])

    def test_step_limit_ends_with_a_normal_reply(self):
        endless = [tool_call("list_promotions", call_id=str(i)) for i in range(20)]
        agent = self.agent_with(*endless)
        reply = agent.respond("s1", "oi")
        self.assertEqual(reply.text, STEP_LIMIT_REPLY)
        self.assertEqual(len(reply.tool_calls), 6)

    def test_conversation_continues_after_the_step_limit(self):
        endless = [tool_call("list_promotions", call_id=str(i)) for i in range(6)]
        extra = tool_call("list_promotions", call_id="extra")
        agent = self.agent_with(*endless, extra, AIMessage("voltei"))
        agent.respond("s1", "oi")
        self.assertEqual(agent.respond("s1", "de novo").text, "voltei")
        unanswered = [
            call["id"] for m in self.model.received[-1] if isinstance(m, AIMessage) for call in m.tool_calls
        ]
        answered = [m.tool_call_id for m in tool_results(self.model.received[-1])]
        self.assertEqual(sorted(unanswered), sorted(answered))

    def test_model_failure_gets_a_friendly_reply_and_keeps_the_session(self):
        failure = anthropic.APIConnectionError(request=httpx2.Request("POST", "http://test"))
        agent = self.agent_with(failure, AIMessage("voltei"))
        self.assertEqual(agent.respond("s1", "oi").text, MODEL_ERROR_REPLY)
        self.assertEqual(agent.respond("s1", "de novo").text, "voltei")


class ScenarioCheckTest(GraphTestCase):
    """Garante que o verificador de agent/scenarios.py aponta os problemas, sem chamar o modelo real."""

    def test_detects_missing_text_and_tool(self):
        turn = Turn("preço?", contains=("2.199",), uses_tool="search_products")
        self.assertEqual(len(check_turn(turn, AgentReply("não sei"))), 2)

    def test_tool_with_error_does_not_count(self):
        turn = Turn("preço?", uses_tool="search_products")
        reply = AgentReply("ok", [ToolCallRecord("search_products", {}, is_error=True)])
        self.assertEqual(len(check_turn(turn, reply)), 1)

    def test_markdown_is_a_problem_in_any_scenario(self):
        self.assertEqual(check_turn(Turn("oi"), AgentReply("**olá**")), ["usou markdown"])

    def test_wrong_negation_is_a_problem_but_no_momento_is_not(self):
        self.assertEqual(check_turn(Turn("oi"), AgentReply("No, não está em promoção")), ["escreveu 'No' no lugar de 'Não'"])
        self.assertEqual(check_turn(Turn("oi"), AgentReply("No encontrei esse modelo")), ["escreveu 'No' no lugar de 'Não'"])
        self.assertEqual(check_turn(Turn("oi"), AgentReply("No momento não temos")), [])

    def test_comparison_ignores_case(self):
        turn = Turn("capital?", excludes=("paris",))
        self.assertEqual(len(check_turn(turn, AgentReply("É PARIS"))), 1)
        self.assertEqual(check_turn(Turn("oi", contains=("OLÁ",)), AgentReply("olá!")), [])

    def test_runner_counts_turns_with_problems(self):
        agent = self.agent_with(AIMessage("Paris"), AIMessage("ok"))
        scenario = Scenario("teste", [Turn("capital?", excludes=("Paris",)), Turn("oi")])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run_scenarios(agent, [scenario]), 1)


class PromptTest(unittest.TestCase):
    def test_prompt_contains_the_reference_date(self):
        self.assertIn("2026-03-25", build_system_prompt(date(2026, 3, 25)))


if __name__ == "__main__":
    unittest.main()
