# Artefact

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

| Rota | Função | Tool futura |
|---|---|---|
| `GET /products` | Busca por texto e filtra por categoria, marca, preço, material, eletrônica, disponibilidade e promoção | `search_products` |
| `GET /promotions` | Lista as promoções vigentes | `list_promotions` |
| `GET /categories` | Lista as categorias e quantos produtos cada uma tem | `list_categories` |
| `POST /orders/lookup` | Consulta um pedido com número e telefone | `get_order_status` |
| `POST /orders/search` | Lista os pedidos de um cliente com telefone e e-mail | `list_customer_orders` |

- **Tools específicas em vez de SQL gerado pelo LLM:** o agente só faz consultas previstas, e os parâmetros são validados pelo Pydantic e passados ao banco separados da consulta.
- **Camadas:** `api/store.py` contém as consultas e `api/main.py` só as expõe por HTTP. As tools podem chamar `Store` diretamente, sem depender do servidor.
- **Somente leitura:** a conexão abre o banco com `mode=ro`.
- **Busca:** ignora acentos e hífens, e procura cada termo como substring do nome, marca, categoria, descrição, cor ou material. Todos os termos precisam aparecer; não há correção de erros, stemming, stopwords ou ordenação por relevância. Resultados são ordenados por disponibilidade, preço e ID.
- **Disponibilidade:** produtos esgotados, descontinuados ou "em breve" aparecem por padrão, identificados no campo `availability`, para o agente poder explicar a situação. `available_only=true` os exclui.
- **Pedidos:** a autorização é feita em código, não no prompt. Telefone errado e pedido inexistente recebem a mesma resposta, e a API só devolve o primeiro nome do cliente. Telefone e e-mail vão no corpo do POST para não aparecerem em URLs.

**Limitações:** a autorização depende de dados que outra pessoa pode conhecer, pois a base não tem senha nem código de confirmação, e a API não limita tentativas. Em produção, seriam necessários código por SMS ou WhatsApp e limite de tentativas. A API também não tem autenticação, então deve rodar apenas localmente.

## Decisões técnicas obrigatórias

### Framework(s) / abordagem do agente
    RAG, function calling, ReAct, agente de SQL, híbrido, etc. 

### Modelo e Provedor 
    Você pode escolher modelos pagos ou grátis, locais ou via API.  

### Interface de interação 
    CLI, notebook, API, ou UI simples — o foco é o agente funcionando corretamente. 

### Persistência do histórico de conversa 
    Implemente se fizer sentido para a experiência do usuário. 

### Tratamento dos dados

Os CSVs são tratados com pandas e viram um banco SQLite somente leitura. O banco não vai para o repositório. Para gerá-lo e testá-lo, a partir da raiz (testado com Python 3.13):

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m db.etl
python -m unittest db.test_etl
```

No Linux ou macOS, ative o ambiente com `source .venv/bin/activate`.

- **Por que pandas:** as transformações ficam concisas e a leitura e a carga usam funções prontas (`read_csv` e `to_sql`). As restrições continuam no `schema.sql`, porque `to_sql` só insere nas tabelas já criadas.
- **Por que SQLite:** preço, estoque e pedido pedem filtros exatos. O banco é um único arquivo e não exige um servidor.
- **Tipos e integridade:** tabelas `STRICT`, chaves estrangeiras e `CHECK` rejeitam valores inválidos na carga.
- **Valores vazios:** viram `NULL`.
- **`specs`:** cor, material das cordas e eletrônica viram colunas, com valores em português. Na origem, `strings` guardava ora o material, ora a quantidade de cordas; a quantidade agora fica em `string_count`.
- **Busca:** `name_search` e `category_search` não têm acento nem hífen, e `brand` é extraída do nome.
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
