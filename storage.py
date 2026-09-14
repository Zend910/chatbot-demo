"""Lưu trữ dữ liệu notebook bằng Firebase Firestore.

Khác với bản cũ (lưu vào data/notebooks.json trên đĩa cục bộ — bị xóa mỗi khi
Render khởi động lại service), toàn bộ users / notebooks / tài liệu / lịch sử
chat / sản phẩm Studio giờ nằm trên Firestore nên KHÔNG mất khi service restart
hoặc redeploy.

Cấu trúc Firestore:
  users/{user_id}
  notebooks/{notebook_id}
  notebooks/{notebook_id}/documents/{document_id}
  notebooks/{notebook_id}/chat_history/{seq}
  notebooks/{notebook_id}/studio_items/{item_id}

Toàn bộ tên hàm và tham số giữ nguyên như bản cũ để app.py không cần sửa gì
thêm ngoài việc xóa/đổi tên file storage.py cũ.
"""
import os
import secrets
import uuid
from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

from firebase_init import get_db


def _db():
    return get_db()


def _now():
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def _user_public(user):
    return {
        "id": user["id"],
        "username": user["username"],
        "email": user.get("email", ""),
        "role": user.get("role", "user"),
        "created_at": user.get("created_at"),
    }


def get_user_by_id(user_id):
    if not user_id:
        return None
    doc = _db().collection("users").document(user_id).get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    data["id"] = doc.id
    return data


def get_user_by_username(username):
    username = (username or "").strip()
    if not username:
        return None
    key = username.lower()
    for doc in _db().collection("users").stream():
        data = doc.to_dict()
        if (data.get("username") or "").lower() == key:
            data["id"] = doc.id
            return data
    return None


def get_user_by_email(email):
    email = (email or "").strip().lower()
    if not email:
        return None
    query = _db().collection("users").where("email", "==", email).limit(1)
    for doc in query.stream():
        data = doc.to_dict()
        data["id"] = doc.id
        return data
    return None


def register_user(username, password, role="user", email=None):
    username = (username or "").strip()
    password = password or ""
    role = (role or "user").strip().lower()
    if role not in {"user", "admin"}:
        raise ValueError("Role phải là user hoặc admin.")
    if len(username) < 3:
        raise ValueError("Tên đăng nhập phải có ít nhất 3 ký tự.")
    if len(password) < 6:
        raise ValueError("Mật khẩu phải có ít nhất 6 ký tự.")
    if get_user_by_username(username):
        raise ValueError("Tên đăng nhập này đã tồn tại.")

    user_id = uuid.uuid4().hex[:10]
    user = {
        "id": user_id,
        "username": username,
        "email": (email or "").strip().lower(),
        "role": role,
        "password_hash": generate_password_hash(password),
        "created_at": _now(),
    }
    _db().collection("users").document(user_id).set(user)
    return _user_public(user)


def ensure_default_admin():
    """Tạo tài khoản admin mặc định CHỈ MỘT LẦN nếu chưa có ai trong hệ thống.

    QUAN TRỌNG: hàm này KHÔNG được ghi đè mật khẩu của tài khoản admin đã tồn
    tại — bản cũ làm vậy nên mỗi lần Render khởi động lại / redeploy, mật khẩu
    admin bị reset về "admin123" mặc định, biến nó thành một backdoor công
    khai. Mật khẩu khởi tạo lấy từ biến môi trường ADMIN_INITIAL_PASSWORD nếu
    có, để bạn không phải nhớ đổi ngay sau khi deploy lần đầu.
    """
    existing = get_user_by_username("admin")
    if existing:
        if existing.get("role") != "admin":
            _db().collection("users").document(existing["id"]).update({"role": "admin"})
        return _user_public(existing)

    initial_password = os.environ.get("ADMIN_INITIAL_PASSWORD") or secrets.token_urlsafe(12)
    admin = register_user("admin", initial_password, role="admin")
    if not os.environ.get("ADMIN_INITIAL_PASSWORD"):
        print(
            "\n[SETUP] Đã tạo tài khoản admin mặc định.\n"
            f"        Username: admin\n"
            f"        Password: {initial_password}\n"
            "        Hãy đăng nhập và đổi mật khẩu này ngay, hoặc đặt biến môi trường\n"
            "        ADMIN_INITIAL_PASSWORD trước lần deploy đầu tiên để tự chọn mật khẩu.\n"
        )
    return admin


