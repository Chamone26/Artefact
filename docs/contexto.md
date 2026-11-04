# Contexto do projeto

Resumo para continuar o trabalho em outra máquina ou sessão. Situação em 2026-11-04.

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

- **Pronto:** ETL e SQLite, API com 5 rotas, grafo do agente, 5 tools de dados, CLI, Streamlit e 75 testes.
- **Parcial:** 20 cenários com o modelo real (1 falhou na última rodada completa) e README.
- **Falta:** RAG e `search_policies`, `escalate_to_human`, conversas de exemplo, seção "Uso de Agentes de IA", que o desenvolvedor pretende escrever, e diagramas finais.

Diagramas: `arq_revisada.excalidraw` traz a arquitetura e `arq_as_is_to_be.excalidraw`, a comparação do estado atual com a meta do MVP.

## Plano proposto, ainda não aprovado

Só implementar depois da aprovação do desenvolvedor. Ele pediu que correções e alterações sejam propostas antes de aplicadas.

0. **Separar responsabilidades:** renomear `call_api` para `translate_api_errors` e mover os esquemas para `contracts/`, para `agent/tools.py` não importar `api`. As tools já usam HTTP; o acoplamento é só de código.
1. **Ingestão (`rag/ingest.py`):** extrair o PDF com PyMuPDF e dividir por seção, deixando fora do índice as seções internas 7.1, 7.2, 7.3 e 10. O índice é gerado, fora do repositório.
2. **Busca (`rag/search.py`):** BM25 por seção, com palavras-chave para sinônimos e até 3 resultados. Meta: 27 de 29 perguntas entre os 3 primeiros resultados, validada com 10 perguntas novas.
3. **Rota e tool:** `POST /policies/search` e `search_policies`.
4. **Prompt:** remover a seção temporária "Políticas da loja" e responder sobre políticas só com base na tool.
5. **Contradições do manual:** documentar as interpretações no README.
6. **Cenários:** cobrir endereço, horários, devolução, defeito e PIX em promoção.
7. **Documentação:** atualizar README, `agente.md` e diagramas.

### Medição que embasa a busca

Teste com o manual dividido em 28 seções e 29 perguntas escritas depois de lê-lo:

| Busca | Certa em 1º | Certa entre as 3 primeiras |
|---|---|---|
| BM25 | 21 | 25 |
| Embeddings multilíngues | 15 | 21 |
| Híbrido | 18 | 22 |

Só um modelo de embeddings foi testado, e o script não está no repositório.

### Interpretações propostas para o manual

- **Telefone:** (67) 3321-4500 para WhatsApp (seção 7) e (67) 3341-4444 para telefone (seção 1.2).
- **E-mail:** `contato@emporiodamusica.com.br`, a forma da capa, sem acento.
- **Parcela mínima:** vale a seção 3.1, mais detalhada que a tabela.

## Pendências para rodar em outro ambiente

- **PDF de políticas:** `políticas_da_loja.pdf` não está no repositório, por decisão do desenvolvedor. O RAG depende dele, que deverá ser enviado antes da etapa 1.
- **Chave de API:** o `.env` não é versionado. Crie-o a partir do `.env.example` ou defina `ANTHROPIC_API_KEY` no ambiente.
- **Banco:** gere com `python -m db.etl`, depois de instalar o `requirements.txt`.
