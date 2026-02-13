# 多人線上點餐系統（最多 10 人）

這是一個可部署到 **Google Cloud Run** 的簡易多人點餐系統範例，支援：

- 匯入 **JSON 菜單**（自動產生可勾選表單）
- 匯入 **圖檔菜單**（改為文字輸入菜名）
- 每位使用者先取名再點餐
- 即時查看所有人已點品項與價格
- 重複菜色醒目標示

## 快速啟動

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

開啟：`http://127.0.0.1:8000`

## JSON 菜單格式

```json
{
  "title": "今晚聚餐",
  "categories": [
    {
      "name": "熱炒類",
      "items": [
        {"name": "宮保雞丁", "price": 220},
        {"name": "蔥爆牛肉", "price": 240}
      ]
    }
  ]
}
```

## Cloud Run 部署（範例）

```bash
gcloud builds submit --tag gcr.io/$PROJECT_ID/customized-any-menu

gcloud run deploy customized-any-menu \
  --image gcr.io/$PROJECT_ID/customized-any-menu \
  --platform managed \
  --allow-unauthenticated \
  --region asia-east1
```

> 注意：此版本資料儲存在記憶體中，重啟後會清空。若要正式上線，建議把資料改存 Firestore 或 Cloud SQL。
