from __future__ import annotations

import json
import uuid
from collections import Counter
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


class OrderItem(BaseModel):
    dish: str
    price: int = Field(ge=0, default=0)


class MenuState(BaseModel):
    type: str = "json"
    title: str = "未命名菜單"
    categories: list[dict[str, Any]] = Field(default_factory=list)
    image_path: str | None = None


class AppState:
    def __init__(self) -> None:
        self.lock = Lock()
        self.menu = MenuState()
        self.users: set[str] = set()
        self.orders: dict[str, list[OrderItem]] = {}

    def reset_orders(self) -> None:
        self.orders = {name: [] for name in self.users}


def normalize_menu_payload(payload: Any) -> tuple[str, list[dict[str, Any]]]:
    """Accept both old schema and map-style Chinese schema.

    Supported examples:
    1) {"title": "...", "categories": [{"name":"熱炒", "items":[{"name":"A","price":1}]}]}
    2) {"冷盤類": [{"名稱":"寧粉一隻", "價格":600}], "熱炒類": [...]} 
    """
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON 根節點必須是物件")

    if isinstance(payload.get("categories"), list):
        categories_raw = payload["categories"]
        title = str(payload.get("title") or "未命名菜單")
    else:
        # Treat keys as category names.
        categories_raw = [{"name": key, "items": value} for key, value in payload.items() if isinstance(value, list)]
        title = "未命名菜單"

    categories: list[dict[str, Any]] = []
    for category in categories_raw:
        if not isinstance(category, dict):
            continue

        category_name = str(category.get("name") or category.get("分類") or category.get("category") or "未分類")
        items_raw = category.get("items", [])
        if not isinstance(items_raw, list):
            continue

        normalized_items: list[dict[str, Any]] = []
        for item in items_raw:
            if not isinstance(item, dict):
                continue

            dish_name = str(item.get("name") or item.get("名稱") or item.get("菜名") or "").strip()
            if not dish_name:
                continue

            raw_price = item.get("price", item.get("價格", 0))
            try:
                price = max(0, int(raw_price))
            except (TypeError, ValueError):
                price = 0

            normalized_items.append({"name": dish_name, "price": price})

        categories.append({"name": category_name, "items": normalized_items})

    if not categories:
        raise HTTPException(status_code=400, detail="找不到可用的分類/菜色資料")

    return title, categories


state = AppState()
app = FastAPI(title="customized-any-menu")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/join")
def join(name: str = Form(...)) -> dict[str, str]:
    clean = name.strip()
    if not clean:
        raise HTTPException(status_code=400, detail="名稱不能空白")

    with state.lock:
        if clean not in state.users and len(state.users) >= 10:
            raise HTTPException(status_code=400, detail="目前最多 10 位使用者")
        state.users.add(clean)
        state.orders.setdefault(clean, [])

    return {"name": clean}


@app.post("/api/menu/json")
async def import_menu_json(file: UploadFile = File(...)) -> dict[str, str]:
    try:
        raw = await file.read()
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="JSON 格式錯誤") from exc

    title, categories = normalize_menu_payload(payload)

    with state.lock:
        state.menu = MenuState(type="json", title=title, categories=categories, image_path=None)
        state.reset_orders()

    return {"message": "JSON 菜單已匯入"}


@app.post("/api/menu/image")
async def import_menu_image(file: UploadFile = File(...)) -> dict[str, str]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(status_code=400, detail="僅支援 png/jpg/jpeg/webp")

    filename = f"{uuid.uuid4().hex}{suffix}"
    save_path = UPLOAD_DIR / filename
    content = await file.read()
    save_path.write_bytes(content)

    with state.lock:
        state.menu = MenuState(type="image", title="圖片菜單", categories=[], image_path=f"/uploads/{filename}")
        state.reset_orders()

    return {"message": "圖片菜單已匯入"}


class SubmitOrderPayload(BaseModel):
    name: str
    items: list[OrderItem]


@app.post("/api/order")
def submit_order(payload: SubmitOrderPayload) -> dict[str, str]:
    with state.lock:
        if payload.name not in state.users:
            raise HTTPException(status_code=400, detail="請先加入並命名")
        state.orders[payload.name] = payload.items

    return {"message": "送出成功"}


@app.get("/api/state")
def get_state() -> dict[str, Any]:
    with state.lock:
        flat_dishes = [item.dish for items in state.orders.values() for item in items if item.dish]
        duplicate_names = {dish for dish, count in Counter(flat_dishes).items() if count > 1}

        all_orders = {
            name: [
                {"dish": item.dish, "price": item.price, "duplicate": item.dish in duplicate_names}
                for item in items
            ]
            for name, items in state.orders.items()
        }

        return {
            "menu": state.menu.model_dump(),
            "users": sorted(state.users),
            "orders": all_orders,
            "duplicateDishes": sorted(duplicate_names),
        }
