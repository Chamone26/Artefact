"""Entradas e saídas das consultas. As descrições também servirão de contrato para as tools do agente."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Availability = Literal["disponivel", "esgotado", "em_breve", "descontinuado"]


def normalize_phone(phone):
    """Aceita qualquer formatação e devolve DDD + número, sem o código do país."""
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("55") and len(digits) in (12, 13):
        digits = digits[2:]
    if len(digits) not in (10, 11):
        raise ValueError("telefone deve ter DDD e número")
    return digits


class ProductSearch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str | None = Field(None, max_length=200, description="Modelo, marca, tipo ou característica. Ex.: 'Takamine GD20'")
    category: str | None = Field(None, max_length=100, description="Categoria do produto. Ex.: 'violão', 'guitarra'")
    brand: str | None = Field(None, max_length=100, description="Marca exata. Ex.: 'Yamaha'")
    min_price: float | None = Field(None, ge=0, description="Preço final mínimo em reais")
    max_price: float | None = Field(None, ge=0, description="Preço final máximo em reais")
    string_material: Literal["nylon", "aço"] | None = Field(None, description="Material das cordas de violões e ukuleles")
    has_electronics: bool | None = Field(None, description="Se violões e ukuleles têm captação elétrica")
    available_only: bool = Field(False, description="Traz só produtos que podem ser comprados agora")
    on_promotion: bool = Field(False, description="Traz só produtos com promoção vigente")
    limit: int = Field(10, ge=1, le=20, description="Quantidade máxima de produtos")

    @model_validator(mode="after")
    def check_price_range(self):
        if self.min_price is not None and self.max_price is not None and self.min_price > self.max_price:
            raise ValueError("min_price não pode ser maior que max_price")
        return self


class Product(BaseModel):
    product_id: int
    name: str
    brand: str
    category: str
    description: str
    color: str | None
    string_material: str | None
    has_electronics: bool | None
    specs: dict
    availability: Availability
    stock_quantity: int
    price_brl: float = Field(description="Preço de tabela")
    discount_percent: float | None = Field(description="Desconto da promoção vigente, se houver")
    promotion: str | None
    final_price_brl: float = Field(description="Preço com a promoção vigente, sem outros descontos")


class ProductSearchResult(BaseModel):
    total: int = Field(description="Total de produtos encontrados, mesmo os que passam do limite")
    products: list[Product]


class Category(BaseModel):
    category_id: int
    name: str
    description: str
    product_count: int


class OrderLookup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: int = Field(gt=0, description="Número do pedido")
    phone: str = Field(max_length=30, description="Telefone do cliente que fez o pedido")

    _normalize_phone = field_validator("phone")(normalize_phone)


class CustomerOrdersLookup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str = Field(max_length=30, description="Telefone do cliente")
    email: str = Field(max_length=254, description="E-mail do cliente")

    _normalize_phone = field_validator("phone")(normalize_phone)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, email):
        email = email.strip().casefold()
        if "@" not in email:
            raise ValueError("e-mail inválido")
        return email


class OrderItem(BaseModel):
    product_id: int
    product_name: str
    quantity: int


class Order(BaseModel):
    """Só expõe o primeiro nome do cliente: e-mail e telefone completos não saem da API."""

    order_id: int
    customer_first_name: str
    order_date: str
    status: Literal["pending", "confirmed", "shipped", "delivered", "cancelled"]
    status_label: str
    total_brl: float = Field(description="Valor cobrado no pedido")
    payment_method: Literal["pix", "debit", "credit", "boleto"]
    installments: int | None
    tracking_code: str | None
    estimated_delivery: str | None = Field(description="Previsão de entrega; a data real de entrega não é registrada")
    notes: str | None
    items: list[OrderItem]
