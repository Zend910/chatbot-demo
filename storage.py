"""Lưu trữ dữ liệu notebook đơn giản bằng JSON, chạy hoàn toàn local."""
import json
import os
import shutil
import threading
import uuid
from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DB_PATH = os.path.join(DATA_DIR, "notebooks.json")
DB_BACKUP_PATH = DB_PATH + ".bak"
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
AUDIO_DIR = os.path.join(DATA_DIR, "audio")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(AUDIO_DIR, exist_ok=True)

_lock = threading.Lock()


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _read_json_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load():
    if not os.path.exists(DB_PATH):
        db = {"notebooks": {}, "users": {}}
        _save(db)
        return db
    try:
        data = _read_json_file(DB_PATH)
    except (json.JSONDecodeError, OSError, ValueError):
        # notebooks.json chính bị hỏng (thường do tắt cmd/kill tiến trình đúng lúc
        # đang ghi file) -> thử phục hồi từ bản sao lưu thay vì làm mất trắng dữ liệu.
        if os.path.exists(DB_BACKUP_PATH):
            try:
                data = _read_json_file(DB_BACKUP_PATH)
            except (json.JSONDecodeError, OSError, ValueError):
                data = {"notebooks": {}, "users": {}}
        else:
            data = {"notebooks": {}, "users": {}}
    data.setdefault("notebooks", {})
    data.setdefault("users", {})
    return data


def _save(db):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp_path = DB_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, DB_PATH)
    # Giữ thêm một bản sao lưu ngay sau khi ghi thành công, để nếu lần ghi kế
    # tiếp bị cắt ngang giữa chừng (tắt cmd đột ngột) thì vẫn còn bản gần nhất để phục hồi.
    try:
        shutil.copyfile(DB_PATH, DB_BACKUP_PATH)
    except OSError:
        pass


def _user_public(user):
    return {
        "id": user["id"],
        "username": user["username"],
        "email": user.get("email", ""),
        "role": user.get("role", "user"),
        "created_at": user.get("created_at"),
    }


def get_user_by_id(user_id):
    db = _load()
    user = db.get("users", {}).get(user_id)
    if not user:
        return None
    return user


def get_user_by_username(username):
    username = (username or "").strip()
    if not username:
        return None
    key = username.lower()
    db = _load()
    for user in db.get("users", {}).values():
        if user.get("username", "").lower() == key:
            return user
    return None


def get_user_by_email(email):
    email = (email or "").strip().lower()
    if not email:
        return None
    db = _load()
    for user in db.get("users", {}).values():
        if user.get("email", "").lower() == email:
            return user
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

    with _lock:
        db = _load()
        user_id = uuid.uuid4().hex[:10]
        user = {
            "id": user_id,
            "username": username,
            "email": (email or "").strip().lower(),
            "role": role,
            "password_hash": generate_password_hash(password),
            "created_at": _now(),
        }
        db.setdefault("users", {})[user_id] = user
        _save(db)
        return _user_public(user)


def ensure_default_admin():
    db = _load()
    for user in db.get("users", {}).values():
        if user.get("username", "").lower() == "admin":
            user["role"] = "admin"
            user["password_hash"] = generate_password_hash("admin123")
            _save(db)
            return _user_public(user)
    return register_user("admin", "admin123", role="admin")


def list_users():
    db = _load()
    return [_user_public(user) for user in db.get("users", {}).values()]


def update_user(user_id, username=None, password=None, role=None):
    with _lock:
        db = _load()
        user = db.get("users", {}).get(user_id)
        if not user:
            raise KeyError(f"Không tìm thấy người dùng {user_id}")

        new_username = (username or user["username"]).strip()
        new_role = (role or user.get("role", "user")).strip().lower()
        if new_role not in {"user", "admin"}:
            raise ValueError("Role phải là user hoặc admin.")
        if len(new_username) < 3:
            raise ValueError("Tên đăng nhập phải có ít nhất 3 ký tự.")
        if username is not None and get_user_by_username(new_username) and get_user_by_username(new_username)["id"] != user_id:
            raise ValueError("Tên đăng nhập này đã tồn tại.")

        if password is not None:
            password = password or ""
            if len(password) < 6:
                raise ValueError("Mật khẩu phải có ít nhất 6 ký tự.")
            user["password_hash"] = generate_password_hash(password)

        user["username"] = new_username
        user["role"] = new_role
        _save(db)
        return _user_public(user)


def delete_user(user_id):
    with _lock:
        db = _load()
        user = db.get("users", {}).get(user_id)
        if not user:
            return
        db["users"].pop(user_id, None)
        for nb in db.get("notebooks", {}).values():
            if nb.get("user_id") == user_id:
                nb["user_id"] = None
        _save(db)


def verify_user(username, password):
    user = get_user_by_username(username)
    if not user:
        return False
    return check_password_hash(user.get("password_hash", ""), password)


