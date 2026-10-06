"""Business data source contract.

The agent never sees this layer directly: tools call services, services call a
BusinessDataSource. Today it is JsonDataSource (sample file). Later a SQL Server
adapter for the existing VB.NET system implements the same Protocol, and nothing
above this layer changes.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Variant:
    sku: str
    product_id: str
    size: str
    color: str
    price: int  # PKR, whole rupees
    quantity_available: int


@dataclass(frozen=True)
class Product:
    product_id: str
    name: str
    category: str
    description: str
    url: str | None


@dataclass(frozen=True)
class OrderItem:
    sku: str
    name: str
    quantity: int
    unit_price: int


@dataclass(frozen=True)
class Order:
    order_id: str
    customer_id: str
    status: str
    total: int
    created_at: str
    courier: str | None
    tracking_number: str | None
    items: tuple[OrderItem, ...]


@dataclass(frozen=True)
class Customer:
    customer_id: str
    name: str
    phone: str  # digits only, international format, e.g. 923001234567


class BusinessDataSource(Protocol):
    def list_products(self) -> list[Product]: ...
    def variants_for(self, product_id: str) -> list[Variant]: ...
    def get_variant(self, sku: str) -> Variant | None: ...
    def get_product(self, product_id: str) -> Product | None: ...
    def get_order(self, order_id: str) -> Order | None: ...
    def find_customer_by_phone(self, phone: str) -> Customer | None: ...


def normalize_phone(raw: str) -> str:
    """Digits only; Pakistani local numbers (03xx...) become 923xx..."""
    digits = "".join(ch for ch in raw if ch.isdigit())
    if digits.startswith("0") and len(digits) == 11:
        digits = "92" + digits[1:]
    return digits


class JsonDataSource:
    """Read-only data source backed by a JSON file. Loaded once at startup."""

    def __init__(self, path: str | Path) -> None:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        self._products = {p["product_id"]: Product(**p) for p in raw["products"]}
        self._variants = {v["sku"]: Variant(**v) for v in raw["variants"]}
        self._customers = [
            Customer(c["customer_id"], c["name"], normalize_phone(c["phone"])) for c in raw["customers"]
        ]
        self._orders: dict[str, Order] = {}
        for o in raw["orders"]:
            items = tuple(OrderItem(**i) for i in o["items"])
            self._orders[o["order_id"].upper()] = Order(**{**o, "items": items})

    def list_products(self) -> list[Product]:
        return list(self._products.values())

    def variants_for(self, product_id: str) -> list[Variant]:
        return [v for v in self._variants.values() if v.product_id == product_id]

    def get_variant(self, sku: str) -> Variant | None:
        return self._variants.get(sku.upper())

    def get_product(self, product_id: str) -> Product | None:
        return self._products.get(product_id)

    def get_order(self, order_id: str) -> Order | None:
        return self._orders.get(order_id.strip().upper())

    def find_customer_by_phone(self, phone: str) -> Customer | None:
        target = normalize_phone(phone)
        return next((c for c in self._customers if c.phone == target), None)
