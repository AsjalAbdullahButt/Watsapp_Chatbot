"""Read-only tools for the check build: product search, stock, order status.

Handlers call services through the BusinessDataSource contract and return only
verified fields. No write tools exist in this build.
"""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.data.source import BusinessDataSource, Product, Variant
from app.tools.registry import Tool, ToolContext, ToolRegistry, ToolResult, ToolStatus

MAX_SEARCH_RESULTS = 5


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SearchProductsArgs(_Strict):
    query: str = Field(min_length=1, max_length=100, description="Words describing the garment, in English, e.g. 'black hoodie'.")


class CheckStockArgs(_Strict):
    sku: str | None = Field(default=None, max_length=40, description="Exact SKU if the customer gave one.")
    product_name: str | None = Field(default=None, max_length=100, description="Product name in English, e.g. 'polo'.")
    size: str | None = Field(default=None, max_length=10, description="Size such as S, M, L, XL or 32.")
    color: str | None = Field(default=None, max_length=30, description="Colour in English, e.g. 'black'.")

    @model_validator(mode="after")
    def _need_sku_or_name(self) -> "CheckStockArgs":
        if not self.sku and not self.product_name:
            raise ValueError("sku or product_name is required")
        return self


class OrderStatusArgs(_Strict):
    order_id: str = Field(pattern=r"^[A-Za-z]{2,5}-?\d{3,10}$", description="Order ID such as ORD-10021.")


def _tokens(text: str) -> set[str]:
    return {t for t in text.lower().replace("/", " ").replace("-", " ").split() if len(t) > 1}


def _variant_view(v: Variant, with_quantity: bool) -> dict[str, object]:
    view: dict[str, object] = {"sku": v.sku, "size": v.size, "color": v.color, "price_pkr": v.price}
    if with_quantity:
        view["quantity_available"] = v.quantity_available
    else:
        view["in_stock"] = v.quantity_available > 0
    return view


def _product_view(p: Product, variants: list[Variant], with_quantity: bool) -> dict[str, object]:
    return {
        "product_id": p.product_id,
        "name": p.name,
        "category": p.category,
        "description": p.description,
        "url": p.url,
        "variants": [_variant_view(v, with_quantity) for v in variants],
    }


def build_registry(source: BusinessDataSource) -> ToolRegistry:
    def search_products(args: SearchProductsArgs, ctx: ToolContext) -> ToolResult:
        wanted = _tokens(args.query)
        scored: list[tuple[int, Product]] = []
        for p in source.list_products():
            variants = source.variants_for(p.product_id)
            haystack = _tokens(f"{p.name} {p.category} {p.description} " + " ".join(f"{v.color} {v.size}" for v in variants))
            score = len(wanted & haystack)
            if score:
                scored.append((score, p))
        if not scored:
            return ToolResult(ToolStatus.NOT_FOUND, message="No products matched.")
        scored.sort(key=lambda s: -s[0])
        hits = [_product_view(p, source.variants_for(p.product_id), with_quantity=False) for _, p in scored[:MAX_SEARCH_RESULTS]]
        return ToolResult(ToolStatus.OK, data=hits)

    def check_stock(args: CheckStockArgs, ctx: ToolContext) -> ToolResult:
        if args.sku:
            v = source.get_variant(args.sku)
            if v is None:
                return ToolResult(ToolStatus.NOT_FOUND, message="No variant with that SKU.")
            product = source.get_product(v.product_id)
            name = product.name if product else v.product_id
            return ToolResult(ToolStatus.OK, data=[{"product": name, **_variant_view(v, with_quantity=True)}])

        wanted = _tokens(args.product_name or "")
        matches: list[dict[str, object]] = []
        for p in source.list_products():
            if not wanted & _tokens(f"{p.name} {p.category}"):
                continue
            for v in source.variants_for(p.product_id):
                if args.size and v.size.lower() != args.size.lower():
                    continue
                if args.color and v.color.lower() != args.color.lower():
                    continue
                matches.append({"product": p.name, **_variant_view(v, with_quantity=True)})
        if not matches:
            return ToolResult(ToolStatus.NOT_FOUND, message="No matching product or variant.")
        return ToolResult(ToolStatus.OK, data=matches)

    def get_order_status(args: OrderStatusArgs, ctx: ToolContext) -> ToolResult:
        if ctx.customer is None:
            return ToolResult(
                ToolStatus.CUSTOMER_NOT_LINKED,
                message="This WhatsApp number is not linked to a customer account.",
            )
        order = source.get_order(args.order_id)
        # Another customer's order is reported exactly like a missing one, so IDs cannot be probed.
        if order is None or order.customer_id != ctx.customer.customer_id:
            return ToolResult(ToolStatus.NOT_FOUND, message="No order with that ID on this customer's account.")
        return ToolResult(
            ToolStatus.OK,
            data={
                "order_id": order.order_id,
                "status": order.status,
                "total_pkr": order.total,
                "placed_on": order.created_at,
                "courier": order.courier,
                "tracking_number": order.tracking_number,
                "items": [{"name": i.name, "quantity": i.quantity} for i in order.items],
            },
        )

    registry = ToolRegistry()
    registry.register(Tool(
        "search_products",
        "Search the garment catalogue. Use when the customer asks what is available, prices, sizes or colours.",
        SearchProductsArgs, search_products,
    ))
    registry.register(Tool(
        "check_stock",
        "Get exact stock quantities for a product or SKU, optionally filtered by size and colour.",
        CheckStockArgs, check_stock,
    ))
    registry.register(Tool(
        "get_order_status",
        "Get status, items, courier and tracking for one of the customer's own orders.",
        OrderStatusArgs, get_order_status,
    ))
    return registry
