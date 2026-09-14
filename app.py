import os
import json
import base64
import mimetypes
import time
import uuid
import threading
import secrets
from datetime import timedelta
from functools import wraps

from flask import Flask, jsonify, request, send_from_directory, render_template, session, redirect, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import storage
import ingest
import retrieval
import llm_client
import audio
from config import load_config, save_config

app = Flask(__name__)

_secret_key = os.environ.get("FLASK_SECRET_KEY", "").strip()
_is_production = bool(os.environ.get("RENDER") or os.environ.get("PORT"))
if not _secret_key:
    if _is_production:
        # Không cho phép fallback về một chuỗi cố định khi chạy thật: bất kỳ ai
        # đọc được mã nguồn (repo công khai, hoặc chỉ cần đoán) cũng biết được
        # secret này và có thể tự ký ("forge") cookie phiên đăng nhập, kể cả
        # giả làm admin. Nếu thiếu biến môi trường, dừng khởi động luôn thay vì
        # chạy với một lỗ hổng nghiêm trọng.
        raise RuntimeError(
            "Thiếu biến môi trường FLASK_SECRET_KEY. Hãy đặt một chuỗi ngẫu nhiên dài "
            "(ví dụ: python -c \"import secrets; print(secrets.token_hex(32))\") "
            "trong Render Environment trước khi deploy."
        )
    _secret_key = "notebooklm-local-secret"  # chỉ dùng khi chạy local để dev
app.secret_key = _secret_key

app.config["MAX_CONTENT_LENGTH"] = 250 * 1024 * 1024  # 250MB mỗi lần upload
# Cookie phiên đăng nhập: chỉ gửi qua HTTPS khi chạy thật, JS không đọc được,
# và chặn phần lớn tấn công CSRF nhờ SameSite=Lax.
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = _is_production
# "Remember me": khi người dùng tích chọn, phiên đăng nhập (cookie session) sẽ
# được đánh dấu "permanent" và tồn tại tối đa 30 ngày thay vì bị xoá ngay khi
# đóng trình duyệt. Khi KHÔNG tích, session vẫn là session-cookie bình thường
# (mất khi đóng trình duyệt) — xem hàm login()/firebase_auth() bên dưới.
app.permanent_session_lifetime = timedelta(days=30)
storage.ensure_default_admin()

# Giới hạn số lần thử đăng nhập/đăng ký để chống brute-force mật khẩu.
# Lưu ý: bộ nhớ giới hạn ở đây là in-memory — đủ dùng cho 1 instance Render;
# nếu sau này scale nhiều instance, cần chuyển sang storage_uri="redis://...".
limiter = Limiter(get_remote_address, app=app, default_limits=[])

ALLOWED_EXT = {".pdf", ".docx", ".txt", ".md"} | ingest.IMAGE_EXTS
upload_progress = {}
upload_progress_lock = threading.Lock()


def firebase_credentials_value():
    value = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
    if not value:
        return None
    if value.startswith("{"):
        return json.loads(value)
    return os.path.abspath(os.path.expandvars(os.path.expanduser(value)))


def error_response(exc, code=400):
    message = str(exc)
    lowered = message.lower()
    if code >= 500 and ("429" in lowered or "quota" in lowered or "rate limit" in lowered):
        return jsonify({
            "error": (
                "Google AI đã hết hạn mức miễn phí cho API key này. "
                "Hãy chờ hạn mức được cấp lại hoặc dùng API key/project khác."
            ),
            "code": "quota_exceeded",
        }), 429
    return jsonify({"error": message}), code


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return storage.get_user_by_id(user_id)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            if request.path.startswith("/api/"):
                return error_response("Bạn cần đăng nhập để tiếp tục.", 401)
            return redirect(url_for("landing"))
        return view(*args, **kwargs)
    return wrapped


def ensure_notebook_access(nb_id, user=None):
    user = user or current_user()
    if not user:
        raise PermissionError("Bạn cần đăng nhập để tiếp tục.")
    return storage.get_notebook(nb_id, user_id=user["id"], role=user.get("role"))


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            if request.path.startswith("/api/"):
                return error_response("Bạn cần đăng nhập để tiếp tục.", 401)
            return redirect(url_for("landing"))
        if user.get("role") != "admin":
            if request.path.startswith("/api/"):
                return error_response("Bạn cần quyền admin để thực hiện hành động này.", 403)
            return redirect(url_for("chat_page"))
        return view(*args, **kwargs)
    return wrapped


def selected_documents(nb, data):
    document_ids = data.get("document_ids")
    if document_ids is None:
        return nb["documents"]
    wanted = set(document_ids)
    documents = [doc for doc in nb["documents"] if doc["id"] in wanted]
    if not documents:
        raise ValueError("Hãy chọn ít nhất một tài liệu.")
    return documents


def runtime_ai_config():
    api_key = (session.get("personal_api_key") or "").strip()
    model = (session.get("personal_model") or "gemini-2.5-flash").strip()
    provider = (session.get("personal_provider") or "auto").strip()
    if not api_key and not model and provider == "auto":
        return None
    cfg = load_config()
    if api_key:
        cfg["api_key"] = api_key
    if model:
        cfg["model"] = model
    if provider:
        cfg["provider"] = provider
    return cfg


@app.errorhandler(413)
def request_entity_too_large(_exc):
    return error_response("Tệp quá lớn. Kích thước tối đa là 250MB.", 413)


@app.route("/api/auth/me", methods=["GET"])
def auth_me():
    user = current_user()
    if not user:
        return jsonify({"authenticated": False}), 401
    return jsonify({
        "authenticated": True,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": user.get("email", ""),
            "role": user.get("role", "user"),
        },
    })


USAGE_TOKEN_LIMIT = 100000


@app.route("/api/account/usage", methods=["GET"])
@login_required
def get_usage():
    """Trả về hạn mức sử dụng (token/lượt gọi API) CỦA RIÊNG tài khoản đang đăng
    nhập — không dùng chung với tài khoản khác."""
    stats = storage.get_usage_stats(current_user()["id"])
    return jsonify({
        "date": stats["date"],
        "tokens": stats["tokens"],
        "calls": stats["calls"],
        "limit": USAGE_TOKEN_LIMIT,
    })


