"""Versioned local database. No mail is written by inference."""
import csv
import io
import json
import sqlite3
import threading
import unicodedata
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from pathlib import Path

FIELDS = {
    'terms': ['english', 'korean', 'aliases', 'domain', 'context', 'hull', 'source', 'status'],
    'examples': ['korean', 'english', 'purpose', 'tags', 'source', 'status'],
    'projects': ['name', 'notes'],
    'history': ['name', 'original', 'context', 'analysis', 'korean', 'subject', 'english', 'model', 'settings'],
}
REQUIRED = {'terms': ['english', 'korean'], 'examples': ['korean', 'english'], 'projects': ['name'], 'history': ['name']}
# No model is forced: the user picks an installed local model (see README for evaluated candidates).
DEFAULTS = {'runtime': 'ollama', 'model': '', 'endpoint': 'http://127.0.0.1:11434', 'timeout': 300, 'context_size': 8192, 'signature': '', 'font_size': 16, 'autosave': False, 'auto_learn': True}
RUNTIMES = {'ollama': 'http://127.0.0.1:11434', 'openai': 'http://127.0.0.1:1234'}

def normalize(s):
    return ' '.join(unicodedata.normalize('NFKC', s).casefold().split())

def validate(kind, data):
    if kind not in FIELDS or not isinstance(data, dict):
        raise ValueError('자료 종류/형식이 올바르지 않습니다.')
    if set(data) - set(FIELDS[kind]) - {'id', 'updated'}:
        raise ValueError('허용하지 않는 필드가 있습니다.')
    result = {}
    for key in FIELDS[kind]:
        value = data.get(key, 'draft' if key == 'status' else '')
        if not isinstance(value, str) or len(value) > (60000 if kind == 'history' else 4000):
            raise ValueError('필드 자료형 또는 길이를 확인하세요: ' + key)
        result[key] = value
    if any(not result[key].strip() for key in REQUIRED[kind]):
        raise ValueError('필수 항목이 비어 있습니다.')
    if 'status' in result and result['status'] not in ('draft', 'reviewed'):
        raise ValueError('검토 상태는 draft 또는 reviewed여야 합니다.')
    return result