def list_users():
    result = []
    for doc in _db().collection("users").stream():
        data = doc.to_dict()
        data["id"] = doc.id
        result.append(_user_public(data))
    return result


def update_user(user_id, username=None, password=None, role=None):
    ref = _db().collection("users").document(user_id)
    doc = ref.get()
    if not doc.exists:
        raise KeyError(f"Không tìm thấy người dùng {user_id}")
    user = doc.to_dict()
    user["id"] = user_id

    new_username = (username or user["username"]).strip()
    new_role = (role or user.get("role", "user")).strip().lower()
    if new_role not in {"user", "admin"}:
        raise ValueError("Role phải là user hoặc admin.")
    if len(new_username) < 3:
        raise ValueError("Tên đăng nhập phải có ít nhất 3 ký tự.")
    if username is not None:
        existing = get_user_by_username(new_username)
        if existing and existing["id"] != user_id:
            raise ValueError("Tên đăng nhập này đã tồn tại.")

    updates = {"username": new_username, "role": new_role}
    if password is not None:
        password = password or ""
        if len(password) < 6:
            raise ValueError("Mật khẩu phải có ít nhất 6 ký tự.")
        updates["password_hash"] = generate_password_hash(password)

    ref.update(updates)
    user.update(updates)
    return _user_public(user)


def delete_user(user_id):
    ref = _db().collection("users").document(user_id)
    if not ref.get().exists:
        return
    ref.delete()
    for doc in _db().collection("notebooks").where("user_id", "==", user_id).stream():
        doc.reference.update({"user_id": None})


def verify_user(username, password):
    user = get_user_by_username(username)
    if not user:
        return False
    return check_password_hash(user.get("password_hash", ""), password)


def get_custom_instructions(user_id):
    if not user_id:
        return ""
    user = get_user_by_id(user_id)
    if not user:
        return ""
    return user.get("custom_instructions", "")


def set_custom_instructions(user_id, text):
    ref = _db().collection("users").document(user_id)
    if not ref.get().exists:
        raise KeyError(f"Không tìm thấy người dùng {user_id}")
    value = str(text or "").strip()
    ref.update({"custom_instructions": value})
    return value


def _today_str():
    return datetime.now().strftime("%Y-%m-%d")


def get_usage_stats(user_id):
    if not user_id:
        return {"date": _today_str(), "tokens": 0, "calls": 0}
    user = get_user_by_id(user_id)
    if not user:
        return {"date": _today_str(), "tokens": 0, "calls": 0}
    stats = user.get("usage_stats") or {}
    today = _today_str()
    if stats.get("date") != today:
        return {"date": today, "tokens": 0, "calls": 0}
    return {
        "date": today,
        "tokens": int(stats.get("tokens") or 0),
        "calls": int(stats.get("calls") or 0),
    }


def record_usage(user_id, tokens=0):
    if not user_id:
        return {"date": _today_str(), "tokens": 0, "calls": 0}
    ref = _db().collection("users").document(user_id)
    doc = ref.get()
    if not doc.exists:
        return {"date": _today_str(), "tokens": 0, "calls": 0}
    user = doc.to_dict()
    today = _today_str()
    stats = user.get("usage_stats") or {}
    if stats.get("date") != today:
        stats = {"date": today, "tokens": 0, "calls": 0}
    stats["tokens"] = int(stats.get("tokens") or 0) + max(0, int(tokens or 0))
    stats["calls"] = int(stats.get("calls") or 0) + 1
    ref.update({"usage_stats": stats})
    return stats


# ---------------------------------------------------------------------------
# Notebooks
# ---------------------------------------------------------------------------

def _notebook_summary(nb, owner=None, doc_count=0):
    summary = {
        "id": nb["id"],
        "name": nb["name"],
        "created_at": nb["created_at"],
        "doc_count": doc_count,
        "user_id": nb.get("user_id"),
    }
    if owner is not None:
        summary["owner_username"] = owner.get("username")
        summary["owner_role"] = owner.get("role", "user")
    return summary


