"""ShipMail local application; Python standard library only."""
import argparse
import hashlib
import csv
import io
import json
import os
import re
import secrets
import socket
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from checks import segments, compare, cautions, rule_translations, normalize_term, restore_abbreviations, REQUEST_EN
from model import Call, ModelError, RUNTIME_NAMES, ensure_local, generate, request, runtime_status, validate_settings
from store import Store, FIELDS, RUNTIMES, export_csv

ROOT = Path(__file__).resolve().parent

def code_version():
    """Fingerprint of the Python code on disk. Screens are served fresh from disk, but Python code only changes on restart."""
    digest = hashlib.sha1()
    for name in ('app.py', 'model.py', 'checks.py', 'store.py', 'seed.py'):
        try:
            digest.update((ROOT / name).read_bytes())
        except OSError:
            pass
    return digest.hexdigest()[:12]

RUNNING_VERSION = code_version()
MAX_BODY = 8_000_000

def text_input(data, key, limit=12000):
    value = data.get(key, '')
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f'{key}: 최대 {limit:,}자입니다. 내용을 나누어 처리하세요. 입력을 자동으로 자르지 않습니다.')
    return value

# Qwen models occasionally drift into Chinese characters inside Korean output (seen once in evaluation: "添付된").
HAN = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')

# Three or more English function words inside the Korean result = part of the sentence was left untranslated
# (catches mixed output such as "shall be 변경 from DOL to").
UNTRANSLATED_WORDS = re.compile(r'\b(?:shall|should|must|will|would|could|be|is|are|was|were|been|the|from|to|of|for|with|and|or|that|this|which|please|changed|required|provided)\b', re.I)
ENGLISH_FIELD = re.compile(r'"english"\s*:\s*"((?:[^"\\]|\\.)*)')
HANGUL_TEXT = re.compile(r'[\uac00-\ud7a3]')
KOREAN_FIELD = re.compile(r'"korean"\s*:\s*"((?:[^"\\]|\\.)*)"')

def untranslated(text):
    return len(UNTRANSLATED_WORDS.findall(text)) >= 3

def term_notes(glossary, source, target):
    """Reviewed glossary check: a term found in the source should appear (as its pair or an alias) in the result."""
    notes, src, dst = [], normalize_term(source), normalize_term(target)
    for english, korean, aliases in glossary:
        for have, want in ((english, [korean, *aliases]), (korean, [english, *aliases])):
            if have and normalize_term(have) in src and not any(normalize_term(w) in dst for w in want if w):
                notes.append(f'용어집 확인: "{have}" → "{want[0]}" 표현이 결과에 없습니다.')
    return notes

