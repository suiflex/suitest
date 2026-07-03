"""Brewly — tiny coffee-shop order app used as the Suitest demo target.

Fixture app, not a product: in-memory state, no auth, deterministic seed data.
"""

from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BULK_DISCOUNT_MIN_QTY = 4
BULK_DISCOUNT_RATE = 0.10

app = FastAPI(title="Brewly", version="1.0.0", description="Demo coffee-shop order API")


@dataclass
class MenuItem:
    id: int
    name: str
    price: float
    stock: int


@dataclass
class Order:
    id: int
    item_id: int
    quantity: int
    total: float
    status: str = "pending"


@dataclass
class State:
    menu: dict[int, MenuItem] = field(default_factory=dict)
    orders: dict[int, Order] = field(default_factory=dict)
    next_order_id: int = 1


_state = State()


def reset_state() -> None:
    _state.menu = {
        1: MenuItem(1, "Espresso", 3.00, 10),
        2: MenuItem(2, "Latte", 4.50, 10),
        3: MenuItem(3, "Cold Brew", 4.00, 10),
        4: MenuItem(4, "Matcha Latte", 5.00, 10),
    }
    _state.orders = {}
    _state.next_order_id = 1


reset_state()


class MenuItemOut(BaseModel):
    id: int
    name: str
    price: float
    stock: int


class OrderCreate(BaseModel):
    item_id: int
    quantity: int = Field(gt=0, le=100)


class OrderOut(BaseModel):
    id: int
    item_id: int
    quantity: int
    total: float
    status: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/reset", status_code=204)
def reset() -> None:
    reset_state()


@app.get("/api/menu", response_model=list[MenuItemOut])
def list_menu() -> list[MenuItem]:
    return sorted(_state.menu.values(), key=lambda i: i.id)


@app.post("/api/orders", response_model=OrderOut, status_code=201)
def create_order(payload: OrderCreate) -> Order:
    item = _state.menu.get(payload.item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="unknown menu item")
    if item.stock < payload.quantity:
        raise HTTPException(status_code=409, detail="insufficient stock")
    item.stock -= payload.quantity
    order = Order(
        id=_state.next_order_id,
        item_id=item.id,
        quantity=payload.quantity,
        total=round(item.price * payload.quantity, 2),
    )
    _state.orders[order.id] = order
    _state.next_order_id += 1
    return order


@app.get("/api/orders/{order_id}", response_model=OrderOut)
def get_order(order_id: int) -> Order:
    order = _state.orders.get(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    return order


@app.post("/api/orders/{order_id}/checkout", response_model=OrderOut)
def checkout(order_id: int) -> Order:
    order = _state.orders.get(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    if order.status == "paid":
        raise HTTPException(status_code=409, detail="order already paid")
    total = order.total
    if order.quantity >= BULK_DISCOUNT_MIN_QTY:
        total = round(total * (1 - BULK_DISCOUNT_RATE), 2)
    order.total = total
    order.status = "paid"
    return order


_static = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=_static), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(_static / "index.html")
