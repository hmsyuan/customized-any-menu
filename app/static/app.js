let currentUser = "";
let lastMenuKey = "";
let imageDraftItems = [];

function applyThemeColor(hex) {
  document.documentElement.style.setProperty("--user-bg", hex);
}

function applyCardColor(hex) {
  document.documentElement.style.setProperty("--user-card-bg", hex);
}

function initThemeColor() {
  const themePicker = document.getElementById("theme-color");
  const cardPicker = document.getElementById("card-color");

  const savedTheme = localStorage.getItem("menu-theme-color") || "#0b1020";
  const savedCard = localStorage.getItem("menu-card-color") || "#111827";

  themePicker.value = savedTheme;
  cardPicker.value = savedCard;
  applyThemeColor(savedTheme);
  applyCardColor(savedCard);

  themePicker.addEventListener("input", () => {
    localStorage.setItem("menu-theme-color", themePicker.value);
    applyThemeColor(themePicker.value);
  });

  cardPicker.addEventListener("input", () => {
    localStorage.setItem("menu-card-color", cardPicker.value);
    applyCardColor(cardPicker.value);
  });
}

async function postForm(url, formData) {
  const res = await fetch(url, { method: "POST", body: formData });
  if (!res.ok) {
    const data = await res.json().catch(() => ({ detail: "請求失敗" }));
    throw new Error(data.detail || "請求失敗");
  }
  return res.json();
}

async function postJson(url, payload) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({ detail: "請求失敗" }));
    throw new Error(data.detail || "請求失敗");
  }
  return res.json();
}

function getMenuKey(menu) {
  if (!menu) return "";
  if (menu.type === "image") return `image:${menu.image_path || ""}`;
  return `json:${menu.title || ""}:${JSON.stringify(menu.categories || [])}`;
}

function renderHostPanel(state) {
  const hostPanel = document.getElementById("host-panel");
  const host = state.host;
  const remaining = state.sessionRemainingSeconds || 0;
  const minutes = Math.floor(remaining / 60);
  const seconds = remaining % 60;

  const isHost = currentUser && host && currentUser === host;
  const canUpload = currentUser && (!host || isHost);

  document.getElementById("json-file").disabled = !canUpload;
  document.getElementById("image-file").disabled = !canUpload;
  document.getElementById("json-submit-btn").disabled = !canUpload;
  document.getElementById("image-submit-btn").disabled = !canUpload;

  const hostText = host ? `目前主持人：${host}` : "目前尚無主持人，第一位上傳菜單者會成為主持人";
  const tip = canUpload ? "你可上傳/修正菜單" : "你目前不能調整菜單（僅主持人可操作）";

  hostPanel.innerHTML = `
    <div class="host-badge">${hostText}</div>
    <small>Session 剩餘時間：約 ${minutes} 分 ${seconds} 秒（到時自動清空）</small>
    <p>${tip}</p>
    ${isHost ? '<button id="release-host-btn" type="button" class="danger-btn">放棄主持權</button>' : ""}
  `;

  document.getElementById("release-host-btn")?.addEventListener("click", async () => {
    try {
      await postJson("/api/host/release", { name: currentUser });
      await refreshState();
      alert("已放棄主持權");
    } catch (err) {
      alert(err.message);
    }
  });
}

async function refreshState() {
  const res = await fetch("/api/state");
  const state = await res.json();

  renderHostPanel(state);

  const menuKey = getMenuKey(state.menu);
  if (menuKey !== lastMenuKey) {
    renderMenu(state.menu);
    lastMenuKey = menuKey;
  }

  renderSummary(state);
  renderAggregateSummary(state.aggregatedOrders || [], state.aggregatedGrandTotal || 0);
}

function renderMenu(menu) {
  const wrap = document.getElementById("menu-view");

  if (menu.type === "image") {
    imageDraftItems = [];
    wrap.innerHTML = `
      <p><strong>${menu.title}</strong></p>
      <img src="${menu.image_path}" alt="菜單圖片" style="max-width:100%;border-radius:12px" />
      <form id="text-order-form" class="inline-form" style="margin-top:10px">
        <input id="dish-name" placeholder="菜名，例如：三杯雞" required />
        <input id="dish-price" type="number" min="0" placeholder="價格" />
        <input id="dish-quantity" type="number" min="1" value="1" placeholder="數量" />
        <button type="submit">新增到我的清單</button>
      </form>
      <ul id="my-items"></ul>
      <button id="submit-my-order">送出我的點餐</button>
    `;
    attachTextOrderHandlers();
    return;
  }

  const categoriesHtml = (menu.categories || [])
    .map((category, i) => {
      const itemsHtml = (category.items || [])
        .map(
          (item, j) => `
          <label class="dish-option">
            <input type="checkbox" data-dish="${item.name}" data-price="${Number(item.price) || 0}" id="item-${i}-${j}" />
            <span>${item.name}</span>
            <strong>$${Number(item.price) || 0}</strong>
            <input type="number" min="1" value="1" class="qty-input" id="qty-${i}-${j}" />
          </label>`
        )
        .join("");
      return `<div class="category"><h3>${category.name}</h3><div class="dish-grid">${itemsHtml}</div></div>`;
    })
    .join("");

  wrap.innerHTML = `
    <p><strong>${menu.title}</strong></p>
    <form id="json-order-form">
      <div class="category-layout">${categoriesHtml || "<small>目前沒有菜色</small>"}</div>
      <button type="submit">送出我的點餐</button>
    </form>
  `;

  const form = document.getElementById("json-order-form");
  form?.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!currentUser) {
      alert("請先取名");
      return;
    }
    const checked = [...form.querySelectorAll("input[type='checkbox']:checked")];
    const items = checked.map((el) => {
      const qtyInput = document.getElementById(el.id.replace("item-", "qty-"));
      return {
        dish: el.dataset.dish,
        price: Number(el.dataset.price) || 0,
        quantity: Math.max(1, Number(qtyInput?.value || 1)),
      };
    });

    try {
      await postJson("/api/order", { name: currentUser, items });
      await refreshState();
      alert("送出成功");
    } catch (err) {
      alert(err.message);
    }
  });
}

