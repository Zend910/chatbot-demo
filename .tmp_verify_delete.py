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

user = storage.register_user('legacy', 'pass123')
nb = storage.create_notebook('Legacy NB', user_id=user['id'])
db = storage._load()
db['notebooks'][nb['id']]['studio_items'] = [{'type': 'summary', 'title': 'Legacy summary', 'content': 'old content', 'created_at': storage._now()}]
storage._save(db)
nb2 = storage.get_notebook(nb['id'], user_id=user['id'])
assert nb2['studio_items'][0].get('id')
storage.delete_studio_item(nb['id'], nb2['studio_items'][0]['id'], user_id=user['id'])
assert storage.get_notebook(nb['id'], user_id=user['id'])['studio_items'] == []

with app.test_client() as c:
    with c.session_transaction() as s:
        s['user_id'] = user['id']
    nb3 = storage.create_notebook('AJAX NB', user_id=user['id'])
    item = storage.add_studio_item(nb3['id'], {'type': 'quiz', 'title': 'Quiz 1', 'content': {'questions': []}, 'created_at': storage._now()}, user_id=user['id'])
    r = c.delete('/api/notebooks/' + nb3['id'] + '/studio/' + item['id'])
    print('status=', r.status_code)
    print('json=', r.get_json())
    print('remaining=', len(storage.get_notebook(nb3['id'], user_id=user['id'])['studio_items']))
    assert r.status_code == 200
    assert r.get_json()['ok'] is True
    assert len(storage.get_notebook(nb3['id'], user_id=user['id'])['studio_items']) == 0