class App:
    def __init__(self, path):
        self.db = Store(path)
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.job = None
        self.memo = {}  # (model, glossary) + sentence -> Korean, this session only (not written to disk)
        self.warmed = 0.0

    def warm(self):
        """Load the selected model in the background so the first request does not wait for loading."""
        if time.monotonic() - self.warmed < 60:
            return
        self.warmed = time.monotonic()
        def load():
            try:
                settings = validate_settings(self.db.settings())
                if settings['model'] and settings['runtime'] == 'ollama' and not (self.job and self.job['status'] == 'running'):
                    request(settings, '/api/generate', {'model': settings['model'], 'prompt': '', 'keep_alive': '30m', 'options': {'num_ctx': settings['context_size']}}, timeout=180)
            except (ModelError, ValueError, OSError):
                pass
        threading.Thread(target=load, daemon=True).start()

    def start(self, data):
        kind = data.get('kind')
        if kind not in ('translate', 'reply', 'back'):
            raise ValueError('작업 종류 오류')
        clean = {key: text_input(data, key, limit) for key, limit in [('original', 12000), ('context', 1500), ('korean', 2000), ('english', 3000)]}
        if not clean[{'translate': 'original', 'reply': 'korean', 'back': 'english'}[kind]].strip():
            raise ValueError('처리할 내용을 입력하세요.')
        settings = validate_settings(self.db.settings())
        if kind == 'reply' and len(clean['original']) + len(clean['context']) + len(clean['korean']) > 4500:
            raise ValueError('회신 문맥과 한국어 답변 합계는 4,500자 이내로 나누어 주세요.')
        if kind == 'translate' and any(len(s['text']) > 1800 for s in segments(clean['original'])):
            raise ValueError('한 문장/문단이 1,800자를 넘습니다. 줄바꿈을 추가하여 나누어 주세요.')
        with self.lock:
            if self.job and self.job['status'] == 'running':
                raise ValueError('현재 작업이 끝나거나 취소된 후 다시 실행하세요.')
            job = {'id': secrets.token_hex(12), 'status': 'running', 'progress': '로컬 모델 확인 중', 'started': time.monotonic(), 'result': None, 'error': '', 'call': Call()}
            self.job = job  # Retain only the latest job, in memory.
        threading.Thread(target=self.run, args=(job, kind, clean, settings), daemon=True).start()
        return {'id': job['id']}

    def bounded_refs(self, text):
        # Bound reference context independently of user-controlled DB field sizes.
        selected, size = [], 0
        for r in self.db.references(text):
            r = {k: v for k, v in r.items() if k not in ('id', 'updated')}
            length = len(json.dumps(r, ensure_ascii=False))
            if size + length <= 1600:
                selected.append(r)
                size += length
        return selected

    def finish_segment(self, item, glossary):
        if item['source'] == 'rule':
            notes = ['인사말·맺음말·서명: 규칙으로 처리(AI 미사용)']
        else:
            notes = cautions(item['text']) + term_notes(glossary, item['text'], item['korean'])
            if untranslated(item['korean']):
                notes.append('해석에 번역되지 않은 영어가 남아 있습니다. 해당 부분을 확인해 고치세요.')
            if HAN.search(item['korean']) and not HAN.search(item['text']):
                notes.append('해석에 한자·중국어 문자가 섞였습니다(모델 오류 가능). 해당 부분을 확인해 고치세요.')
            if item['source'] == 'library':
                notes.insert(0, '자료실에 저장된 해석을 그대로 사용(AI 미사용·즉시)')
            elif item['source'] == 'cache':
                notes.insert(0, '같은 문장의 이전 해석 재사용(AI 미사용·즉시)')
        item.update(rule=item['source'] == 'rule', cautions=notes, check=compare(item['text'], item['korean']))
        return item

    def run(self, job, kind, data, settings):
        try:
            caps = ensure_local(settings) or []
            public_settings = settings
            settings = {**settings, '_caps': caps}
            glossary = self.db.glossary()
            soft_stop = False  # cancelled/failed during an optional final step: keep what is already done
            if kind == 'translate':
                source = segments(data['original'])
                fixed = rule_translations(source)
                library = self.db.reviewed_translations()
                gkey = (settings['model'], hash(tuple((e, k, tuple(a)) for e, k, a in glossary)))
                parts = []
                for s in source:
                    item = {**s, 'korean': None, 'source': 'ai'}
                    norm = normalize_term(s['text'])
                    if s['id'] in fixed:
                        item.update(korean=fixed[s['id']], source='rule')
                    elif norm in library:
                        item.update(korean=library[norm], source='library')
                    elif (gkey, norm) in self.memo:
                        item.update(korean=self.memo[(gkey, norm)], source='cache')
                    parts.append(self.finish_segment(item, glossary) if item['korean'] is not None else item)
                todo = [p for p in parts if p['korean'] is None]
                # Partial results are exposed so the screen fills in as each sentence streams out of the model.
                job['partial'] = {'segments': parts, 'stage': 'sentences'}
                result = {'segments': parts, 'requests': [], 'conditions': [], 'uncertainties': []}
                body = '\n'.join(p['text'] for p in parts if p['source'] != 'rule').strip()
                skey = (gkey, 'summary', normalize_term(body + '\n' + data['context']))
                refs = self.bounded_refs('\n'.join(p['text'] for p in todo)) if todo else []
                # Whole-mail batches keep quality: measured single-sentence requests left English untranslated.
                chunks, chunk, length = [], [], 0
                for seg in todo:
                    if chunk and length + len(seg['text']) > 1600:
                        chunks.append(chunk)
                        chunk, length = [], 0
                    chunk.append(seg)
                    length += len(seg['text'])
                if chunk:
                    chunks.append(chunk)
                def progress():
                    done = sum(p['korean'] is not None for p in todo)
                    if todo and done == len(todo):
                        job['progress'] = '해석 완료 · 요청·조건 요약 작성 중 ([요약 건너뛰기]를 누르면 해석만 남깁니다)'
                        job['partial'] = {'segments': parts, 'stage': 'summary'}
                    else:
                        job['progress'] = f'문장 해석 {done}/{len(todo)} · 끝난 문장부터 화면에 표시' + (f' · 즉시 처리 {len(parts)-len(todo)}개' if len(parts) > len(todo) else '')
                progress()
                for index, chunk in enumerate(chunks):
                    def on_text(text, chunk=chunk):
                        for item, raw in zip(chunk, KOREAN_FIELD.findall(text)):
                            if item['korean'] is None:
                                korean = json.loads('"' + raw + '"')
                                if korean.strip():
                                    item['korean'] = korean
                                    self.finish_segment(item, glossary)
                        progress()
                    context = {'segments': [{'id': s['id'], 'text': s['text']} for s in chunk], 'previous_context': data['context'],
                               'adjacent_before': chunks[index-1][-1]['text'] if index else '', 'adjacent_after': chunks[index+1][0]['text'] if index + 1 < len(chunks) else '',
                               'reviewed_references': refs}
                    try:
                        translated, _ = generate(settings, kind, context, job['call'], [s['id'] for s in chunk], on_text=on_text)
                    except ModelError:
                        # Cancel pressed while only the summary lists were still being written: keep the translations.
                        if not (job['call'].cancelled.is_set() and index == len(chunks) - 1 and all(p['korean'] is not None for p in todo)):
                            raise
                        soft_stop = True
                        result['uncertainties'] = ['요약을 건너뛰었습니다. 문장별 해석은 완료되었습니다.']
                        break
                    for item, t in zip(chunk, translated['segments']):
                        item['korean'] = t['korean']
                        if len(self.memo) > 3000:
                            self.memo.clear()
                        self.memo[(gkey, normalize_term(item['text']))] = t['korean']
                        self.finish_segment(item, glossary)
                    for key in ('requests', 'conditions', 'uncertainties'):
                        result[key].extend(translated[key])
                if soft_stop:
                    pass
                elif todo and len(todo) == sum(p['source'] != 'rule' for p in parts):
                    self.memo[skey] = {k: result[k] for k in ('requests', 'conditions', 'uncertainties')}
                elif body:
                    # Some sentences came from the library/cache: summarize the whole body (reused on re-runs).
                    job['partial'] = {'segments': parts, 'stage': 'summary'}
                    job['progress'] = '해석 완료 · 요청·조건 요약 중 (해석은 먼저 확인하세요)'
                    try:
                        if skey not in self.memo:
                            self.memo[skey], _ = generate(settings, 'summary', {'original': body, 'previous_mail_context': data['context']}, job['call'])
                        result.update(self.memo[skey])
                    except ModelError as error:
                        soft_stop = True
                        result['uncertainties'] = ['요약을 ' + ('취소했습니다.' if job['call'].cancelled.is_set() else '만들지 못했습니다: ' + str(error)) + ' 문장별 해석은 완료되었습니다.']
                refs = [None] * len(refs)
                result['check'] = compare(data['original'], '\n'.join(p['korean'] for p in parts))
            elif kind == 'reply':
                refs = self.bounded_refs(data['original'] + '\n' + data['korean'])
                job['progress'] = '영어 회신 작성 중'
                # The received mail is not given to the writer step, so its sentences cannot leak into the reply.
                def on_reply_text(text):
                    # Show the English body while it is being written (JSON key "english" streams first).
                    m = ENGLISH_FIELD.search(text)
                    if m:
                        try:
                            draft = json.loads('"' + m.group(1).rstrip('\\') + '"')
                        except ValueError:
                            return
                        job['partial'] = {'reply_draft': draft}
                result, _ = generate(settings, 'reply', {'korean': data['korean'], 'reviewed_references': refs}, job['call'], on_text=on_reply_text)
                result['english'] = restore_abbreviations(data['korean'], result['english'])
                # Check items are meant for the Korean-speaking user; drop items the model wrote in English.
                result['uncertainties'] = [u for u in result['uncertainties'] if HANGUL_TEXT.search(u)]
                # A duplicated "Subject:" line is removed; placeholders are only flagged, never filled in.
                result['english'] = re.sub(r'\A\s*subject:[^\n]*\n+', '', result['english'], flags=re.I).strip()
                # Some models echo the field description instead of writing subjects; drop those.
                echo = re.compile(r'\s*(?:an?\s+)?(?:(?:short|concise)\s+)?(?:english\s+)?subject(?:\s+line)?s?(?:\s+in\s+english)?\s*\d*\s*', re.I)
                result['subjects'] = [x for x in result.pop('subjects') if not echo.fullmatch(x)]
                result['subject'] = result['subjects'][0] if result['subjects'] else ''
                if not result['subjects']:
                    result['uncertainties'].append('제목이 생성되지 않았습니다. 직접 입력하세요.')
                # "as requested / as mentioned" asserts something the user did not write (e.g. that the reader asked for it): drop it.
                if not re.search(r'요청하신|요청에\s*따라|말씀하신|언급하신|말씀드린|언급한', data['korean']):
                    result['english'] = re.sub(r',?\s+as\s+(?:requested|mentioned|discussed|previously\s+mentioned)(?=[\s.,;])', '', result['english'], flags=re.I)
                if re.search(r'\[[^\]\n]{1,40}\]', result['english']):
                    result['uncertainties'].append('영문에 [ ] 자리표시자가 있습니다. 직접 수정하거나 삭제하세요.')
                result['check'] = compare(data['korean'], result['english'])
                result['uncertainties'].extend(term_notes(glossary, data['korean'], result['english']))
                if settings['signature'].strip():
                    result['english'] += '\n\n' + settings['signature'].strip()
                result['unanswered'] = []
                # Show the reply now; the unanswered-items check follows.
                job['partial'] = {'reply': dict(result)}
                if data['original'].strip():
                    job['progress'] = '영어 회신 완료 · 받은 메일 중 미답변 항목 확인 중'
                    try:
                        gaps, _ = generate(settings, 'gaps', {'original': data['original'], 'context': data['context'], 'korean': data['korean']}, job['call'])
                        # Keep only items that are requests/questions (drops plain statements and instructions quoted from the mail).
                        result['unanswered'] = [u for u in gaps['unanswered'] if HANGUL_TEXT.search(u) or REQUEST_EN.search(u) or '?' in u or re.search(r'\b(?:advise|confirm|indicate|send|submit|provide|inform)\b', u, re.I)]
                    except ModelError as error:
                        soft_stop = True
                        result['uncertainties'].append('미답변 항목 확인을 ' + ('취소했습니다.' if job['call'].cancelled.is_set() else '하지 못했습니다: ' + str(error)))
            else:
                refs = self.bounded_refs(data['english'])
                job['progress'] = '수정한 영어의 한국어 뜻 확인 중'
                result, _ = generate(settings, kind, {'english': data['english'], 'reviewed_references': refs}, job['call'])
            if job['call'].cancelled.is_set() and not soft_stop:
                raise ModelError('작업을 취소했습니다.')
            result['seconds'] = round(time.monotonic()-job['started'], 2)
            result['model'] = settings['model']
            result['settings'] = public_settings
            result['reference_count'] = len(refs)
            job['result'] = result
            job['status'] = 'done'
        except (ModelError, ValueError) as error:
            job['error'] = str(error)
            job['status'] = 'cancelled' if job['call'].cancelled.is_set() else 'error'
        except Exception:
            # Never log prompts, mail, raw runtime errors or reasoning.
            job['error'] = '처리를 완료하지 못했습니다. 입력은 유지됩니다. 로컬 런타임 상태를 확인 후 재시도하세요.'
            job['status'] = 'error'

    def status(self):
        settings = self.db.settings()
        name = RUNTIME_NAMES.get(settings.get('runtime'), '로컬 런타임')
        try:
            return {'connected': True, 'runtime': name, **runtime_status(settings)}
        except (ModelError, ValueError):
            return {'connected': False, 'runtime': name, 'models': [], 'processes': [], 'error': f'{name} 연결 안 됨 · 설치 후 로컬 서버를 실행하세요.'}

