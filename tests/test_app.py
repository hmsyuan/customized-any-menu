from io import BytesIO

from fastapi.testclient import TestClient

from app.main import app, state

client = TestClient(app)


def setup_function():
    with state.lock:
        state.reset_all()


def test_join_limit_10_users():
    for i in range(1, 11):
        resp = client.post("/api/join", data={"name": f"u{i}"})
        assert resp.status_code == 200

    over = client.post("/api/join", data={"name": "u11"})
    assert over.status_code == 400


def test_import_json_menu_and_submit_order_with_quantity():
    menu_json = '{"title":"t","categories":[{"name":"熱炒類","items":[{"name":"A","price":10}]}]}'.encode("utf-8")
    client.post("/api/join", data={"name": "amy"})

    files = {"file": ("menu.json", BytesIO(menu_json), "application/json")}
    resp = client.post("/api/menu/json", data={"name": "amy"}, files=files)
    assert resp.status_code == 200

    submit = client.post(
        "/api/order",
        json={"name": "amy", "items": [{"dish": "A", "size": "中", "price": 10, "quantity": 3}]},
    )
    assert submit.status_code == 200

    data = client.get("/api/state").json()
    assert data["orders"]["amy"][0]["quantity"] == 3
    assert data["orders"]["amy"][0]["lineTotal"] == 30


def test_aggregated_orders():
    client.post("/api/join", data={"name": "amy"})
    client.post("/api/join", data={"name": "bob"})

    client.post(
        "/api/order", json={"name": "amy", "items": [{"dish": "滷肉飯", "size": "中", "price": 80, "quantity": 2}]}
    )
    client.post(
        "/api/order", json={"name": "bob", "items": [{"dish": "滷肉飯", "size": "中", "price": 80, "quantity": 1}]}
    )

    data = client.get("/api/state").json()
    row = data["aggregatedOrders"][0]
    assert row["dish"] == "滷肉飯"
    assert row["size"] == "中"
    assert row["quantity"] == 3
    assert row["totalPrice"] == 240
    assert data["aggregatedGrandTotal"] == 240


def test_host_lock_and_release():
    menu_json = '{"冷盤類":[{"名稱":"寧粉一隻","價格":600}]}'.encode("utf-8")
    client.post("/api/join", data={"name": "amy"})
    client.post("/api/join", data={"name": "bob"})

    files = {"file": ("menu.json", BytesIO(menu_json), "application/json")}
    first = client.post("/api/menu/json", data={"name": "amy"}, files=files)
    assert first.status_code == 200

    second = client.post("/api/menu/json", data={"name": "bob"}, files=files)
    assert second.status_code == 403

    release = client.post("/api/host/release", json={"name": "amy"})
    assert release.status_code == 200

    third = client.post("/api/menu/json", data={"name": "bob"}, files=files)
    assert third.status_code == 200


def test_session_expired_clears_everything():
    client.post("/api/join", data={"name": "amy"})

    with state.lock:
        state.host = "amy"
        state.users.add("amy")
        state.orders["amy"] = []
        state.session_started_at -= 3661

    data = client.get("/api/state").json()
    assert data["users"] == []
    assert data["host"] is None


def test_duplicate_dish_flag():
    client.post("/api/join", data={"name": "amy"})
    client.post("/api/join", data={"name": "bob"})
    client.post(
        "/api/order", json={"name": "amy", "items": [{"dish": "滷肉飯", "size": "中", "price": 80, "quantity": 1}]}
    )
    client.post(
        "/api/order", json={"name": "bob", "items": [{"dish": "滷肉飯", "size": "中", "price": 80, "quantity": 1}]}
    )

    data = client.get("/api/state").json()
    assert "滷肉飯" in data["duplicateDishes"]
    assert data["orders"]["amy"][0]["duplicate"] is True


def test_import_json_supports_size_price_mapping():
    menu_json = (
        '{"title":"t","categories":[{"name":"砂鍋類","items":[{"name":"酸菜鮮","price":{"小":420,"中":520,"大":620}}]}]}'
    ).encode("utf-8")
    client.post("/api/join", data={"name": "amy"})

    files = {"file": ("menu.json", BytesIO(menu_json), "application/json")}
    resp = client.post("/api/menu/json", data={"name": "amy"}, files=files)
    assert resp.status_code == 200

    state_data = client.get("/api/state").json()
    item = state_data["menu"]["categories"][0]["items"][0]
    assert item["sizeOptions"] == [
        {"size": "小", "price": 420},
        {"size": "中", "price": 520},
        {"size": "大", "price": 620},
    ]


def test_only_host_can_delete_submitted_item():
    client.post("/api/join", data={"name": "amy"})
    client.post("/api/join", data={"name": "bob"})

    menu_json = '{"冷盤類":[{"名稱":"寧粉一隻","價格":600}]}'.encode("utf-8")
    files = {"file": ("menu.json", BytesIO(menu_json), "application/json")}
    client.post("/api/menu/json", data={"name": "amy"}, files=files)

    client.post(
        "/api/order", json={"name": "bob", "items": [{"dish": "寧粉一隻", "size": "中", "price": 600, "quantity": 1}]}
    )

    forbidden = client.post(
        "/api/order/delete-submitted-item",
        json={"actor": "bob", "target_user": "bob", "item_index": 0},
    )
    assert forbidden.status_code == 403

    deleted = client.post(
        "/api/order/delete-submitted-item",
        json={"actor": "amy", "target_user": "bob", "item_index": 0},
    )
    assert deleted.status_code == 200

    data = client.get("/api/state").json()
    assert data["orders"]["bob"] == []
