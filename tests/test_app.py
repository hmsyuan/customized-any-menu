from io import BytesIO

from fastapi.testclient import TestClient

from app.main import app, state

client = TestClient(app)


def setup_function():
    with state.lock:
        state.users.clear()
        state.orders.clear()
        state.menu.type = "json"
        state.menu.title = "未命名菜單"
        state.menu.categories = []
        state.menu.image_path = None


def test_join_limit_10_users():
    for i in range(1, 11):
        resp = client.post("/api/join", data={"name": f"u{i}"})
        assert resp.status_code == 200

    over = client.post("/api/join", data={"name": "u11"})
    assert over.status_code == 400


def test_import_json_menu_and_submit_order():
    menu_json = b'{"title":"t","categories":[{"name":"熱炒類","items":[{"name":"A","price":10}]}]}'
    files = {"file": ("menu.json", BytesIO(menu_json), "application/json")}
    resp = client.post("/api/menu/json", files=files)
    assert resp.status_code == 200

    client.post("/api/join", data={"name": "amy"})
    submit = client.post("/api/order", json={"name": "amy", "items": [{"dish": "A", "price": 10}]})
    assert submit.status_code == 200

    data = client.get("/api/state").json()
    assert data["orders"]["amy"][0]["dish"] == "A"


def test_duplicate_dish_flag():
    client.post("/api/join", data={"name": "amy"})
    client.post("/api/join", data={"name": "bob"})
    client.post("/api/order", json={"name": "amy", "items": [{"dish": "滷肉飯", "price": 80}]})
    client.post("/api/order", json={"name": "bob", "items": [{"dish": "滷肉飯", "price": 80}]})

    data = client.get("/api/state").json()
    assert "滷肉飯" in data["duplicateDishes"]
    assert data["orders"]["amy"][0]["duplicate"] is True
