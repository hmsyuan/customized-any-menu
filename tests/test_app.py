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


def test_import_json_menu_and_submit_order():
    menu_json = '{"title":"t","categories":[{"name":"熱炒類","items":[{"name":"A","price":10}]}]}'.encode("utf-8")
    client.post("/api/join", data={"name": "amy"})

    files = {"file": ("menu.json", BytesIO(menu_json), "application/json")}
    resp = client.post("/api/menu/json", data={"name": "amy"}, files=files)
    assert resp.status_code == 200

    submit = client.post("/api/order", json={"name": "amy", "items": [{"dish": "A", "price": 10}]})
    assert submit.status_code == 200

    data = client.get("/api/state").json()
    assert data["orders"]["amy"][0]["dish"] == "A"


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
    client.post("/api/order", json={"name": "amy", "items": [{"dish": "滷肉飯", "price": 80}]})
    client.post("/api/order", json={"name": "bob", "items": [{"dish": "滷肉飯", "price": 80}]})

    data = client.get("/api/state").json()
    assert "滷肉飯" in data["duplicateDishes"]
    assert data["orders"]["amy"][0]["duplicate"] is True
