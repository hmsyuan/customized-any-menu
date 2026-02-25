from __future__ import annotations

import json
import time
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
SESSION_TTL_SECONDS = 60 * 60


class OrderItem(BaseModel):
    dish: str
    size: str = "中"
    price: int = Field(ge=0, default=0)
    quantity: int = Field(ge=1, default=1)


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
        self.host: str | None = None
        self.session_started_at = time.time()

    def reset_orders(self) -> None:
        self.orders = {name: [] for name in self.users}

    def reset_all(self) -> None:
        self.menu = MenuState()
        self.users.clear()
        self.orders.clear()
        self.host = None
        self.session_started_at = time.time()

    def expire_if_needed(self) -> None:
        if time.time() - self.session_started_at >= SESSION_TTL_SECONDS:
            self.reset_all()

    def assert_host_can_manage_menu(self, user_name: str) -> None:
        if self.host is not None and self.host != user_name:
            raise HTTPException(status_code=403, detail=f"目前主持人是 {self.host}，只有主持人可調整菜單")


class SubmitOrderPayload(BaseModel):
    name: str
    items: list[OrderItem]


class ReleaseHostPayload(BaseModel):
    name: str


class DeleteSubmittedItemPayload(BaseModel):
    actor: str
    target_user: str
    item_index: int = Field(ge=0)


def normalize_menu_payload(payload: Any) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON 根節點必須是物件")

    if isinstance(payload.get("categories"), list):
        categories_raw = payload["categories"]
        title = str(payload.get("title") or "未命名菜單")
    else:
        categories_raw = [{"name": key, "items": value} for key, value in payload.items() if isinstance(value, list)]
        title = "未命名菜單"

    def parse_size_prices(raw_price: Any) -> list[dict[str, Any]]:
        size_aliases = {
            "小": "小",
            "small": "小",
            "s": "小",
            "中": "中",
            "medium": "中",
            "m": "中",
            "大": "大",
            "large": "大",
            "l": "大",
        }
        if isinstance(raw_price, dict):
            parsed: dict[str, int] = {}
            for key, value in raw_price.items():
                size_key = size_aliases.get(str(key).strip().lower(), str(key).strip())
                try:
                    parsed[size_key] = max(0, int(value))
                except (TypeError, ValueError):
                    continue

            if not parsed:
                return [{"size": "中", "price": 0}]

            size_order = {"小": 0, "中": 1, "大": 2}
            return [
                {"size": size, "price": price}
                for size, price in sorted(parsed.items(), key=lambda pair: (size_order.get(pair[0], 999), pair[0]))
            ]

        try:
            single_price = max(0, int(raw_price))
        except (TypeError, ValueError):
            single_price = 0
        return [{"size": "中", "price": single_price}]

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
            size_options = parse_size_prices(raw_price)
            default_option = next((opt for opt in size_options if opt["size"] == "中"), size_options[0])
            normalized_items.append(
                {
                    "name": dish_name,
                    "price": default_option["price"],
                    "sizeOptions": size_options,
                    "hasSizeOptions": isinstance(raw_price, dict),
                }
            )

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
        state.expire_if_needed()
        if clean not in state.users and len(state.users) >= 10:
            raise HTTPException(status_code=400, detail="目前最多 10 位使用者")
        state.users.add(clean)
        state.orders.setdefault(clean, [])

    return {"name": clean}


@app.post("/api/menu/json")
async def import_menu_json(name: str = Form(...), file: UploadFile = File(...)) -> dict[str, str]:
    try:
        raw = await file.read()
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="JSON 格式錯誤") from exc

    title, categories = normalize_menu_payload(payload)

    with state.lock:
        state.expire_if_needed()
        if name not in state.users:
            raise HTTPException(status_code=400, detail="請先加入並命名")
        state.assert_host_can_manage_menu(name)

        if state.host is None:
            state.host = name

        existing_image_path = state.menu.image_path
        state.menu = MenuState(type="json", title=title, categories=categories, image_path=existing_image_path)
        state.reset_orders()

    return {"message": "JSON 菜單已匯入"}


@app.post("/api/menu/image")
async def import_menu_image(name: str = Form(...), file: UploadFile = File(...)) -> dict[str, str]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(status_code=400, detail="僅支援 png/jpg/jpeg/webp")

    filename = f"{uuid.uuid4().hex}{suffix}"
    save_path = UPLOAD_DIR / filename
    content = await file.read()
    save_path.write_bytes(content)

    with state.lock:
        state.expire_if_needed()
        if name not in state.users:
            raise HTTPException(status_code=400, detail="請先加入並命名")
        state.assert_host_can_manage_menu(name)

        if state.host is None:
            state.host = name

        image_path = f"/uploads/{filename}"
        if state.menu.categories:
            state.menu.image_path = image_path
        else:
            state.menu = MenuState(type="image", title="圖片菜單", categories=[], image_path=image_path)
            state.reset_orders()

    return {"message": "圖片菜單已匯入"}


