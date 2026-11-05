# Contexto do projeto

Resumo para continuar o trabalho em outra máquina ou sessão.

## O desafio

Processo seletivo de AI Engineer: um agente de mensagens de texto em Python para a Empório da Música, loja fictícia de instrumentos em Campo Grande/MS. O PDF do enunciado não está no repositório.

O agente deve:

- assumir uma persona alinhada ao tom da loja
- responder com base nos dados e nas políticas fornecidos
- saber quando consultar dados (preço, estoque, pedido) e quando consultar políticas (trocas, horários, pagamento)
- lidar bem com perguntas fora do escopo

Entregáveis:

- **Repositório público no GitHub:** histórico com progresso real, sem force-push de tudo em um commit, e sem alterações depois da entrega.
- **README:** como rodar, justificativa das decisões (framework, LLM, retrieval, prompt), limitações, o que faria com mais tempo e como usou assistentes de IA.
- **De 3 a 5 conversas de exemplo** em `.md`, `.txt` ou imagem, com ao menos uma não trivial. Sugestões do enunciado: violões até R$ 1.000, endereço da loja, preço do Takamine GD20 e arrependimento de compra.

Ambiguidades devem ser resolvidas com uma interpretação razoável, documentada no README. O link é enviado respondendo ao e-mail do processo.

## Decisões tomadas

| Tema | Decisão | Motivo |
|---|---|---|
| Abordagem | Function calling com RAG como tool | O agente decide o que consultar |
| Retrieval | BM25 por seção, com palavras-chave | Melhor resultado na comparação, sem download de modelo |
| Framework | LangGraph com `StateGraph` | Escolha do desenvolvedor para demonstrar domínio, mesmo que um loop próprio bastasse |
| Dados | Servidor HTTP separado do agente | Escolha do desenvolvedor; as tools de RAG também ficarão no servidor |
| Modelo | Claude Haiku 5.5 | Escolha do desenvolvedor. Limitação conhecida: às vezes escreve "No" no lugar de "Não" |
| ETL | pandas | Escolha do desenvolvedor |
| Busca de produtos | Substring simples | Simplificação feita pelo desenvolvedor; as descrições das tools compensam os limites |
| Interfaces | CLI e Streamlit | Clientes independentes de `Agent.respond` |
| Memória | `InMemorySaver`, por sessão | Suficiente para o protótipo |
| Fora do MVP | AI Gateway, backend separado, AWS, WhatsApp, serviço de guardrails, memória persistente | Vão para "o que faria com mais tempo" |

O funcionamento interno está em [agente.md](agente.md).

## Estado atual

- **Pronto:** ETL e SQLite, API com 7 rotas, grafo do agente, 7 tools (dados, `search_policies` e `escalate_to_human`), ingestão e busca nas políticas, CLI, Streamlit, testes sem LLM e 5 conversas de exemplo em `examples/`.
- **Parcial:** README e cenários com o modelo real. Na última rodada, nenhum dos 35 turnos foi marcado, mas o "No" no lugar de "Não", limitação conhecida do Haiku, apareceu na rodada anterior e pode voltar.
- **Falta:** seção "Uso de Agentes de IA", que o desenvolvedor pretende escrever, e diagramas finais.

Diagramas: `arq_revisada.excalidraw` traz a arquitetura e `arq_as_is_to_be.excalidraw`, a comparação do estado atual com a meta do MVP.

## Retrieval

Decisões e medições estão em [agente.md](agente.md). Em resumo: BM25 acertou 25 de 29 perguntas entre os 3 primeiros resultados, contra 21 dos embeddings e 22 do híbrido. Com palavras-chave, foram 7 de 10 em perguntas novas, que não devem guiar novos ajustes.

## Pendências para rodar em outro ambiente

- **PDF de políticas:** fica em `rag/raw_data/politicas_da_loja.pdf`, e a ingestão depende dele.
- **Chave de API:** o `.env` não é versionado. Crie-o a partir do `.env.example` ou defina `ANTHROPIC_API_KEY` no ambiente.
- **Banco e índice:** gere com `python -m db.etl` e `python -m rag.ingest`, depois de instalar o `requirements.txt`.
