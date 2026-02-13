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

    categories = payload.get("categories", [])
    if not isinstance(categories, list):
        raise HTTPException(status_code=400, detail="categories 必須是陣列")

    with state.lock:
        state.menu = MenuState(
            type="json",
            title=payload.get("title", "未命名菜單"),
            categories=categories,
            image_path=None,
        )
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