def _record_usage(request_text="", response_text=""):
    """Ước tính số token đã dùng cho một lượt gọi AI và cộng dồn vào hạn mức
    CHỈ của tài khoản đang đăng nhập hiện tại."""
    user = current_user()
    if not user:
        return
    estimated_tokens = max(20, (len(request_text or "") + len(response_text or "")) // 4)
    storage.record_usage(user["id"], estimated_tokens)


@app.route("/api/account/personalization", methods=["GET"])
@login_required
def get_personalization():
    """Trả về Hướng dẫn tùy chỉnh CỦA RIÊNG tài khoản đang đăng nhập."""
    text = storage.get_custom_instructions(current_user()["id"])
    return jsonify({"custom_instructions": text})


@app.route("/api/account/personalization", methods=["POST"])
@login_required
def save_personalization():
    """Lưu Hướng dẫn tùy chỉnh CHỈ cho tài khoản đang đăng nhập, không đụng tài khoản khác."""
    data = request.get_json(force=True) if request.data else {}
    text = data.get("custom_instructions", "")
    try:
        saved = storage.set_custom_instructions(current_user()["id"], text)
    except KeyError as e:
        return error_response(e, 404)
    return jsonify({"ok": True, "custom_instructions": saved})


@app.route("/api/auth/register", methods=["POST"])
@limiter.limit("10 per hour")
def register():
    data = request.get_json(force=True) if request.data else {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    role = (data.get("role") or "user").strip().lower()
    remember = bool(data.get("remember", True))
    if role not in {"user", "admin"}:
        return error_response("Role phải là user hoặc admin.", 400)
    try:
        user = storage.register_user(username, password, role=role)
    except ValueError as e:
        return error_response(e, 400)

    session.permanent = remember
    session["user_id"] = user["id"]
    return jsonify({"ok": True, "user": user})


@app.route("/api/auth/login", methods=["POST"])
@limiter.limit("10 per minute")
def login():
    data = request.get_json(force=True) if request.data else {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    remember = bool(data.get("remember", True))

    if not username or not password:
        return error_response("Tên đăng nhập và mật khẩu không được để trống.", 400)
    if not storage.verify_user(username, password):
        return error_response("Tên đăng nhập hoặc mật khẩu không đúng.", 401)

    user = storage.get_user_by_username(username)
    # "Remember me": tích chọn thì giữ đăng nhập tối đa 30 ngày (session.permanent
    # + app.permanent_session_lifetime), không tích thì phiên mất khi đóng trình duyệt.
    session.permanent = remember
    session["user_id"] = user["id"]
    return jsonify({
        "ok": True,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": user.get("email", ""),
            "role": user.get("role", "user"),
        },
    })


@app.route("/api/auth/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/auth/password", methods=["POST"])
@login_required
def change_password():
    data = request.get_json(force=True) if request.data else {}
    current_password = data.get("current_password") or ""
    new_password = data.get("new_password") or ""
    id_token = (data.get("id_token") or "").strip()
    user = current_user()

    if not current_password or not new_password or not id_token:
        return error_response("Cần nhập mật khẩu hiện tại, mật khẩu mới và xác thực email.", 400)
    if len(new_password) < 6:
        return error_response("Mật khẩu mới phải có ít nhất 6 ký tự.", 400)
    if not user.get("email"):
        return error_response("Tài khoản này chưa có email để xác thực.", 400)
    try:
        import firebase_admin
        from firebase_admin import auth as firebase_auth_api, credentials
        if not firebase_admin._apps:
            service_account = firebase_credentials_value()
            if not service_account:
                return error_response("Chưa cấu hình Firebase Service Account trên server.", 503)
            firebase_admin.initialize_app(credentials.Certificate(service_account))
        decoded = firebase_auth_api.verify_id_token(id_token, check_revoked=False)
        token_email = (decoded.get("email") or "").strip().lower()
        if token_email != user.get("email", "").lower() or not decoded.get("email_verified"):
            return error_response("Email chưa được xác thực. Hãy xác thực email trước khi đổi mật khẩu.", 403)
        firebase_auth_api.update_user(decoded["uid"], password=new_password)
    except ImportError:
        return error_response("Chưa cài firebase-admin trên server.", 503)
    except Exception as exc:
        return error_response(f"Không thể xác thực email: {exc}", 401)

    try:
        updated_user = storage.update_user(user["id"], password=new_password)
        return jsonify({"ok": True, "user": updated_user})
    except (ValueError, KeyError) as exc:
        return error_response(exc, 400)


@app.route("/api/auth/firebase", methods=["POST"])
@limiter.limit("10 per minute")
def firebase_auth():
    try:
        import firebase_admin
        from firebase_admin import auth as firebase_auth_api, credentials
    except ImportError:
        return error_response("Chưa cài firebase-admin. Hãy chạy pip install -r requirements.txt.", 503)

    data = request.get_json(force=True) or {}
    token = data.get("id_token")
    remember = bool(data.get("remember", True))
    if not token:
        return error_response("Thiếu Firebase ID token.", 401)

    try:
        if not firebase_admin._apps:
            service_account = firebase_credentials_value()
            if not service_account:
                return error_response("Chưa cấu hình FIREBASE_SERVICE_ACCOUNT_JSON trên server.", 503)
            firebase_admin.initialize_app(credentials.Certificate(service_account))
        decoded = firebase_auth_api.verify_id_token(token)
        email = (decoded.get("email") or "").strip().lower()
        if not email:
            return error_response("Tài khoản Firebase chưa có email.", 401)
    except Exception as exc:
        return error_response(f"Không thể xác minh Firebase token: {exc}", 401)

    user = storage.get_user_by_email(email)
    if not user:
        base_username = email.split("@", 1)[0][:24] or "user"
        username = base_username
        suffix = 1
        while storage.get_user_by_username(username):
            username = f"{base_username[:20]}-{suffix}"
            suffix += 1
        user = storage.register_user(username, secrets.token_urlsafe(32), email=email)
    else:
        user = storage._user_public(user)

    session.permanent = remember
    session["user_id"] = user["id"]
    return jsonify({"ok": True, "user": user})


@app.route("/api/auth/firebase/identifier", methods=["POST"])
def firebase_identifier():
    identifier = ((request.get_json(force=True) or {}).get("identifier") or "").strip()
    if not identifier:
        return error_response("Hãy nhập username hoặc email.", 400)
    if "@" in identifier:
        return jsonify({"email": identifier.lower()})
    user = storage.get_user_by_username(identifier)
    if not user or not user.get("email"):
        return error_response("Không tìm thấy username này.", 404)
    return jsonify({"email": user["email"]})


@app.route("/api/auth/firebase/profile", methods=["POST"])
def firebase_profile():
    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    token = data.get("id_token")
    if not username or not token:
        return error_response("Thiếu username hoặc Firebase ID token.", 400)
    if storage.get_user_by_username(username):
        return error_response("Username này đã được sử dụng.", 409)

    try:
        import firebase_admin
        from firebase_admin import auth as firebase_auth_api, credentials
        if not firebase_admin._apps:
            service_account = firebase_credentials_value()
            if not service_account:
                return error_response("Chưa cấu hình FIREBASE_SERVICE_ACCOUNT_JSON trên server.", 503)
            firebase_admin.initialize_app(credentials.Certificate(service_account))
        decoded = firebase_auth_api.verify_id_token(token, check_revoked=False)
        email = (decoded.get("email") or "").strip().lower()
        if not email:
            return error_response("Tài khoản Firebase chưa có email.", 401)
    except Exception as exc:
        return error_response(f"Không thể xác minh Firebase token: {exc}", 401)

    existing = storage.get_user_by_email(email)
    if existing:
        return error_response("Email này đã được liên kết với tài khoản khác.", 409)
    user = storage.register_user(username, secrets.token_urlsafe(32), email=email)
    return jsonify({"ok": True, "user": user})


@app.route("/api/uploads/<upload_id>", methods=["GET"])
@login_required
def get_upload_progress(upload_id):
    with upload_progress_lock:
        return jsonify(upload_progress.get(upload_id, {"status": "unknown"}))


@app.route("/api/notebooks/<nb_id>/uploads", methods=["GET"])
@login_required
def list_notebook_uploads(nb_id):
    """Trả về các lượt tải tài liệu đang xử lý (hoặc vừa xong) của notebook này,
    để giao diện có thể khôi phục thanh tiến trình sau khi refresh trang / đăng nhập lại."""
    try:
        ensure_notebook_access(nb_id)
    except (KeyError, PermissionError) as e:
        return error_response(e, 404 if isinstance(e, KeyError) else 403)

    now = time.time()
    result = []
    with upload_progress_lock:
        for upload_id, info in upload_progress.items():
            if info.get("nb_id") != nb_id:
                continue
            # Giữ lại các mục đang xử lý vô thời hạn; mục đã xong/lỗi chỉ giữ trong ít phút
            # để client kịp nhận và cập nhật giao diện.
            if info.get("status") == "processing" or now - info.get("updated_at", now) < 300:
                result.append({
                    "upload_id": upload_id,
                    "status": info.get("status"),
                    "filename": info.get("filename"),
                    "doc_id": info.get("doc_id"),
                    "page": info.get("page", 0),
                    "total": info.get("total", 0),
                    "error": info.get("error"),
                })
    return jsonify(result)


# ---------- Trang chính ----------


@app.route("/")
def landing():
    if current_user():
        return redirect(url_for("chat_page"))
    return render_template("landing.html")


@app.route("/login")
def login_page():
    if current_user():
        return redirect(url_for("chat_page"))
    return render_template("auth.html", mode="login")


@app.route("/register")
def register_page():
    if current_user():
        return redirect(url_for("chat_page"))
    return render_template("auth.html", mode="register")


@app.route("/chat")
@login_required
def chat_page():
    return render_template("index.html")


@app.route("/admin")
@login_required
@admin_required
def admin_page():
    return render_template("admin.html")


# ---------- Cấu hình ----------


@app.route("/api/config", methods=["GET"])
@admin_required
def get_config():
    cfg = load_config()
    return jsonify({
        "model": cfg.get("model"),
        "provider": cfg.get("provider", "auto"),
        "openai_model": cfg.get("openai_model"),
        "has_api_key": bool(cfg.get("api_key")),
        "has_openai_key": bool(cfg.get("openai_api_key")),
        "has_openrouter_key": bool(cfg.get("openrouter_api_key")),
        "openrouter_model": cfg.get("openrouter_model"),
        "anthropic_model": cfg.get("anthropic_model"),
        "has_anthropic_key": bool(cfg.get("anthropic_api_key")),
        "has_github_token": bool(cfg.get("github_token")),
    })


@app.route("/api/personal-config", methods=["POST"])
@login_required
def set_personal_config():
    data = request.get_json(force=True) if request.data else {}
    session["personal_api_key"] = (data.get("api_key") or "").strip()
    session["personal_model"] = (data.get("model") or "gemini-2.5-flash").strip()
    session["personal_provider"] = (data.get("provider") or "auto").strip()
    return jsonify({"ok": True, "config": {
        "api_key": session.get("personal_api_key", ""),
        "model": session.get("personal_model", "gemini-2.5-flash"),
        "provider": session.get("personal_provider", "auto"),
    }})


@app.route("/api/personal-config", methods=["GET"])
@login_required
def get_personal_config():
    return jsonify({
        "api_key": session.get("personal_api_key", ""),
        "model": session.get("personal_model", "gemini-2.5-flash"),
        "provider": session.get("personal_provider", "auto"),
    })


@app.route("/api/config", methods=["POST"])
@admin_required
def set_config():
    data = request.get_json(force=True)
    cfg = save_config(
        api_key=data.get("api_key"),
        model=data.get("model"),
        provider=data.get("provider"),
        openai_api_key=data.get("openai_api_key"),
        openai_model=data.get("openai_model"),
        openrouter_api_key=data.get("openrouter_api_key"),
        openrouter_model=data.get("openrouter_model"),
        anthropic_api_key=data.get("anthropic_api_key"),
        anthropic_model=data.get("anthropic_model"),
        github_token=data.get("github_token"),
    )
    return jsonify({
        "model": cfg.get("model"),
        "provider": cfg.get("provider", "auto"),
        "openai_model": cfg.get("openai_model"),
        "has_api_key": bool(cfg.get("api_key")),
        "has_openai_key": bool(cfg.get("openai_api_key")),
        "has_openrouter_key": bool(cfg.get("openrouter_api_key")),
        "openrouter_model": cfg.get("openrouter_model"),
        "anthropic_model": cfg.get("anthropic_model"),
        "has_anthropic_key": bool(cfg.get("anthropic_api_key")),
        "has_github_token": bool(cfg.get("github_token")),
    })


@app.route("/api/feedback", methods=["POST"])
@login_required
def submit_feedback():
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip()
    feedback_type = (request.form.get("type") or "").strip().lower()
    subject = (request.form.get("subject") or "").strip()
    message = (request.form.get("message") or "").strip()
    image_data = ""
    image = request.files.get("image")
    if image and image.filename:
        image_bytes = image.read()
        if len(image_bytes) > 700 * 1024:
            return error_response("Ảnh đính kèm không được vượt quá 700 KB.", 400)
        content_type = image.mimetype or mimetypes.guess_type(image.filename)[0] or ""
        if not content_type.startswith("image/"):
            return error_response("Tệp đính kèm phải là hình ảnh.", 400)
        image_data = f"data:{content_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
    try:
        feedback = storage.create_feedback(
            name,
            email,
            feedback_type,
            subject,
            message,
            image_data=image_data,
            user_id=current_user()["id"],
        )
        feedback.pop("image_data", None)
        return jsonify({"ok": True, "feedback": feedback}), 201
    except ValueError as e:
        return error_response(str(e), 400)


@app.route("/api/admin/feedback", methods=["GET"])
@admin_required
def admin_list_feedback():
    return jsonify(storage.list_feedback())


@app.route("/api/admin/feedback/<feedback_id>", methods=["PATCH"])
@admin_required
def admin_update_feedback(feedback_id):
    data = request.get_json(force=True) if request.data else {}
    try:
        return jsonify({"ok": True, "feedback": storage.update_feedback_status(feedback_id, data.get("status"))})
    except (KeyError, ValueError) as e:
        return error_response(str(e), 400)


# ---------- Notebooks ----------


@app.route("/api/notebooks", methods=["GET"])
@login_required
def list_notebooks():
    user = current_user()
    if user.get("role") == "admin":
        return jsonify(storage.list_notebooks_for_user(user["id"], role="admin"))
    return jsonify(storage.list_notebooks_for_user(user["id"]))


@app.route("/api/notebooks", methods=["POST"])
@login_required
def create_notebook():
    data = request.get_json(force=True) if request.data else {}
    name = (data.get("name") or data.get("notebook_name") or "").strip()
    if not name:
        return error_response("Tên sổ tay không được để trống.", 400)
    nb = storage.create_notebook(name, user_id=current_user()["id"])
    return jsonify({"ok": True, "notebook": nb})


@app.route("/api/admin/notebooks", methods=["GET"])
@admin_required
def admin_list_notebooks():
    return jsonify(storage.list_all_notebooks_with_users())


@app.route("/api/admin/notebooks", methods=["POST"])
@admin_required
def admin_create_notebook():
    data = request.get_json(force=True) if request.data else {}
    name = (data.get("name") or data.get("notebook_name") or "").strip()
    user_id = data.get("user_id")
    if user_id is None:
        user_id = data.get("userId")
    if user_id is None:
        user_id = data.get("owner_id")
    if user_id in (None, ""):
        user_id = current_user()["id"]
    user_id = str(user_id).strip() if user_id is not None else current_user()["id"]

    if not name:
        return error_response("Tên sổ tay không được để trống.", 400)
    if user_id and not storage.get_user_by_id(user_id):
        return error_response("Người dùng không tồn tại.", 404)

    try:
        nb = storage.create_notebook(name, user_id=user_id)
        return jsonify({"ok": True, "notebook": nb})
    except Exception as exc:
        return error_response(exc, 400)


@app.route("/api/admin/users", methods=["GET"])
@admin_required
def admin_list_users():
    db = storage._load()
    users = []
    for user in db.get("users", {}).values():
        users.append({
            "id": user["id"],
            "username": user["username"],
            "email": user.get("email", ""),
            "role": user.get("role", "user"),
            "created_at": user.get("created_at"),
            "notebook_count": len([
                nb for nb in db.get("notebooks", {}).values() if nb.get("user_id") == user["id"]
            ]),
        })
    return jsonify(users)


@app.route("/api/admin/users", methods=["POST"])
@admin_required
def admin_create_user():
    data = request.get_json(force=True) if request.data else {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    email = (data.get("email") or "").strip().lower()
    role = (data.get("role") or "user").strip().lower()
    if role not in {"user", "admin"}:
        return error_response("Role phải là user hoặc admin.", 400)
    try:
        verification_link = None
        if email:
            import firebase_admin
            from firebase_admin import auth as firebase_auth_api, credentials
            if not firebase_admin._apps:
                service_account = firebase_credentials_value()
                if not service_account:
                    return error_response("Chưa cấu hình Firebase Service Account trên server.", 503)
                firebase_admin.initialize_app(credentials.Certificate(service_account))
            firebase_user = firebase_auth_api.create_user(email=email, password=password, display_name=username)
            user = storage.register_user(username, password, role=role, email=email)
            firebase_auth_api.update_user(firebase_user.uid, email_verified=False)
            verification_link = firebase_auth_api.generate_email_verification_link(email)
        else:
            user = storage.register_user(username, password, role=role)
    except ValueError as e:
        return error_response(e, 400)
    return jsonify({"ok": True, "user": user, "verification_link": verification_link})


@app.route("/api/admin/documents", methods=["GET"])
@admin_required
def admin_list_documents():
    db = storage._load()
    documents = []
    for notebook in db.get("notebooks", {}).values():
        owner = storage.get_user_by_id(notebook.get("user_id"))
        for document in notebook.get("documents", []):
            documents.append({
                "id": document.get("id"),
                "name": document.get("name", ""),
                "source_type": document.get("source_type", ""),
                "created_at": document.get("created_at", notebook.get("created_at")),
                "notebook_id": notebook.get("id"),
                "notebook_name": notebook.get("name", ""),
                "user_id": notebook.get("user_id"),
                "owner_username": owner.get("username") if owner else "Không rõ",
                "owner_email": owner.get("email", "") if owner else "",
            })
    return jsonify(documents)


@app.route("/api/admin/documents/<nb_id>/<doc_id>", methods=["DELETE"])
@admin_required
def admin_delete_document(nb_id, doc_id):
    try:
        storage.remove_document(nb_id, doc_id, user_id=current_user()["id"], role="admin")
        return jsonify({"ok": True})
    except (KeyError, PermissionError) as exc:
        return error_response(exc, 404 if isinstance(exc, KeyError) else 403)


@app.route("/api/admin/users/<user_id>", methods=["PUT"])
@admin_required
def admin_update_user(user_id):
    data = request.get_json(force=True) if request.data else {}
    try:
        user = storage.update_user(
            user_id,
            username=data.get("username"),
            password=data.get("password"),
            role=data.get("role"),
        )
    except (ValueError, KeyError) as e:
        return error_response(e, 400 if isinstance(e, ValueError) else 404)
    return jsonify({"ok": True, "user": user})


@app.route("/api/admin/users/<user_id>", methods=["DELETE"])
@admin_required
def admin_delete_user(user_id):
    try:
        storage.delete_user(user_id)
        return jsonify({"ok": True})
    except Exception as e:
        return error_response(e, 400)


@app.route("/api/admin/notebooks/<nb_id>", methods=["DELETE"])
@admin_required
def admin_delete_notebook(nb_id):
    try:
        storage.delete_notebook(nb_id, user_id=current_user()["id"], role=current_user().get("role"))
        return jsonify({"ok": True})
    except PermissionError as e:
        return error_response(e, 403)


@app.route("/api/notebooks/<nb_id>", methods=["GET"])
@login_required
def get_notebook(nb_id):
    try:
        return jsonify(ensure_notebook_access(nb_id))
    except (KeyError, PermissionError) as e:
        return error_response(e, 404 if isinstance(e, KeyError) else 403)


@app.route("/api/notebooks/<nb_id>", methods=["DELETE"])
@login_required
def delete_notebook(nb_id):
    try:
        storage.delete_notebook(nb_id, user_id=current_user()["id"], role=current_user().get("role"))
        return jsonify({"ok": True})
    except PermissionError as e:
        return error_response(e, 403)


@app.route("/api/notebooks/<nb_id>/chat", methods=["DELETE"])
@login_required
def clear_notebook_chat_history(nb_id):
    """Xóa lịch sử trò chuyện CHỈ của note đang mở (không đụng note khác).
    Không đụng tới tài liệu, sản phẩm Studio (quiz/mindmap/flashcard/...) của note này,
    và không đụng tới Hướng dẫn cá nhân hóa (được lưu riêng, dùng chung cho mọi note)."""
    try:
        storage.clear_chat_history(nb_id, user_id=current_user()["id"], role=current_user().get("role"))
        return jsonify({"ok": True})
    except (KeyError, PermissionError) as e:
        return error_response(e, 404 if isinstance(e, KeyError) else 403)


# ---------- Tài liệu ----------


def _run_document_ingest(nb_id, user_id, role, tmp_path, filename, use_ocr, upload_id, doc_id):
    """Chạy trong luồng nền, độc lập với vòng đời của request HTTP đã tạo ra nó.
    Vì vậy việc refresh trang, đóng tab hay đăng xuất tài khoản ở trình duyệt
    KHÔNG làm dừng quá trình quét/OCR tài liệu đang chạy ở server.

    Ngoài ra, cứ vài giây lại tự lưu TẠM phần đã quét được xuống notebooks.json
    (đánh dấu "processing": True). Nhờ vậy nếu cửa sổ dòng lệnh (cmd) bị đóng
    đột ngột giữa chừng — khiến cả tiến trình Python bị tắt ngay lập tức — thì
    chỉ mất phần quét rất mới, thay vì mất trắng toàn bộ tài liệu."""

    ext = os.path.splitext(filename)[1]
    partial_state = {"last_saved_at": 0.0, "saved_any": False}

    def progress(page, total):
        with upload_progress_lock:
            entry = upload_progress.get(upload_id)
            if entry:
                entry.update(page=page, total=total, updated_at=time.time())

    def on_partial_pages(pages_so_far):
        now = time.time()
        # Lưu tạm mỗi ~4 giây một lần (đủ nhanh để không mất nhiều nếu bị tắt đột
        # ngột, nhưng không ghi đĩa liên tục gây chậm với PDF nhiều trang).
        if partial_state["saved_any"] and now - partial_state["last_saved_at"] < 4:
            return
        partial_state["last_saved_at"] = now
        partial_state["saved_any"] = True
        try:
            partial_doc = ingest.build_document(pages_so_far, filename, ext, doc_id=doc_id)
            partial_doc["processing"] = True
            partial_doc["pages_done"] = len(pages_so_far)
            storage.upsert_document(nb_id, partial_doc, user_id=user_id, role=role)
        except Exception:
            # Đừng để lỗi lưu tạm làm gián đoạn quá trình OCR chính.
            pass

    try:
        doc = ingest.parse_document(
            tmp_path,
            filename,
            use_ocr=use_ocr,
            progress=progress,
            on_partial_pages=on_partial_pages,
            doc_id=doc_id,
        )
        storage.upsert_document(nb_id, doc, user_id=user_id, role=role)
        with upload_progress_lock:
            entry = upload_progress.get(upload_id)
            if entry:
                entry.update(
                    status="complete",
                    page=entry.get("total", 0),
                    doc=doc,
                    updated_at=time.time(),
                )
    except ingest.OCRUnavailableError as e:
        _finalize_failed_upload(nb_id, user_id, role, doc_id, partial_state["saved_any"], str(e))
        with upload_progress_lock:
            entry = upload_progress.get(upload_id)
            if entry:
                entry.update(status="error", error=str(e), updated_at=time.time())
    except PermissionError as e:
        with upload_progress_lock:
            entry = upload_progress.get(upload_id)
            if entry:
                entry.update(status="error", error=str(e), updated_at=time.time())
    except Exception as e:
        _finalize_failed_upload(nb_id, user_id, role, doc_id, partial_state["saved_any"], str(e))
        with upload_progress_lock:
            entry = upload_progress.get(upload_id)
            if entry:
                entry.update(status="error", error=f"Không xử lý được tệp: {e}", updated_at=time.time())
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def _finalize_failed_upload(nb_id, user_id, role, doc_id, had_partial, error_message):
    """Nếu đã có bản lưu tạm (processing=True) cho tài liệu này, đánh dấu là bị
    lỗi/gián đoạn thay vì để mãi ở trạng thái "đang xử lý" (gây hiểu lầm là còn
    đang chạy). Phần nội dung đã quét được (nếu có) vẫn được giữ lại để dùng."""
    if not had_partial:
        return
    try:
        db_doc = None
        nb = storage.get_notebook(nb_id, user_id=user_id, role=role)
        for d in nb.get("documents", []):
            if d["id"] == doc_id:
                db_doc = d
                break
        if db_doc is not None:
            db_doc["processing"] = False
            db_doc["interrupted"] = True
            db_doc["error"] = error_message
            storage.upsert_document(nb_id, db_doc, user_id=user_id, role=role)
    except Exception:
        pass


@app.route("/api/notebooks/<nb_id>/documents", methods=["POST"])
@login_required
def upload_document(nb_id):
    current = current_user()
    try:
        storage.get_notebook(nb_id, user_id=current["id"], role=current.get("role"))
    except (KeyError, PermissionError) as e:
        return error_response(e, 404 if isinstance(e, KeyError) else 403)

    if "file" not in request.files:
        return error_response("Thiếu tệp tải lên.")
    file = request.files["file"]
    if not file.filename:
        return error_response("Tên tệp không hợp lệ.")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXT:
        return error_response(
            f"Định dạng {ext} chưa được hỗ trợ (chỉ PDF, DOCX, TXT, MD, hoặc ảnh PNG/JPG)."
        )

    use_ocr = request.form.get("ocr", "true").lower() != "false"

    tmp_name = f"{uuid.uuid4().hex[:10]}{ext}"
    tmp_path = os.path.join(storage.UPLOAD_DIR, tmp_name)
    upload_id = request.headers.get("X-Upload-ID", "") or uuid.uuid4().hex
    doc_id = uuid.uuid4().hex[:10]
    file.save(tmp_path)

    # Chụp lại user_id/role ngay tại đây (thay vì gọi current_user() trong luồng nền,
    # vì luồng nền không còn context của request/session khi request này đã trả lời xong).
    user_id = current["id"]
    role = current.get("role")

    with upload_progress_lock:
        upload_progress[upload_id] = {
            "status": "processing",
            "page": 0,
            "total": 0,
            "nb_id": nb_id,
            "filename": file.filename,
            "doc_id": doc_id,
            "updated_at": time.time(),
        }

    thread = threading.Thread(
        target=_run_document_ingest,
        args=(nb_id, user_id, role, tmp_path, file.filename, use_ocr, upload_id, doc_id),
        daemon=True,
    )
    thread.start()

    # Trả lời ngay lập tức: việc quét/OCR tài liệu tiếp tục chạy ở server dù
    # trình duyệt có refresh, đóng tab hay tài khoản đăng xuất.
    return jsonify({"upload_id": upload_id, "doc_id": doc_id, "status": "processing"}), 202


@app.route("/api/notebooks/<nb_id>/chat/image-context", methods=["POST"])
@login_required
def chat_image_context(nb_id):
    """Nhận diện chữ (OCR) từ một ảnh vừa được DÁN trực tiếp vào khung chat
    (Ctrl+V), để đính kèm cùng câu hỏi. KHÁC với /documents: ảnh này KHÔNG
    được lưu thành tài liệu/nguồn trong Sổ tay — chỉ xử lý xong là xoá file
    tạm ngay, chỉ trả về văn bản OCR để frontend giữ tạm trong bộ nhớ và gửi
    kèm câu hỏi khi người dùng bấm Gửi."""
    current = current_user()
    try:
        storage.get_notebook(nb_id, user_id=current["id"], role=current.get("role"))
    except (KeyError, PermissionError) as e:
        return error_response(e, 404 if isinstance(e, KeyError) else 403)

    if "file" not in request.files:
        return error_response("Thiếu ảnh.")
    file = request.files["file"]
    if not file.filename:
        return error_response("Tên tệp không hợp lệ.")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ingest.IMAGE_EXTS:
        return error_response("Chỉ hỗ trợ dán ảnh (PNG/JPG/WEBP/BMP/TIFF) vào khung chat.")

    tmp_name = f"paste_{uuid.uuid4().hex[:10]}{ext}"
    tmp_path = os.path.join(storage.UPLOAD_DIR, tmp_name)
    file.save(tmp_path)
    try:
        pages = ingest.extract_pages(tmp_path, ext, use_ocr=True)
        text = "\n\n".join(p[0] for p in pages).strip()
        if not text:
            return error_response("Không nhận diện được chữ nào trong ảnh này (OCR trống).")
        return jsonify({"ok": True, "text": text})
    except ingest.OCRUnavailableError as e:
        return error_response(str(e), 400)
    except ValueError as e:
        return error_response(str(e), 400)
    except Exception as e:
        return error_response(f"Lỗi xử lý ảnh: {e}", 500)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


@app.route("/api/notebooks/<nb_id>/documents/<doc_id>", methods=["DELETE"])
@login_required
def delete_document(nb_id, doc_id):
    try:
        storage.remove_document(nb_id, doc_id, user_id=current_user()["id"], role=current_user().get("role"))
        return jsonify({"ok": True})
    except PermissionError as e:
        return error_response(e, 403)


@app.route("/api/notebooks/<nb_id>/studio", methods=["POST"])
@login_required
def save_studio_item(nb_id):
    data = request.get_json(force=True) if request.data else {}
    item_type = (data.get("type") or "").strip().lower()
    if item_type not in {"summary", "quiz", "audio", "mindmap", "flashcards"}:
        return error_response("Loại sản phẩm Studio không hợp lệ.", 400)
    if data.get("content") is None:
        return error_response("Thiếu nội dung sản phẩm Studio.", 400)
    try:
        item = storage.add_studio_item(
            nb_id,
            {
                "type": item_type,
                "title": (data.get("title") or item_type.title()).strip(),
                "content": data["content"],
                "created_at": storage._now(),
            },
            user_id=current_user()["id"],
            role=current_user().get("role"),
        )
        return jsonify({"ok": True, "item": item})
    except (KeyError, PermissionError) as exc:
        return error_response(exc, 404 if isinstance(exc, KeyError) else 403)


@app.route("/api/notebooks/<nb_id>/studio/<item_id>", methods=["DELETE"])
@login_required
def delete_studio_item(nb_id, item_id):
    try:
        storage.delete_studio_item(
            nb_id,
            item_id,
            user_id=current_user()["id"],
            role=current_user().get("role"),
        )
        return jsonify({"ok": True})
    except (KeyError, PermissionError) as exc:
        return error_response(exc, 404 if isinstance(exc, KeyError) else 403)


# ---------- Chat hỏi đáp có trích dẫn ----------


@app.route("/api/notebooks/<nb_id>/chat", methods=["POST"])
@login_required
def chat(nb_id):
    data = request.get_json(force=True)
    question = (data.get("question") or "").strip()
    # image_context: văn bản OCR của (các) ảnh vừa DÁN trực tiếp vào khung chat (ephemeral,
    # không phải tài liệu đã tải lên) — khi có, AI chỉ tập trung trả lời dựa trên ảnh này.
    image_context = (data.get("image_context") or "").strip()
    custom_instructions = storage.get_custom_instructions(current_user()["id"])  # theo từng tài khoản, không lấy từ client
    if not question:
        return error_response("Câu hỏi trống.")

    try:
        nb = ensure_notebook_access(nb_id)
    except (KeyError, PermissionError) as e:
        return error_response(e, 404 if isinstance(e, KeyError) else 403)

    current = current_user()

    try:
        if image_context:
            # Có ảnh vừa dán kèm câu hỏi: bỏ qua tìm kiếm trong nguồn tài liệu đã tải lên,
            # chỉ trả lời dựa trên nội dung ảnh + câu hỏi.
            result = llm_client.answer_question_with_image(
                image_context,
                question,
                nb["chat_history"],
                custom_instructions=custom_instructions,
                runtime_config=runtime_ai_config(),
            )
        else:
            chunks = storage.all_chunks(
                nb_id,
                user_id=current["id"],
                role=current.get("role"),
            )
            relevant = retrieval.top_chunks(chunks, question, k=10) if chunks else []
            result = llm_client.answer_question(
                relevant,
                question,
                nb["chat_history"],
                custom_instructions=custom_instructions,
                runtime_config=runtime_ai_config(),
            )
    except llm_client.NotConfiguredError as e:
        return error_response(e, 400)
    except Exception as e:
        return error_response(f"Lỗi gọi Gemini API: {e}", 502)

    storage.append_chat(nb_id, "user", question, user_id=current_user()["id"], nb_role=current_user().get("role"))
    storage.append_chat(nb_id, "assistant", result["answer"], result["citations"], user_id=current_user()["id"], nb_role=current_user().get("role"))
    _record_usage(question, result.get("answer", ""))
    return jsonify(result)


# ---------- Tóm tắt đa tài liệu ----------


@app.route("/api/notebooks/<nb_id>/summary", methods=["POST"])
@login_required
def summary(nb_id):
    data = request.get_json(force=True) if request.data else {}
    custom_instructions = storage.get_custom_instructions(current_user()["id"])  # theo từng tài khoản, không lấy từ client
    try:
        nb = ensure_notebook_access(nb_id)
        documents = selected_documents(nb, data)
    except (KeyError, PermissionError) as e:
        return error_response(e, 404 if isinstance(e, KeyError) else 403)
    except ValueError as e:
        return error_response(e)

    if not documents:
        return error_response("Notebook chưa có tài liệu nào.")

    try:
        text = llm_client.summarize_documents(
            documents,
            custom_instructions=custom_instructions,
            runtime_config=runtime_ai_config(),
        )
    except llm_client.NotConfiguredError as e:
        return error_response(e, 400)
    except Exception as e:
        return error_response(f"Lỗi gọi Gemini API: {e}", 502)

    _record_usage(json.dumps(data, ensure_ascii=False), text)
    return jsonify({"summary": text})


# ---------- Quiz / Flashcard ----------


@app.route("/api/notebooks/<nb_id>/quiz", methods=["POST"])
@login_required
def quiz(nb_id):
    data = request.get_json(force=True) if request.data else {}
    n_questions = max(1, min(20, int(data.get("n_questions", 6))))
    difficulty = data.get("difficulty", "medium")
    topic = (data.get("topic") or "").strip()
    custom_instructions = storage.get_custom_instructions(current_user()["id"])  # theo từng tài khoản, không lấy từ client

    try:
        nb = ensure_notebook_access(nb_id)
        documents = selected_documents(nb, data)
    except (KeyError, PermissionError) as e:
        return error_response(e, 404 if isinstance(e, KeyError) else 403)
    except ValueError as e:
        return error_response(e)

    if not documents:
        return error_response("Notebook chưa có tài liệu nào.")

    try:
        questions = llm_client.generate_quiz(
            documents,
            n_questions=n_questions,
            difficulty=difficulty,
            topic=topic,
            custom_instructions=custom_instructions,
            runtime_config=runtime_ai_config(),
        )
    except llm_client.NotConfiguredError as e:
        return error_response(e, 400)
    except Exception as e:
        return error_response(f"Lỗi gọi Gemini API hoặc phân tích JSON: {e}", 502)

    _record_usage(json.dumps(data, ensure_ascii=False), json.dumps(questions, ensure_ascii=False))
    return jsonify({"questions": questions})


@app.route("/api/notebooks/<nb_id>/mindmap", methods=["POST"])
@login_required
def mindmap(nb_id):
    data = request.get_json(force=True) if request.data else {}
    topic = (data.get("topic") or "").strip()
    custom_instructions = storage.get_custom_instructions(current_user()["id"])  # theo từng tài khoản, không lấy từ client
    try:
        nb = ensure_notebook_access(nb_id)
        documents = selected_documents(nb, data)
    except (KeyError, PermissionError) as e:
        return error_response(e, 404 if isinstance(e, KeyError) else 403)
    except ValueError as e:
        return error_response(e)
    if not documents:
        return error_response("Notebook chưa có tài liệu nào.")
    try:
        result = llm_client.generate_mindmap(documents, topic=topic, custom_instructions=custom_instructions, runtime_config=runtime_ai_config())
        _record_usage(json.dumps(data, ensure_ascii=False), json.dumps(result, ensure_ascii=False))
        return jsonify(result)
    except llm_client.NotConfiguredError as e:
        return error_response(e, 400)
    except Exception as e:
        return error_response(f"Lỗi tạo mind map: {e}", 502)


@app.route("/api/notebooks/<nb_id>/flashcards", methods=["POST"])
@login_required
def flashcards(nb_id):
    data = request.get_json(force=True) if request.data else {}
    topic = (data.get("topic") or "").strip()
    n_cards = max(2, min(30, int(data.get("n_cards", 10))))
    custom_instructions = storage.get_custom_instructions(current_user()["id"])  # theo từng tài khoản, không lấy từ client
    try:
        nb = ensure_notebook_access(nb_id)
        documents = selected_documents(nb, data)
    except (KeyError, PermissionError) as e:
        return error_response(e, 404 if isinstance(e, KeyError) else 403)
    except ValueError as e:
        return error_response(e)
    if not documents:
        return error_response("Notebook chưa có tài liệu nào.")
    try:
        cards = llm_client.generate_flashcards(documents, n_cards=n_cards, topic=topic, custom_instructions=custom_instructions, runtime_config=runtime_ai_config())
        _record_usage(json.dumps(data, ensure_ascii=False), json.dumps(cards, ensure_ascii=False))
        return jsonify({"cards": cards})
    except llm_client.NotConfiguredError as e:
        return error_response(e, 400)
    except Exception as e:
        return error_response(f"Lỗi tạo flashcards: {e}", 502)


# ---------- Audio overview (podcast 2 người dẫn) ----------


@app.route("/api/notebooks/<nb_id>/audio", methods=["POST"])
@login_required
def create_audio(nb_id):
    data = request.get_json(force=True) if request.data else {}
    custom_instructions = storage.get_custom_instructions(current_user()["id"])  # theo từng tài khoản, không lấy từ client
    try:
        nb = ensure_notebook_access(nb_id)
        documents = selected_documents(nb, data)
    except (KeyError, PermissionError) as e: 
        return error_response(e, 404 if isinstance(e, KeyError) else 403)
    except ValueError as e:
        return error_response(e)

    if not documents:
        return error_response("Notebook chưa có tài liệu nào.")

    try:
        turns = llm_client.generate_podcast_script(documents, custom_instructions=custom_instructions, runtime_config=runtime_ai_config())
    except llm_client.NotConfiguredError as e:
        return error_response(e, 400)
    except Exception as e:
        return error_response(f"Lỗi gọi Gemini API hoặc phân tích JSON: {e}", 502)

    try:
        path = audio.generate_podcast_audio(turns, storage.AUDIO_DIR, nb_id)
    except Exception as e:
        return error_response(f"Lỗi tạo audio (TTS): {e}", 500)

    _record_usage(json.dumps(data, ensure_ascii=False), json.dumps(turns, ensure_ascii=False))
    filename = os.path.basename(path)
    return jsonify({"turns": turns, "audio_url": f"/api/audio/{filename}"})


@app.route("/api/audio/<filename>")
@login_required
def get_audio(filename):
    # Tên file có dạng "{notebook_id}_{random}.wav" (xem audio.generate_podcast_audio).
    # Trước đây route này chỉ yêu cầu đăng nhập mà KHÔNG kiểm tra người dùng có
    # thuộc notebook đó không — user A có thể nghe được audio của user B nếu
    # đoán/biết được tên file. Giờ bắt buộc phải có quyền truy cập notebook
    # tương ứng, giống mọi endpoint khác của notebook.
    nb_id = filename.split("_", 1)[0]
    try:
        ensure_notebook_access(nb_id)
    except (KeyError, PermissionError) as e:
        return error_response(e, 404 if isinstance(e, KeyError) else 403)
    return send_from_directory(storage.AUDIO_DIR, filename)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"\n NotebookLM-clone đang chạy tại cổng: {port}")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
