"""Khởi tạo Firebase Admin SDK dùng chung cho toàn bộ app (Auth + Firestore).

Đọc credentials từ biến môi trường FIREBASE_SERVICE_ACCOUNT_JSON, có thể là:
  - Nội dung JSON đầy đủ của file service-account (khuyên dùng khi deploy lên Render,
    dán thẳng nội dung file vào Environment Variable, không cần upload file).
  - Hoặc đường dẫn tới file JSON đó trên máy (dùng khi chạy local).
"""
import json
import os

import firebase_admin
from firebase_admin import credentials, firestore

_db = None


def _credentials_value():
    value = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
    if not value:
        raise RuntimeError(
            "Thiếu biến môi trường FIREBASE_SERVICE_ACCOUNT_JSON. "
            "Hãy đặt nó bằng nội dung JSON của Firebase service account "
            "(Project settings > Service accounts > Generate new private key), "
            "hoặc đường dẫn tới file JSON đó nếu chạy ở máy local."
        )
    if value.startswith("{"):
        return json.loads(value)
    return os.path.abspath(os.path.expandvars(os.path.expanduser(value)))


def init_firebase():
    """Khởi tạo Firebase Admin app một lần duy nhất (an toàn khi gọi nhiều lần)."""
    if not firebase_admin._apps:
        cred = credentials.Certificate(_credentials_value())
        firebase_admin.initialize_app(cred)
    return firebase_admin.get_app()


def get_db():
    """Trả về Firestore client dùng chung (singleton)."""
    global _db
    if _db is None:
        init_firebase()
        _db = firestore.client()
    return _db
