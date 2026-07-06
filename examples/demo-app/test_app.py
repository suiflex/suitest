from app import app, reset_state
from fastapi.testclient import TestClient

client = TestClient(app)


def setup_function() -> None:
    reset_state()


def test_menu_returns_fixed_items() -> None:
    r = client.get("/api/menu")
    assert r.status_code == 200
    names = [i["name"] for i in r.json()]
    assert names == ["Espresso", "Latte", "Cold Brew", "Matcha Latte"]


def test_create_order_decrements_stock() -> None:
    r = client.post("/api/orders", json={"item_id": 1, "quantity": 2})
    assert r.status_code == 201
    assert r.json()["total"] == 6.0  # espresso 3.00 * 2
    menu = client.get("/api/menu").json()
    assert menu[0]["stock"] == 8  # started at 10


def test_order_rejects_out_of_stock() -> None:
    r = client.post("/api/orders", json={"item_id": 3, "quantity": 99})
    assert r.status_code == 409
    assert r.json()["detail"] == "insufficient stock"


def test_checkout_applies_bulk_discount() -> None:
    order = client.post("/api/orders", json={"item_id": 2, "quantity": 5}).json()
    r = client.post(f"/api/orders/{order['id']}/checkout")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "paid"
    assert body["total"] == 20.25  # latte 4.50*5=22.50, 10% off >= 4 items


def test_get_unknown_order_404() -> None:
    assert client.get("/api/orders/999").status_code == 404
