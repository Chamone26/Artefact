# Devolução de um pedido (caso não trivial)

Combina três fontes: a política de devolução, a verificação do telefone e os dados do pedido. A data de referência do agente é 2026-03-25, logo depois do último pedido da base.

**Cliente:** Me arrependi da minha compra, posso devolver meu pedido?

Tools chamadas: `search_policies(query='arrependimento devolução prazo')`

**Agente:**

Sim, dá para devolver por arrependimento, sem precisar explicar o motivo. Algumas regras:

- O prazo é de até 7 dias corridos após o recebimento do produto. Como ainda não temos a data real de entrega, a contagem é feita a partir da previsão de entrega do seu pedido.
- O produto precisa estar na embalagem original, sem sinais de uso, com todos os acessórios e manuais.
- O reembolso é feito na mesma forma de pagamento usada na compra, em até 10 dias úteis.
- Se for arrependimento, o frete da devolução fica por conta da loja.

Para eu conferir o seu pedido e o prazo, me passa o número do pedido e o telefone usado na compra.

**Cliente:** É o pedido 1, meu telefone é (67) 98432-1098

Tools chamadas: `get_order_status(order_id=1, phone='***')`

**Agente:**

Pedro, localizei o seu pedido 1, do Martin D-28 Dreadnought Natural. Ele consta como entregue, com previsão de entrega em 25/10/2025.

Infelizmente, o prazo de 7 dias para arrependimento já passou. Contando a partir dessa previsão, ele terminou no início de novembro de 2025, e hoje estamos em 25/03/2026.

Se quiser, posso registrar seu caso para a equipe da loja analisar. Eles são quem decide se é possível abrir uma exceção, e eu não consigo garantir nada. Quer que eu registre?
