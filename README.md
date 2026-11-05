# Empório da Música: agente de atendimento

Agente de mensagens de texto que atende clientes de uma loja de instrumentos, consultando catálogo, promoções, pedidos e as políticas da loja.

## Como rodar

Testado com Python 3.13. Crie o ambiente, instale as dependências e gere o banco:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python -m db.etl
python -m rag.ingest
```

Preencha `ANTHROPIC_API_KEY` no `.env`. No Linux ou macOS, use `source .venv/bin/activate` e `cp`. Depois, suba a API:

```bash
python main.py
```

Em outro terminal, com o ambiente ativado, escolha um dos clientes:

```bash
# CLI
python -m agent.cli

# Interface web (cliente independente)
streamlit run streamlit_app.py
```

CLI e Streamlit são processos independentes; cada um mantém seu próprio agente e histórico de conversa. Ambos acessam a mesma API de dados, que deve continuar rodando em seu próprio terminal.

Testes, sem chave de API:

```bash
python -m unittest db.test_etl api.test_api agent.test_tools agent.test_graph rag.test_rag
```

O funcionamento interno está em [docs/agente.md](docs/agente.md).

## Uso de Agentes de IA

## API de dados

Com o banco gerado (veja "Tratamento dos dados"), inicie o servidor a partir da raiz:

```bash
python main.py
```

Também é possível iniciar diretamente pelo Uvicorn: `uvicorn api.main:app --reload`.
A documentação interativa fica em `http://127.0.0.1:8000/docs`. Para testar:

```bash
python -m unittest db.test_etl api.test_api
```

| Rota | Função | Tool |
|---|---|---|
| `GET /products` | Busca por texto e filtra por categoria, preço, material, eletrônica, disponibilidade e promoção | `search_products` |
| `GET /promotions` | Lista as promoções vigentes | `list_promotions` |
| `GET /categories` | Lista as categorias e quantos produtos cada uma tem | `list_categories` |
| `POST /orders/lookup` | Consulta um pedido com número e telefone | `get_order_status` |
| `POST /orders/search` | Lista os pedidos de um cliente com telefone e e-mail | `list_customer_orders` |
| `POST /policies/search` | Busca nas políticas da loja | `search_policies` |
| `POST /escalations` | Registra um atendimento para a equipe e devolve um protocolo | `escalate_to_human` |

- **Tools específicas em vez de SQL gerado pelo LLM:** o agente só faz consultas previstas, e os parâmetros são validados pelo Pydantic e passados ao banco separados da consulta.
- **Camadas:** `api/store.py` contém as consultas e `api/main.py` as expõe por HTTP. O agente acessa os dados só pela API, em outro processo.
- **Somente leitura:** a conexão abre o banco com `mode=ro`. A única escrita da API são os encaminhamentos à equipe, em `api/escalations.jsonl`, fora do banco e do repositório. Em produção, iriam para uma fila ou um CRM.
- **Busca:** ignora acentos e hífens, e procura cada termo como substring do nome, categoria, descrição, cor ou material. Todos os termos precisam aparecer; não há correção de erros, stemming, stopwords ou ordenação por relevância. Resultados são ordenados por disponibilidade, preço e ID.
- **Disponibilidade:** produtos esgotados, descontinuados ou "em breve" aparecem por padrão, identificados no campo `availability`, para o agente poder explicar a situação. `available_only=true` os exclui.
- **Pedidos:** a autorização é feita em código, não no prompt. Telefone errado e pedido inexistente recebem a mesma resposta, e a API só devolve o primeiro nome do cliente. Telefone e e-mail vão no corpo do POST para não aparecerem em URLs.

**Limitações:** a autorização depende de dados que outra pessoa pode conhecer, pois a base não tem senha nem código de confirmação, e a API não limita tentativas. Em produção, seriam necessários código por SMS ou WhatsApp e limite de tentativas. A API também não tem autenticação, então deve rodar apenas localmente.

## Decisões técnicas obrigatórias

### Framework(s) / abordagem do agente

Function calling orquestrado com **LangGraph** (`StateGraph`, `ToolNode` e `tools_condition`).

- **Por que function calling:** o agente precisa decidir quando consultar cada fonte, e tools específicas limitam o que ele pode fazer. O acesso a pedidos, por exemplo, é verificado em código.
- **Por que não um agente de SQL:** gerar SQL expõe a base inteira, inclusive dados de outros clientes.
- **Por que LangGraph:** para o fluxo atual, um loop próprio bastaria. O framework foi escolhido para demonstrar domínio dele e porque deixa o fluxo explícito, com memória por sessão e espaço para evoluir.
- **Por que `StateGraph`, e não o `create_agent` do LangChain:** os nós e as transições ficam visíveis no código, em vez de escondidos em uma abstração.
- **Por que API separada:** os dados e o índice de políticas ficam fora do agente, que só alcança o que as rotas permitem. O contrato fica em `contracts/`, e o custo é ter dois processos para subir.