def _doc_count(nb_ref):
    try:
        agg = nb_ref.collection("documents").count().get()
        return agg[0][0].value
    except Exception:
        return len(list(nb_ref.collection("documents").stream()))


def _check_access(nb, user_id, role):
    is_admin = role == "admin"
    if user_id is not None and nb.get("user_id") != user_id and not is_admin:
        raise PermissionError("Bạn không có quyền truy cập notebook này.")


def list_notebooks(user_id=None, role=None):
    query = _db().collection("notebooks")
    if user_id is not None and role != "admin":
        query = query.where("user_id", "==", user_id)
    result = []
    for doc in query.stream():
        nb = doc.to_dict()
        nb["id"] = doc.id
        owner = get_user_by_id(nb.get("user_id")) if nb.get("user_id") else None
        result.append(_notebook_summary(nb, owner=owner, doc_count=_doc_count(doc.reference)))
    return result


def list_notebooks_for_user(user_id, role=None):
    return list_notebooks(user_id=user_id, role=role)


def list_all_notebooks_with_users():
    result = []
    for doc in _db().collection("notebooks").stream():
        nb = doc.to_dict()
        nb["id"] = doc.id
        owner = get_user_by_id(nb.get("user_id")) if nb.get("user_id") else None
        result.append(_notebook_summary(nb, owner=owner, doc_count=_doc_count(doc.reference)))
    return result


def create_notebook(name, user_id=None):
    nb_id = uuid.uuid4().hex[:10]
    nb = {
        "id": nb_id,
        "name": name or "Notebook chưa đặt tên",
        "created_at": _now(),
        "user_id": user_id,
    }
    _db().collection("notebooks").document(nb_id).set(nb)
    nb["documents"] = []
    nb["chat_history"] = []
    nb["studio_items"] = []
    return nb


def get_notebook(nb_id, user_id=None, role=None):
    ref = _db().collection("notebooks").document(nb_id)
    doc = ref.get()
    if not doc.exists:
        raise KeyError(f"Không tìm thấy notebook {nb_id}")
    nb = doc.to_dict()
    nb["id"] = nb_id
    _check_access(nb, user_id, role)

    nb["documents"] = [{**d.to_dict(), "id": d.id} for d in ref.collection("documents").stream()]
    nb["chat_history"] = [
        d.to_dict() for d in ref.collection("chat_history").order_by("seq").stream()
    ]
    studio_items = []
    for d in ref.collection("studio_items").order_by("created_at", direction="DESCENDING").stream():
        item = d.to_dict()
        item["id"] = d.id
        studio_items.append(item)
    nb["studio_items"] = studio_items
    return nb


def add_studio_item(nb_id, item, user_id=None, role=None):
    ref = _db().collection("notebooks").document(nb_id)
    doc = ref.get()
    if not doc.exists:
        raise KeyError(f"Không tìm thấy notebook {nb_id}")
    nb = doc.to_dict()
    nb["id"] = nb_id
    _check_access(nb, user_id, role)

    item = dict(item)
    item_id = item.pop("id", None) or uuid.uuid4().hex[:10]
    item.setdefault("created_at", _now())
    ref.collection("studio_items").document(item_id).set(item)
    item["id"] = item_id
    return item


def delete_studio_item(nb_id, item_id, user_id=None, role=None):
    ref = _db().collection("notebooks").document(nb_id)
    doc = ref.get()
    if not doc.exists:
        raise KeyError(f"Không tìm thấy notebook {nb_id}")
    nb = doc.to_dict()
    nb["id"] = nb_id
    _check_access(nb, user_id, role)

    item_ref = ref.collection("studio_items").document(item_id)
    if not item_ref.get().exists:
        raise KeyError("Không tìm thấy sản phẩm Studio.")
    item_ref.delete()


