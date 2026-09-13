import os
import tempfile
import unittest
from unittest.mock import patch

from app import app
import storage


class AuthStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        storage.DATA_DIR = self.tmp_dir
        storage.DB_PATH = os.path.join(self.tmp_dir, "notebooks.json")
        storage.UPLOAD_DIR = os.path.join(self.tmp_dir, "uploads")
        storage.AUDIO_DIR = os.path.join(self.tmp_dir, "audio")
        os.makedirs(storage.UPLOAD_DIR, exist_ok=True)
        os.makedirs(storage.AUDIO_DIR, exist_ok=True)
        storage._save({"notebooks": {}, "users": {}})

    def test_register_and_verify_user(self):
        user = storage.register_user("alice", "secret123")
        self.assertEqual(user["username"], "alice")
        self.assertEqual(user["role"], "user")
        self.assertTrue(storage.verify_user("alice", "secret123"))
        self.assertFalse(storage.verify_user("alice", "wrongpass"))

    def test_create_notebook_binds_user(self):
        user = storage.register_user("bob", "pass123")
        nb = storage.create_notebook("Notebook A", user_id=user["id"])
        self.assertEqual(nb["user_id"], user["id"])
        self.assertEqual(storage.list_notebooks_for_user(user["id"])[0]["id"], nb["id"])

    def test_admin_can_access_all_notebooks(self):
        admin = storage.register_user("admin", "admin123", role="admin")
        user = storage.register_user("charlie", "pass123")
        nb = storage.create_notebook("Notebook của Charlie", user_id=user["id"])

        self.assertEqual(storage.get_notebook(nb["id"], user_id=admin["id"], role="admin")["id"], nb["id"])
        self.assertEqual(storage.list_notebooks_for_user(admin["id"], role="admin")[0]["id"], nb["id"])

    def test_admin_can_read_chunks_and_append_chat_for_any_notebook(self):
        admin = storage.register_user("admin", "admin123", role="admin")
        user = storage.register_user("charlie", "pass123")
        nb = storage.create_notebook("Notebook của Charlie", user_id=user["id"])
        storage.add_document(nb["id"], {"id": "d1", "name": "doc.txt", "source_type": "txt", "chunks": [{"id": "c1", "text": "Nội dung thử", "position": "Trang 1"}]}, user_id=user["id"])

        chunks = storage.all_chunks(nb["id"], user_id=admin["id"], role="admin")
        self.assertEqual(chunks[0]["doc_name"], "doc.txt")

        storage.append_chat(nb["id"], "user", "Câu hỏi thử", user_id=admin["id"], nb_role="admin")
        self.assertTrue(storage.get_notebook(nb["id"], user_id=admin["id"], role="admin")["chat_history"])

    def test_admin_create_notebook_accepts_user_id_alias(self):
        admin = storage.register_user("admin2", "admin123", role="admin")
        user = storage.register_user("dora", "pass123")

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = admin["id"]

            response = client.post("/api/admin/notebooks", json={"name": "Notebook cho Dora", "userId": user["id"]})
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
            payload = response.get_json()
            self.assertEqual(payload["notebook"]["user_id"], user["id"])

    def test_delete_legacy_studio_item_without_id(self):
        user = storage.register_user("legacy", "pass123")
        nb = storage.create_notebook("Notebook legacy", user_id=user["id"])
        legacy_item = {"type": "summary", "title": "Legacy summary", "content": "old content", "created_at": storage._now()}
        db = storage._load()
        db["notebooks"][nb["id"]]["studio_items"] = [legacy_item]
        storage._save(db)

        nb_loaded = storage.get_notebook(nb["id"], user_id=user["id"])
        self.assertIn("id", nb_loaded["studio_items"][0])

        storage.delete_studio_item(nb["id"], nb_loaded["studio_items"][0]["id"], user_id=user["id"])
        self.assertEqual(storage.get_notebook(nb["id"], user_id=user["id"])["studio_items"], [])

    def test_chat_forwards_custom_instructions_to_ai(self):
        user = storage.register_user("customuser", "pass123")
        nb = storage.create_notebook("Notebook custom", user_id=user["id"])
        storage.add_document(
            nb["id"],
            {"id": "d1", "name": "doc.txt", "source_type": "txt", "chunks": [{"id": "c1", "text": "Nội dung mẫu", "position": "Trang 1"}]},
            user_id=user["id"],
        )

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = user["id"]

            with patch("llm_client.answer_question", return_value={"answer": "Trả lời mẫu", "citations": []}) as mock_answer:
                response = client.post(
                    f"/api/notebooks/{nb['id']}/chat",
                    json={"question": "Nội dung gì?", "custom_instructions": "Trả lời ngắn gọn"},
                )

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(mock_answer.call_args.kwargs["custom_instructions"], "Trả lời ngắn gọn")


if __name__ == "__main__":
    unittest.main()