def get_custom_instructions(user_id):
    """Lấy Hướng dẫn tùy chỉnh (Cá nhân hóa) của MỘT tài khoản cụ thể — mỗi user một bản riêng."""
    if not user_id:
        return ""
    db = _load()
    user = db.get("users", {}).get(user_id)
    if not user:
        return ""
    return user.get("custom_instructions", "")


def set_custom_instructions(user_id, text):
    """Lưu Hướng dẫn tùy chỉnh cho riêng tài khoản user_id, không ảnh hưởng tài khoản khác."""
    with _lock:
        db = _load()
        user = db.get("users", {}).get(user_id)
        if not user:
            raise KeyError(f"Không tìm thấy người dùng {user_id}")
        user["custom_instructions"] = str(text or "").strip()
        _save(db)
        return user["custom_instructions"]


def _today_str():
    return datetime.now().strftime("%Y-%m-%d")


def get_usage_stats(user_id):
    """Lấy hạn mức sử dụng (số token ước tính + số lần gọi API) TRONG NGÀY HÔM NAY
    của MỘT tài khoản cụ thể — mỗi user một bộ đếm riêng, không dùng chung với
    tài khoản khác (trước đây bị lưu ở localStorage của trình duyệt nên admin và
    user đăng nhập cùng máy sẽ bị lẫn số liệu của nhau)."""
    if not user_id:
        return {"date": _today_str(), "tokens": 0, "calls": 0}
    db = _load()
    user = db.get("users", {}).get(user_id)
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
    """Cộng dồn hạn mức sử dụng CHỈ cho riêng tài khoản user_id, reset lại mỗi
    ngày mới, không ảnh hưởng tới hạn mức của tài khoản khác."""
    if not user_id:
        return {"date": _today_str(), "tokens": 0, "calls": 0}
    with _lock:
        db = _load()
        user = db.get("users", {}).get(user_id)
        if not user:
            return {"date": _today_str(), "tokens": 0, "calls": 0}
        today = _today_str()
        stats = user.get("usage_stats") or {}
        if stats.get("date") != today:
            stats = {"date": today, "tokens": 0, "calls": 0}
        stats["tokens"] = int(stats.get("tokens") or 0) + max(0, int(tokens or 0))
        stats["calls"] = int(stats.get("calls") or 0) + 1
        user["usage_stats"] = stats
        _save(db)
        return stats


def _notebook_summary(nb, owner=None):
    summary = {
        "id": nb["id"],
        "name": nb["name"],
        "created_at": nb["created_at"],
        "doc_count": len(nb["documents"]),
        "user_id": nb.get("user_id"),
    }
    if owner is not None:
        summary["owner_username"] = owner.get("username")
        summary["owner_role"] = owner.get("role", "user")
    return summary


def list_notebooks(user_id=None, role=None):
    db = _load()
    notebooks = list(db.get("notebooks", {}).values())
    if user_id is not None and role != "admin":
        notebooks = [nb for nb in notebooks if nb.get("user_id") == user_id]
    result = []
    for nb in notebooks:
        owner = get_user_by_id(nb.get("user_id")) if nb.get("user_id") else None
        result.append(_notebook_summary(nb, owner=owner))
    return result


def list_notebooks_for_user(user_id, role=None):
    return list_notebooks(user_id=user_id, role=role)


def list_all_notebooks_with_users():
    db = _load()
    notebooks = []
    for nb in db.get("notebooks", {}).values():
        owner = get_user_by_id(nb.get("user_id")) if nb.get("user_id") else None
        notebooks.append(_notebook_summary(nb, owner=owner))
    return notebooks


def create_notebook(name, user_id=None):
    with _lock:
        db = _load()
        nb_id = uuid.uuid4().hex[:10]
        db["notebooks"][nb_id] = {
            "id": nb_id,
            "name": name or "Notebook chưa đặt tên",
            "created_at": _now(),
            "user_id": user_id,
            "documents": [],
            "chat_history": [],
            "studio_items": [],
        }
        _save(db)
        return db["notebooks"][nb_id]


def get_notebook(nb_id, user_id=None, role=None):
    db = _load()
    nb = db["notebooks"].get(nb_id)
    if not nb:
        raise KeyError(f"Không tìm thấy notebook {nb_id}")
    is_admin = role == "admin"
    if user_id is not None and nb.get("user_id") != user_id and not is_admin:
        raise PermissionError("Bạn không có quyền truy cập notebook này.")
    nb.setdefault("studio_items", [])
    for item in nb["studio_items"]:
        if not item.get("id"):
            item["id"] = uuid.uuid4().hex[:10]
        if not item.get("created_at"):
            item["created_at"] = _now()
    _save(db)
    return nb


def add_studio_item(nb_id, item, user_id=None, role=None):
    with _lock:
        db = _load()
        nb = db["notebooks"].get(nb_id)
        if not nb:
            raise KeyError(f"Không tìm thấy notebook {nb_id}")
        is_admin = role == "admin"
        if user_id is not None and nb.get("user_id") != user_id and not is_admin:
            raise PermissionError("Bạn không có quyền lưu sản phẩm Studio trong notebook này.")
        nb.setdefault("studio_items", [])
        item.setdefault("id", uuid.uuid4().hex[:10])
        item.setdefault("created_at", _now())
        nb["studio_items"].insert(0, item)
        _save(db)
        return item