### Arquitetura de retrieval

O manual é dividido por seção, e a busca é feita com **BM25**, chamado pelo LLM por meio da tool `search_policies`.

- **Por que tool:** o desafio pede que o agente saiba quando consultar as políticas. Com a tool, a decisão fica explícita e o manual não é enviado em toda chamada. Com cerca de 3.100 tokens, colocá-lo inteiro no prompt também funcionaria.
- **Por que por seção:** o manual já é organizado por assunto, e cada subseção responde a uma dúvida.
- **Por que BM25:** em 29 perguntas, acertou 25 entre os 3 primeiros resultados, contra 21 de um modelo de embeddings multilíngue e 22 da combinação dos dois, sem exigir download de modelo. Só um modelo foi testado, e o documento é pequeno.
- **Palavras-chave:** cada seção recebe termos que o cliente usa e o manual não, como "rastreio". Medida em 10 perguntas novas, a busca acertou 7 entre os 3 primeiros resultados. Com o modelo real, o agente reformulou a busca e respondeu certo a duas das perguntas em que ela falhava ("mudei de ideia" e "Dourados").
- **Seções internas:** instruções para a equipe (7.1, 7.2, 7.3 e 10) ficam fora do índice.
- **Extração:** PyMuPDF, de licença AGPL, usado só na ingestão.

### Interpretações do manual

O manual se contradiz em alguns pontos. As interpretações adotadas foram:

- **Telefone:** (67) 3321-4500 para WhatsApp e (67) 3341-4444 para telefone.
- **E-mail:** `contato@emporiodamusica.com.br`, a forma da capa, sem acento.
- **Parcela mínima:** valem as regras por faixa de parcelas (seção 3.1), mais detalhadas que a tabela geral.

### Modelo e Provedor 

**Claude Haiku 5.5**, via API da Anthropic, configurável por `AGENT_MODEL`. Pelo preço de tabela consultado (US$ 0,10 por milhão de tokens de entrada e US$ 0,50 de saída), repetir os testes custa pouco. Limitação conhecida: ele às vezes escreve "No" no lugar de "Não" ("No, não temos saxofone"). Reforçar o prompt e aumentar o esforço não resolveram, e o Sonnet 5.5 não apresentou o problema em uma amostra menor. O custo menor foi priorizado neste protótipo.

### Interface de interação 

**CLI e Streamlit** como dois clientes independentes do agente. Cada interface chama `Agent.respond` sem depender da outra; ambas acessam a API de dados separadamente.

### Persistência do histórico de conversa 

**Em memória, por sessão**, com o `InMemorySaver` do LangGraph. Faz sentido porque perguntas como "e tem em estoque?" dependem da mensagem anterior. O histórico se perde ao reiniciar, o que é aceitável em um protótipo.

### Tratamento dos dados

Os CSVs são tratados com pandas e viram um banco SQLite somente leitura. O banco não vai para o repositório: é gerado por `python -m db.etl`.

- **Por que pandas:** as transformações ficam concisas e a leitura e a carga usam funções prontas (`read_csv` e `to_sql`). As restrições continuam no `schema.sql`, porque `to_sql` só insere nas tabelas já criadas.
- **Por que SQLite:** preço, estoque e pedido pedem filtros exatos. O banco é um único arquivo e não exige um servidor.
- **Tipos e integridade:** tabelas `STRICT`, chaves estrangeiras e `CHECK` rejeitam valores inválidos na carga.
- **Valores vazios:** viram `NULL`.
- **`specs`:** cor, material das cordas e eletrônica viram colunas, com valores em português. Na origem, `strings` guardava ora o material, ora a quantidade de cordas; a quantidade agora fica em `string_count`.
- **Busca:** `name_search` e `category_search` não têm acento nem hífen.
- **Pagamento:** `credit_6x` vira `payment_method = 'credit'` e `installments = 6`.
- **Regras de negócio:** a view `v_products` define a disponibilidade e o preço final, considerando só promoções ativas.
- **Correção manual:** a única é o nome truncado "Cedr" → "Cedro" (produto 84).

**Limitações dos dados.** O ETL reporta estes pontos e mantém os valores originais:

- Os pedidos 3 e 20 têm total diferente de quantidade × preço atual. Como os itens não guardam o preço da venda, `total_brl` é tratado como o valor cobrado.
- Os clientes 11 e 43 compartilham o e-mail, então a identificação usa o telefone, que é único.
- O produto 130 está como "em breve", mas já aparece em pedidos, um deles entregue.
- O produto 136 está descontinuado, mas tem estoque. O status prevalece e ele não é oferecido.
- Três categorias não têm produtos, embora o manual cite esses instrumentos.
- Os pedidos vão só até 2026-03-22 e não há data real de entrega. Promoções não têm período, então vale apenas `is_active`.