class Handler(BaseHTTPRequestHandler):
    server_version = 'ShipMail/1.0'

    def log_message(self, *args):
        pass

    @property
    def app(self):
        return self.server.app

    def respond(self, value, status=200, content_type='application/json; charset=utf-8'):
        body = json.dumps(value, ensure_ascii=False).encode() if content_type.startswith('application/json') else (value.encode() if isinstance(value, str) else value)
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def guard(self, mutate=False):
        port = self.server.server_port
        hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
        host = self.headers.get('Host', '')
        if host not in hosts:
            raise PermissionError('Host 차단')
        origin = self.headers.get('Origin')
        if origin and origin != 'http://' + host:
            raise PermissionError('Origin 차단')
        if self.headers.get('Sec-Fetch-Site') == 'cross-site':
            raise PermissionError('외부 페이지 접근 차단')
        if mutate and (self.headers.get('X-ShipMail-Token') != self.app.token or self.headers.get_content_type() != 'application/json'):
            raise PermissionError('요청 보호 토큰/형식 오류. 앱 화면을 새로고침하세요.')

    def do_GET(self):
        try:
            self.guard()
            parsed = urlsplit(self.path)
            path, query = parsed.path, parse_qs(parsed.query)
            if path == '/api/bootstrap':
                self.app.warm()
                return self.respond({'token': self.app.token, 'settings': self.app.db.settings(), 'fields': FIELDS, 'runtimes': RUNTIMES,
                                     'version': RUNNING_VERSION, 'disk_version': code_version()})
            if path == '/api/status':
                return self.respond(self.app.status())
            if path == '/api/job':
                job = self.app.job
                if not job or query.get('id', [''])[0] != job['id']:
                    raise ValueError('작업을 찾을 수 없습니다.')
                return self.respond({k: v for k, v in job.items() if k not in ('call', 'started')})
            if path == '/api/records':
                return self.respond(self.app.db.list(query.get('kind', ['terms'])[0], query.get('q', [''])[0]))
            if path == '/api/export':
                kind = query.get('kind', ['terms'])[0]
                rows = self.app.db.list(kind)
                if query.get('format', ['json'])[0] == 'csv':
                    return self.respond(export_csv(kind, rows), content_type='text/csv; charset=utf-8')
                return self.respond(rows)
            files = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'application/javascript'), '/style.css': ('style.css', 'text/css')}
            if path in files:
                file, mime = files[path]
                return self.respond((ROOT / 'static' / file).read_bytes(), content_type=mime + '; charset=utf-8')
            self.respond({'error': '찾을 수 없습니다.'}, 404)
        except PermissionError as e:
            self.respond({'error': str(e)}, 403)
        except (ValueError, KeyError) as e:
            self.respond({'error': str(e)}, 400)
        except Exception:
            self.respond({'error': '로컬 데이터를 읽지 못했습니다.'}, 500)

    def do_POST(self):
        try:
            self.guard(True)
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= MAX_BODY:
                raise ValueError('파일/요청은 8MB 이내여야 합니다.')
            self.connection.settimeout(10)
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('JSON 객체가 필요합니다.')
            path = urlsplit(self.path).path
            if path == '/api/settings':
                result = self.app.db.settings(validate_settings(data))
                self.app.warmed = 0.0
                self.app.warm()
            elif path == '/api/start':
                result = self.app.start(data)
            elif path == '/api/cancel':
                job = self.app.job
                if job and job['id'] == data.get('id') and job['status'] == 'running':
                    job['call'].cancel()
                    job['progress'] = '취소 처리 중 · 런타임 요청 종료 대기'
                result = {'ok': True}
            elif path == '/api/clear-job':
                with self.app.lock:
                    if self.app.job and self.app.job['status'] == 'running':
                        raise ValueError('먼저 실행 중인 작업을 취소하세요.')
                    self.app.job = None
                result = {'ok': True}
            elif path == '/api/compare':
                result = {'segments': segments(text_input(data, 'source', 60000)), 'check': compare(text_input(data, 'source', 60000), text_input(data, 'target', 60000))}
            elif path == '/api/save':
                result = {'id': self.app.db.save(data['kind'], data['record'], data.get('id'))}
            elif path == '/api/learn':
                if not self.app.db.settings().get('auto_learn'):
                    raise ValueError('설정에서 "수정 내용 자료실 자동 저장"이 꺼져 있습니다.')
                result = self.app.db.learn(data['kind'], data['record'], data['key'])
            elif path == '/api/unlearn':
                self.app.db.unlearn(data['kind'], int(data['id']), data.get('previous'))
                result = {'ok': True}
            elif path == '/api/delete':
                self.app.db.delete(data['kind'], data['id'])
                result = {'ok': True}
            elif path == '/api/import-preview' or path == '/api/import':
                rows = data.get('rows')
                if 'csv' in data:
                    rows = list(csv.DictReader(io.StringIO(text_input(data, 'csv', MAX_BODY).lstrip('\ufeff'))))
                if path.endswith('preview'):
                    result = self.app.db.preview_import(data['kind'], rows)
                else:
                    result = {'count': self.app.db.import_rows(data['kind'], rows, data['mode'])}
            elif path == '/api/backup':
                self.app.db.backup()
                result = self.app.db.snapshot()
            elif path == '/api/restore':
                result = {'backup': self.app.db.restore(data['snapshot'], validate_settings)}
            else:
                return self.respond({'error': '찾을 수 없습니다.'}, 404)
            self.respond(result)
        except PermissionError as e:
            self.respond({'error': str(e)}, 403)
        except (ValueError, KeyError, TypeError) as e:
            self.respond({'error': str(e) if isinstance(e, ValueError) else '필수 필드/자료형을 확인하세요.'}, 400)
        except Exception:
            self.respond({'error': '작업에 실패했습니다. DB 쓰기 권한과 파일 상태를 확인하세요.'}, 500)

class ExclusiveServer(ThreadingHTTPServer):
    # HTTPServer enables SO_REUSEADDR, which on Windows lets a second ShipMail bind the same port
    # and split requests between two apps (tokens and jobs then go missing). Require exclusive use.
    allow_reuse_address = False
    allow_reuse_port = False

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

def make_server(path, port=8765):
    server = ExclusiveServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    server.app = App(path)
    return server

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    try:
        server = make_server(ROOT / 'data' / 'shipmail.sqlite3', args.port)
    except OSError:
        # Most often ShipMail is already running: show that window instead of starting a second copy.
        print(f'ShipMail이 이미 실행 중이거나 포트 {args.port}을(를) 쓸 수 없습니다. 이미 열린 ShipMail 화면을 사용하세요.')
        if not args.no_browser:
            webbrowser.open(f'http://127.0.0.1:{args.port}')
        raise SystemExit(1)
    print(f'ShipMail: http://127.0.0.1:{server.server_port}  |  Stop: Ctrl+C')
    if not args.no_browser:
        webbrowser.open(f'http://127.0.0.1:{server.server_port}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        if server.app.job:
            server.app.job['call'].cancel()
    finally:
        server.server_close()