class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self.connect() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version > 1:
                raise ValueError('더 새로운 DB입니다. 앱을 업데이트하세요.')
            db.executescript('''CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL, updated TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS records_kind ON records(kind);
                CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);
                PRAGMA user_version=1;''')
            fresh = db.execute('SELECT COUNT(*) FROM settings').fetchone()[0] == 0
            if fresh:
                db.execute('INSERT INTO settings VALUES(1,?)', (json.dumps(DEFAULTS),))
        if fresh:
            from seed import records
            for kind, item in records():
                self.save(kind, item)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.execute('PRAGMA secure_delete=ON')
            with db:
                yield db
        finally:
            db.close()

    def settings(self, values=None):
        with self.lock, self.connect() as db:
            current = {**DEFAULTS, **json.loads(db.execute('SELECT payload FROM settings WHERE id=1').fetchone()[0])}
            if values is not None:
                current.update(values)
                db.execute('UPDATE settings SET payload=? WHERE id=1', (json.dumps(current),))
            return current

    def list(self, kind, query=''):
        if kind not in FIELDS:
            raise ValueError('자료 종류가 올바르지 않습니다.')
        with self.lock, self.connect() as db:
            rows = db.execute('SELECT id,payload,updated FROM records WHERE kind=? ORDER BY id DESC', (kind,)).fetchall()
        terms = normalize(query).split()
        return [dict(json.loads(p), id=i, updated=u) for i, p, u in rows if all(t in normalize(p) for t in terms)]

    def save(self, kind, data, record_id=None):
        data = validate(kind, data)
        with self.lock, self.connect() as db:
            now = datetime.now(timezone.utc).isoformat()
            if record_id is None:
                record_id = db.execute('INSERT INTO records(kind,payload,updated) VALUES(?,?,?)', (kind, json.dumps(data, ensure_ascii=False), now)).lastrowid
            elif db.execute('UPDATE records SET payload=?,updated=? WHERE id=? AND kind=?', (json.dumps(data, ensure_ascii=False), now, record_id, kind)).rowcount != 1:
                raise ValueError('자료를 찾을 수 없습니다.')
        return record_id

    def delete(self, kind, record_id):
        with self.lock, self.connect() as db:
            db.execute('DELETE FROM records WHERE kind=? AND id=?', (kind, record_id))

    def references(self, text):
        text = normalize(text)
        out = []
        for kind in ('terms', 'examples'):
            ranked = []
            for row in self.list(kind):
                if row.get('status') != 'reviewed':
                    continue
                keys = [row.get('english', ''), row.get('korean', ''), *row.get('aliases', '').split(',')]
                score = sum(len(normalize(k)) for k in keys if len(normalize(k)) > 1 and normalize(k) in text)
                if not score and kind == 'examples':
                    # Saved corrections also help with similar (not identical) sentences: most words overlap.
                    words = set(text.split())
                    for key in keys[:2]:
                        tokens = [w.strip('.,?!:;()"') for w in normalize(key).split() if len(w.strip('.,?!:;()"')) > 1]
                        if len(tokens) >= 3 and sum(w in words or w in text for w in tokens) / len(tokens) >= 0.6:
                            score = len(tokens)
                if score:
                    ranked.append((score, row))
            out.extend(r for _, r in sorted(ranked, key=lambda v: v[0], reverse=True)[:6])
        return out[:8]

    def learn(self, kind, record, key):
        """Upsert a user correction keyed by one field (e.g. the English source sentence). Returns undo information."""
        if kind not in ('terms', 'examples') or key not in FIELDS[kind]:
            raise ValueError('자동 저장 종류가 올바르지 않습니다.')
        data = validate(kind, record)
        with self.lock:
            existing = next((r for r in self.list(kind) if normalize(r.get(key, '')) == normalize(data[key])), None)
            if existing:
                previous = {k: existing.get(k, '') for k in FIELDS[kind]}
                self.save(kind, data, existing['id'])
                return {'id': existing['id'], 'created': False, 'previous': previous}
            return {'id': self.save(kind, data), 'created': True, 'previous': None}

    def unlearn(self, kind, record_id, previous):
        """Undo learn(): delete a newly created record or restore the overwritten one."""
        if previous is None:
            self.delete(kind, record_id)
        else:
            self.save(kind, previous, record_id)

    def reviewed_translations(self):
        """Exact-sentence translation memory from user-reviewed examples: normalized English -> Korean."""
        return {normalize(r['english']): r['korean'] for r in reversed(self.list('examples')) if r.get('status') == 'reviewed' and r.get('english', '').strip() and r.get('korean', '').strip()}

    def glossary(self):
        """Reviewed terms only: (english, korean, aliases) used for rule-based term checks."""
        return [(r['english'], r['korean'], [a.strip() for a in r.get('aliases', '').split(',') if a.strip()]) for r in self.list('terms') if r.get('status') == 'reviewed']

    def snapshot(self):
        with self.lock:
            return {'version': 1, 'records': {k: self.list(k) for k in FIELDS}, 'settings': self.settings()}

    def backup(self):
        folder = self.path.parent / 'backups'
        folder.mkdir(exist_ok=True)
        target = folder / (datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.sqlite3')
        with self.lock, self.connect() as source, closing(sqlite3.connect(target)) as dest:
            source.backup(dest)
        return target.name

    def restore(self, snapshot, settings_validator):
        if not isinstance(snapshot, dict) or snapshot.get('version') != 1 or set(snapshot.get('records', {})) != set(FIELDS):
            raise ValueError('백업 형식/버전이 올바르지 않습니다.')
        clean = {}
        for kind, rows in snapshot['records'].items():
            if not isinstance(rows, list) or len(rows) > 10000:
                raise ValueError('백업 크기 제한을 초과했습니다.')
            clean[kind] = [validate(kind, r) for r in rows]
        settings = settings_validator(snapshot.get('settings', {}))
        with self.lock:
            name = self.backup()
            with self.connect() as db:
                db.execute('DELETE FROM records')
                for kind, rows in clean.items():
                    for row in rows:
                        db.execute('INSERT INTO records(kind,payload,updated) VALUES(?,?,?)', (kind, json.dumps(row, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))
                db.execute('UPDATE settings SET payload=? WHERE id=1', (json.dumps(settings),))
        return name

    def preview_import(self, kind, rows):
        if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
            raise ValueError('한 번에 1~1000개 자료를 가져올 수 있습니다.')
        clean = [validate(kind, r) for r in rows]
        key = REQUIRED[kind][0]
        known = {normalize(r[key]): r['id'] for r in self.list(kind)}
        result = []
        for row in clean:
            identity = normalize(row[key])
            result.append({'data': row, 'conflict': identity in known, 'existing_id': known.get(identity)})
            known.setdefault(identity, None)
        return result

    def import_rows(self, kind, rows, mode):
        if mode not in ('merge', 'skip'):
            raise ValueError('병합/건너뛰기를 선택하세요.')
        with self.lock:
            self.preview_import(kind, rows)
            count = 0
            key = REQUIRED[kind][0]
            # Single transaction: malformed data cannot leave a partial import.
            with self.connect() as db:
                known = {normalize(r[key]): r['id'] for r in self.list(kind)}
                for raw in rows:
                    row = validate(kind, raw)
                    identity = normalize(row[key])
                    existing = known.get(identity)
                    if existing and mode == 'skip':
                        continue
                    args = (json.dumps(row, ensure_ascii=False), datetime.now(timezone.utc).isoformat())
                    if existing:
                        db.execute('UPDATE records SET payload=?,updated=? WHERE id=?', (*args, existing))
                    else:
                        known[identity] = db.execute('INSERT INTO records(payload,updated,kind) VALUES(?,?,?)', (*args, kind)).lastrowid
                    count += 1
            return count

def export_csv(kind, rows):
    target = io.StringIO(newline='')
    writer = csv.DictWriter(target, fieldnames=FIELDS[kind], extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        writer.writerow({k: ("'" + v if v.lstrip().startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else v) for k, v in row.items() if k in FIELDS[kind]})
    return '\ufeff' + target.getvalue()
