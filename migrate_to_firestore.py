"""Chạy MỘT LẦN để đưa dữ liệu cũ trong data/notebooks.json (users, notebooks,
tài liệu, lịch sử chat, sản phẩm Studio) lên Firestore.

Cách chạy (ở máy local, đã cài đặt requirements.txt và cấu hình .env với
FIREBASE_SERVICE_ACCOUNT_JSON trỏ tới file service-account):

    python migrate_to_firestore.py

Script này an toàn khi chạy lại nhiều lần (ghi đè theo id, không tạo trùng).
KHÔNG cần chạy trên Render — chỉ chạy 1 lần ở máy bạn để đẩy dữ liệu cũ lên,
sau đó Render sẽ tự đọc/ghi thẳng vào Firestore qua storage.py mới.
"""
import json
import os

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from firebase_init import get_db

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "notebooks.json")


def main():
    if not os.path.exists(DATA_PATH):
        print(f"Không tìm thấy {DATA_PATH} — không có gì để di chuyển.")
        return

    with open(DATA_PATH, "r", encoding="utf-8") as f:
        old = json.load(f)

    db = get_db()

    users = old.get("users", {})
    print(f"Đang chuyển {len(users)} user(s)...")
    for user_id, user in users.items():
        user = dict(user)
        user["id"] = user_id
        db.collection("users").document(user_id).set(user)
    print("  Xong users.")

    notebooks = old.get("notebooks", {})
    print(f"Đang chuyển {len(notebooks)} notebook(s)...")
    for nb_id, nb in notebooks.items():
        nb_ref = db.collection("notebooks").document(nb_id)
        nb_ref.set({
            "id": nb_id,
            "name": nb.get("name", "Notebook chưa đặt tên"),
            "created_at": nb.get("created_at"),
            "user_id": nb.get("user_id"),
        })

        for doc in nb.get("documents", []):
            doc = dict(doc)
            doc_id = doc.get("id")
            if not doc_id:
                continue
            nb_ref.collection("documents").document(doc_id).set(doc)

        for i, msg in enumerate(nb.get("chat_history", []), start=1):
            msg = dict(msg)
            msg["seq"] = i
            nb_ref.collection("chat_history").document(f"{i:08d}").set(msg)

        for item in nb.get("studio_items", []):
            item = dict(item)
            item_id = item.pop("id", None)
            if not item_id:
                continue
            nb_ref.collection("studio_items").document(item_id).set(item)

        print(f"  Xong notebook {nb_id} ({nb.get('name')}).")

    print("Hoàn tất di chuyển dữ liệu lên Firestore.")


if __name__ == "__main__":
    main()