import os, tempfile
import storage
from app import app

tmp = tempfile.mkdtemp()
storage.DATA_DIR = tmp
storage.DB_PATH = os.path.join(tmp, 'notebooks.json')
storage.UPLOAD_DIR = os.path.join(tmp, 'uploads')
storage.AUDIO_DIR = os.path.join(tmp, 'audio')
os.makedirs(storage.UPLOAD_DIR, exist_ok=True)
os.makedirs(storage.AUDIO_DIR, exist_ok=True)
storage._save({'notebooks': {}, 'users': {}})

user = storage.register_user('deltest', '123456')
nb = storage.create_notebook('Delete Test', user_id=user['id'])
item = storage.add_studio_item(nb['id'], {'type': 'summary', 'title': 'Summary test', 'content': 'hello', 'created_at': storage._now()}, user_id=user['id'])
with app.test_client() as c:
    with c.session_transaction() as s:
        s['user_id'] = user['id']
    r = c.delete('/api/notebooks/' + nb['id'] + '/studio/' + item['id'])
    print('status=', r.status_code)
    print('json=', r.get_json())
    print('remaining=', len(storage.get_notebook(nb['id'], user_id=user['id'])['studio_items']))
    assert r.status_code == 200
    assert r.get_json()['ok'] is True
    assert len(storage.get_notebook(nb['id'], user_id=user['id'])['studio_items']) == 0