function renderImageDraftList() {
  const listEl = document.getElementById("my-items");
  if (!listEl) return;
  listEl.innerHTML = imageDraftItems
    .map((it) => `<li>${it.dish}（$${it.price}）x ${it.quantity}，小計 $${it.price * it.quantity}</li>`)
    .join("");
}

function attachTextOrderHandlers() {
  document.getElementById("text-order-form")?.addEventListener("submit", (e) => {
    e.preventDefault();
    const dishInput = document.getElementById("dish-name");
    const priceInput = document.getElementById("dish-price");
    const qtyInput = document.getElementById("dish-quantity");
    const dish = dishInput.value.trim();
    const price = Math.max(0, Number(priceInput.value || 0));
    const quantity = Math.max(1, Number(qtyInput.value || 1));
    if (!dish) return;

    imageDraftItems.push({ dish, price, quantity });
    renderImageDraftList();
    dishInput.value = "";
    priceInput.value = "";
    qtyInput.value = "1";
    dishInput.focus();
  });

  document.getElementById("submit-my-order")?.addEventListener("click", async () => {
    if (!currentUser) {
      alert("請先取名");
      return;
    }
    try {
      await postJson("/api/order", { name: currentUser, items: imageDraftItems });
      await refreshState();
      alert("送出成功");
    } catch (err) {
      alert(err.message);
    }
  });
}

function renderSummary(state) {
  const summary = document.getElementById("summary");
  const users = state.users || [];
  const orders = state.orders || {};
  const duplicateSet = new Set(state.duplicateDishes || []);

  if (!users.length) {
    summary.innerHTML = "<small>尚未有人加入</small>";
    return;
  }

  summary.innerHTML = `<div class="summary-grid">${users
    .map((name) => {
      const items = orders[name] || [];
      const itemsHtml = items.length
        ? items
            .map((it) => {
              const cls = duplicateSet.has(it.dish) ? "duplicate" : "";
              return `<li><span class="${cls}">${it.dish}</span>（$${it.price}）x ${it.quantity}，小計 $${it.lineTotal}</li>`;
            })
            .join("")
        : "<li><small>尚未點餐</small></li>";
      return `<article class="summary-card"><h3>${name}</h3><ul>${itemsHtml}</ul></article>`;
    })
    .join("")}</div>`;
}

function renderAggregateSummary(items, grandTotal) {
  const wrap = document.getElementById("aggregate-summary");
  if (!items.length) {
    wrap.innerHTML = "<small>尚無彙整結果</small>";
    return;
  }

  wrap.innerHTML = `<div class="summary-grid">${items
    .map(
      (it) => `<article class="summary-card"><h3>${it.dish}</h3><ul>
      <li>單價：$${it.price}</li>
      <li>份數：${it.quantity}</li>
      <li><strong>總價：$${it.totalPrice}</strong></li>
      </ul></article>`
    )
    .join("")}</div><div class="aggregate-grand-total">全部菜色總價格：$${grandTotal}</div>`;
}

document.getElementById("join-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = document.getElementById("name").value;
  const formData = new FormData();
  formData.append("name", name);
  try {
    const data = await postForm("/api/join", formData);
    currentUser = data.name;
    document.getElementById("whoami").textContent = `目前身份：${currentUser}`;
    await refreshState();
  } catch (err) {
    alert(err.message);
  }
});

document.getElementById("json-menu-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!currentUser) {
    alert("請先取名");
    return;
  }
  const file = document.getElementById("json-file").files[0];
  if (!file) return;
  const fd = new FormData();
  fd.append("name", currentUser);
  fd.append("file", file);
  try {
    await postForm("/api/menu/json", fd);
    await refreshState();
  } catch (err) {
    alert(err.message);
  }
});

document.getElementById("image-menu-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!currentUser) {
    alert("請先取名");
    return;
  }
  const file = document.getElementById("image-file").files[0];
  if (!file) return;
  const fd = new FormData();
  fd.append("name", currentUser);
  fd.append("file", file);
  try {
    await postForm("/api/menu/image", fd);
    await refreshState();
  } catch (err) {
    alert(err.message);
  }
});

initThemeColor();
refreshState();
setInterval(refreshState, 2000);