def delete_studio_item(nb_id, item_id, user_id=None, role=None):
    with _lock:
        db = _load()
        nb = db["notebooks"].get(nb_id)
        if not nb:
            raise KeyError(f"Không tìm thấy notebook {nb_id}")
        is_admin = role == "admin"
        if user_id is not None and nb.get("user_id") != user_id and not is_admin:
            raise PermissionError("Bạn không có quyền xóa sản phẩm Studio trong notebook này.")
        original_items = nb.setdefault("studio_items", [])
        for item in original_items:
            if not item.get("id"):
                item["id"] = uuid.uuid4().hex[:10]
            if not item.get("created_at"):
                item["created_at"] = _now()
        filtered_items = [item for item in original_items if item.get("id") != item_id]
        if len(filtered_items) == len(original_items):
            raise KeyError("Không tìm thấy sản phẩm Studio.")
        nb["studio_items"] = filtered_items
        _save(db)


def delete_notebook(nb_id, user_id=None, role=None):
    with _lock:
        db = _load()
        nb = db["notebooks"].get(nb_id)
        if not nb:
            return
        is_admin = role == "admin"
        if user_id is not None and nb.get("user_id") != user_id and not is_admin:
            raise PermissionError("Bạn không có quyền xóa notebook này.")
        db["notebooks"].pop(nb_id, None)
        _save(db)


def clear_chat_history(nb_id, user_id=None, role=None):
    """Xóa lịch sử trò chuyện của MỘT notebook (note) cụ thể — giữ nguyên tài liệu,
    sản phẩm Studio (quiz/mindmap/flashcard/...) của note này, và không đụng tới
    note khác hay Hướng dẫn cá nhân hóa (được lưu riêng ở phía trình duyệt)."""
    with _lock:
        db = _load()
        nb = db["notebooks"].get(nb_id)
        if not nb:
            raise KeyError(f"Không tìm thấy notebook {nb_id}")
        is_admin = role == "admin"
        if user_id is not None and nb.get("user_id") != user_id and not is_admin:
            raise PermissionError("Bạn không có quyền xóa lịch sử trò chuyện của notebook này.")
        nb["chat_history"] = []
        _save(db)


def add_document(nb_id, document, user_id=None, role=None):
    """document: {id, name, source_type, chunks: [{id, text, position}]}"""
    with _lock:
        db = _load()
        nb = db["notebooks"][nb_id]
        is_admin = role == "admin"
        if user_id is not None and nb.get("user_id") != user_id and not is_admin:
            raise PermissionError("Bạn không có quyền thêm tài liệu vào notebook này.")
        nb["documents"].append(document)
        _save(db)
        return document


def upsert_document(nb_id, document, user_id=None, role=None):
    """Thêm mới nếu chưa có, hoặc thay thế tài liệu cùng id nếu đã tồn tại.
    Dùng để lưu tạm tiến trình quét/OCR dở dang (document["processing"] = True),
    để nếu tiến trình bị tắt đột ngột (đóng cmd) thì không mất trắng phần đã quét."""
    with _lock:
        db = _load()
        nb = db["notebooks"][nb_id]
        is_admin = role == "admin"
        if user_id is not None and nb.get("user_id") != user_id and not is_admin:
            raise PermissionError("Bạn không có quyền thêm tài liệu vào notebook này.")
        docs = nb["documents"]
        for i, d in enumerate(docs):
            if d["id"] == document["id"]:
                docs[i] = document
                break
        else:
            docs.append(document)
        _save(db)
        return document


def remove_document(nb_id, doc_id, user_id=None, role=None):
    with _lock:
        db = _load()
        nb = db["notebooks"][nb_id]
        is_admin = role == "admin"
        if user_id is not None and nb.get("user_id") != user_id and not is_admin:
            raise PermissionError("Bạn không có quyền xóa tài liệu khỏi notebook này.")
        nb["documents"] = [d for d in nb["documents"] if d["id"] != doc_id]
        _save(db)


def append_chat(nb_id, role, content, citations=None, user_id=None, nb_role=None):
    with _lock:
        db = _load()
        nb = db["notebooks"][nb_id]
        is_admin = nb_role == "admin"
        if user_id is not None and nb.get("user_id") != user_id and not is_admin:
            raise PermissionError("Bạn không có quyền ghi vào notebook này.")
        nb["chat_history"].append(
            {
                "role": role,
                "content": content,
                "citations": citations or [],
                "ts": _now(),
            }
        )
        _save(db)


def all_chunks(nb_id, user_id=None, role=None):
    nb = get_notebook(nb_id, user_id=user_id, role=role)
    chunks = []
    for doc in nb["documents"]:
        for c in doc["chunks"]:
            chunks.append(
                {
                    "chunk_id": c["id"],
                    "text": c["text"],
                    "position": c.get("position", ""),
                    "doc_id": doc["id"],
                    "doc_name": doc["name"],
                }
            )
    return chunks