@app.post("/api/host/release")
def release_host(payload: ReleaseHostPayload) -> dict[str, str]:
    with state.lock:
        state.expire_if_needed()
        if state.host is None:
            raise HTTPException(status_code=400, detail="目前沒有主持人")
        if payload.name != state.host:
            raise HTTPException(status_code=403, detail="只有主持人可以放棄主持權")

        state.host = None

    return {"message": "已放棄主持權，其他人可重新上傳菜單"}


@app.post("/api/order")
def submit_order(payload: SubmitOrderPayload) -> dict[str, str]:
    with state.lock:
        state.expire_if_needed()
        if payload.name not in state.users:
            raise HTTPException(status_code=400, detail="請先加入並命名")
        state.orders[payload.name] = payload.items

    return {"message": "送出成功"}


@app.post("/api/order/delete-submitted-item")
def delete_submitted_item(payload: DeleteSubmittedItemPayload) -> dict[str, str]:
    with state.lock:
        state.expire_if_needed()
        is_host = payload.actor == state.host
        is_self = payload.actor == payload.target_user
        if not (is_host or is_self):
            raise HTTPException(status_code=403, detail="僅主持人可刪除所有人，或本人刪除自己的項目")
        if payload.target_user not in state.orders:
            raise HTTPException(status_code=404, detail="找不到目標使用者")

        target_items = state.orders[payload.target_user]
        if payload.item_index >= len(target_items):
            raise HTTPException(status_code=400, detail="刪除索引超出範圍")

        del target_items[payload.item_index]

    return {"message": "已刪除送出項目"}


@app.get("/api/state")
def get_state() -> dict[str, Any]:
    with state.lock:
        state.expire_if_needed()

        flat_dishes = [item.dish for items in state.orders.values() for item in items if item.dish]
        duplicate_names = {dish for dish, count in Counter(flat_dishes).items() if count > 1}

        all_orders = {
            name: [
                {
                    "dish": item.dish,
                    "size": item.size,
                    "price": item.price,
                    "quantity": item.quantity,
                    "lineTotal": item.price * item.quantity,
                    "duplicate": item.dish in duplicate_names,
                }
                for item in items
            ]
            for name, items in state.orders.items()
        }

        dish_to_category: dict[str, str] = {}
        for category in state.menu.categories:
            category_name = str(category.get("name") or "未分類")
            for item in category.get("items", []):
                dish_name = str(item.get("name") or "").strip()
                if dish_name and dish_name not in dish_to_category:
                    dish_to_category[dish_name] = category_name

        aggregate_map: dict[tuple[str, str, str, int], dict[str, Any]] = {}
        for items in state.orders.values():
            for item in items:
                category_name = dish_to_category.get(item.dish, "未分類")
                key = (category_name, item.dish, item.size, item.price)
                if key not in aggregate_map:
                    aggregate_map[key] = {
                        "category": category_name,
                        "dish": item.dish,
                        "size": item.size,
                        "price": item.price,
                        "quantity": 0,
                        "totalPrice": 0,
                    }
                aggregate_map[key]["quantity"] += item.quantity
                aggregate_map[key]["totalPrice"] += item.quantity * item.price

        aggregated_orders = sorted(
            aggregate_map.values(), key=lambda x: (x["category"], x["dish"], x["size"], x["price"])
        )
        aggregated_grand_total = sum(row["totalPrice"] for row in aggregated_orders)

        categorized_aggregates: dict[str, list[dict[str, Any]]] = {}
        for row in aggregated_orders:
            categorized_aggregates.setdefault(row["category"], []).append(row)

        aggregated_by_category = [
            {
                "category": category,
                "items": rows,
                "categoryTotal": sum(item["totalPrice"] for item in rows),
            }
            for category, rows in sorted(categorized_aggregates.items(), key=lambda pair: pair[0])
        ]

        remaining_seconds = max(0, int(SESSION_TTL_SECONDS - (time.time() - state.session_started_at)))

        return {
            "menu": state.menu.model_dump(),
            "users": sorted(state.users),
            "orders": all_orders,
            "aggregatedOrders": aggregated_orders,
            "aggregatedByCategory": aggregated_by_category,
            "aggregatedGrandTotal": aggregated_grand_total,
            "host": state.host,
            "sessionRemainingSeconds": remaining_seconds,
            "duplicateDishes": sorted(duplicate_names),
        }