def delete_notebook(nb_id, user_id=None, role=None):
    ref = _db().collection("notebooks").document(nb_id)
    doc = ref.get()
    if not doc.exists:
        return
    nb = doc.to_dict()
    nb["id"] = nb_id
    _check_access(nb, user_id, role)

    for sub in ("documents", "chat_history", "studio_items"):
        for d in ref.collection(sub).stream():
            d.reference.delete()
    ref.delete()


def clear_chat_history(nb_id, user_id=None, role=None):
    ref = _db().collection("notebooks").document(nb_id)
    doc = ref.get()
    if not doc.exists:
        raise KeyError(f"Không tìm thấy notebook {nb_id}")
    nb = doc.to_dict()
    nb["id"] = nb_id
    _check_access(nb, user_id, role)

    for d in ref.collection("chat_history").stream():
        d.reference.delete()


def add_document(nb_id, document, user_id=None, role=None):
    return upsert_document(nb_id, document, user_id=user_id, role=role)


def upsert_document(nb_id, document, user_id=None, role=None):
    ref = _db().collection("notebooks").document(nb_id)
    doc = ref.get()
    if not doc.exists:
        raise KeyError(f"Không tìm thấy notebook {nb_id}")
    nb = doc.to_dict()
    nb["id"] = nb_id
    _check_access(nb, user_id, role)

    document = dict(document)
    doc_id = document.get("id") or uuid.uuid4().hex[:10]
    document["id"] = doc_id
    ref.collection("documents").document(doc_id).set(document)
    return document


def remove_document(nb_id, doc_id, user_id=None, role=None):
    ref = _db().collection("notebooks").document(nb_id)
    doc = ref.get()
    if not doc.exists:
        raise KeyError(f"Không tìm thấy notebook {nb_id}")
    nb = doc.to_dict()
    nb["id"] = nb_id
    _check_access(nb, user_id, role)
    ref.collection("documents").document(doc_id).delete()


def append_chat(nb_id, role, content, citations=None, user_id=None, nb_role=None):
    ref = _db().collection("notebooks").document(nb_id)
    doc = ref.get()
    if not doc.exists:
        raise KeyError(f"Không tìm thấy notebook {nb_id}")
    nb = doc.to_dict()
    nb["id"] = nb_id
    _check_access(nb, user_id, nb_role)

    last = list(
        ref.collection("chat_history").order_by("seq", direction="DESCENDING").limit(1).stream()
    )
    next_seq = (last[0].to_dict().get("seq", 0) + 1) if last else 1
    ref.collection("chat_history").document(f"{next_seq:08d}").set({
        "role": role,
        "content": content,
        "citations": citations or [],
        "ts": _now(),
        "seq": next_seq,
    })


def all_chunks(nb_id, user_id=None, role=None):
    nb = get_notebook(nb_id, user_id=user_id, role=role)
    chunks = []
    for doc in nb["documents"]:
        for c in doc.get("chunks", []):
            chunks.append({
                "chunk_id": c["id"],
                "text": c["text"],
                "position": c.get("position", ""),
                "doc_id": doc["id"],
                "doc_name": doc["name"],
            })
    return chunks


# ---------------------------------------------------------------------------
# Tương thích ngược: 2 route admin trong app.py đọc thẳng toàn bộ CSDL
# (admin_list_users, admin_list_documents). Hàm này chỉ nên dùng cho các
# route quản trị ít gọi — KHÔNG dùng trong luồng chat vì tốn nhiều lượt đọc.
# ---------------------------------------------------------------------------

def _load():
    users = {}
    for doc in _db().collection("users").stream():
        data = doc.to_dict()
        data["id"] = doc.id
        users[doc.id] = data

    notebooks = {}
    for doc in _db().collection("notebooks").stream():
        nb = doc.to_dict()
        nb["id"] = doc.id
        nb["documents"] = [
            {**d.to_dict(), "id": d.id} for d in doc.reference.collection("documents").stream()
        ]
        notebooks[doc.id] = nb
    return {"users": users, "notebooks": notebooks}


UPLOAD_DIR = os.path.join(os.getcwd(), 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)

AUDIO_DIR = os.path.join(os.getcwd(), 'data', 'audio')
os.makedirs(AUDIO_DIR, exist_ok=True)