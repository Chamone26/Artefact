"""Cliente da API de dados (api/main.py), único ponto em que o agente fala com o servidor.

Concentrar o HTTP aqui mantém timeouts e tradução de erros em um só lugar. As tools só lidam com
dois resultados possíveis além do sucesso: "a API recusou a entrada" e "a API está indisponível".
"""

import httpx2

DEFAULT_TIMEOUT_SECONDS = 10


class ApiUnavailableError(Exception):
    """Servidor fora do ar, lento demais ou com erro interno: não adianta o LLM mudar a chamada."""


class ApiRejectedError(Exception):
    """A API recusou os parâmetros (HTTP 4xx): o LLM pode corrigir a chamada e tentar de novo."""


class StoreApiClient:
    def __init__(self, http_client):
        # Recebe o cliente pronto para os testes injetarem o TestClient do FastAPI, que herda de
        # httpx2.Client e chama a API em memória, sem servidor.
        self._http = http_client

    @classmethod
    def from_url(cls, base_url, timeout=DEFAULT_TIMEOUT_SECONDS):
        return cls(httpx2.Client(base_url=base_url, timeout=timeout))

    def _request(self, method, path, **kwargs):
        """Devolve o JSON da resposta, ou None em 404 (consulta válida sem resultado)."""
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx2.TransportError as error:
            raise ApiUnavailableError(f"Falha ao acessar a API em {path}: {error}") from error
        if response.status_code == 404:
            return None
        if response.status_code >= 500:
            raise ApiUnavailableError(f"A API respondeu {response.status_code} em {path}.")
        if response.status_code >= 400:
            raise ApiRejectedError(f"Parâmetros recusados pela API: {response.json().get('detail')}")
        return response.json()

    def search_products(self, **filters):
        return self._request("GET", "/products", params=filters)

    def list_promotions(self):
        return self._request("GET", "/promotions")

    def list_categories(self):
        return self._request("GET", "/categories")

    def get_order(self, order_id, phone):
        # Telefone e e-mail vão no corpo do POST para não aparecerem em URLs e logs de acesso.
        return self._request("POST", "/orders/lookup", json={"order_id": order_id, "phone": phone})

    def list_customer_orders(self, phone, email):
        return self._request("POST", "/orders/search", json={"phone": phone, "email": email})

    def search_policies(self, query, limit=3):
        return self._request("POST", "/policies/search", json={"query": query, "limit": limit})
