"""Offline self-check: run with the network physically disconnected.

1. Confirms the internet is really unreachable.
2. Starts a temporary ShipMail server (temporary DB; your data/ folder is not touched) and drives it over HTTP:
   translate -> reply -> back-translation -> library CRUD/search -> backup -> restore.
3. Watches for outbound connections from ShipMail and Ollama processes the whole time.
Writes evals/results/offline-check-<time>.txt. Uses only developer-made sample text.
"""
import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from app import make_server
from store import Store

SAMPLE = 'Dear Mr. Kim,\nPlease indicate No.1 DG and No.2 DG separately.\nThe attached Rev.E supersedes Rev.D.'
KOREAN = 'No.1 DG와 No.2 DG를 구분한 도면을 다음 주에 보내드리겠습니다.'
lines, results = [], []

def log(text):
    print(text, flush=True)
    lines.append(text)

def check(name, ok, detail=''):
    results.append(ok)
    log(f"[{'통과' if ok else '실패'}] {name}" + (f' · {detail}' if detail else ''))

def internet_reachable():
    for host, port in (('8.8.8.8', 53), ('1.1.1.1', 443), ('208.67.222.222', 53)):
        try:
            socket.create_connection((host, port), timeout=3).close()
            return True
        except OSError:
            pass
    try:
        socket.getaddrinfo('ollama.com', 443)
        return True
    except OSError:
        return False

def watched_pids():
    out = subprocess.run(['tasklist', '/fo', 'csv', '/nh'], capture_output=True, text=True, errors='replace').stdout
    pids = {os.getpid()}
    for row in out.splitlines():
        parts = [p.strip('"') for p in row.split('","')]
        if len(parts) > 1 and parts[0].lower().startswith('ollama'):
            pids.add(int(parts[1]))
    return pids

def external_connections(pids):
    out = subprocess.run(['netstat', '-ano', '-p', 'tcp'], capture_output=True, text=True, errors='replace').stdout
    found = set()
    for row in out.splitlines():
        cols = row.split()
        if len(cols) == 5 and cols[0] == 'TCP' and cols[4].isdigit() and int(cols[4]) in pids:
            remote = cols[2].rsplit(':', 1)[0].strip('[]')
            if remote not in ('127.0.0.1', '::1', '0.0.0.0', '::', '*') and cols[3] != 'LISTENING':
                found.add(f'{remote} ({cols[3]}, pid {cols[4]})')
    return found

class Client:
    def __init__(self, port):
        self.port, self.token = port, ''
    def call(self, path, data=None, timeout=900):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=timeout)
        headers = {'Content-Type': 'application/json', 'X-ShipMail-Token': self.token} if data is not None else {}
        conn.request('POST' if data is not None else 'GET', path, json.dumps(data) if data is not None else None, headers)
        r = conn.getresponse(); body = r.read(); conn.close()
        return r.status, (json.loads(body) if body.startswith((b'{', b'[')) else body)
    def job(self, payload):
        status, started = self.call('/api/start', payload)
        if status != 200:
            return 'error', started.get('error', ''), None
        t = time.monotonic()
        while True:
            _, j = self.call('/api/job?id=' + started['id'])
            if j['status'] != 'running':
                return j['status'], j.get('error', ''), (j.get('result'), round(time.monotonic() - t, 1))
            time.sleep(0.5)

def main():
    log(f'ShipMail 오프라인 점검 · {datetime.now():%Y-%m-%d %H:%M:%S}')
    online = internet_reachable()
    check('인터넷 차단 상태', not online, '외부 주소 3곳·DNS 모두 연결 실패' if not online else '인터넷이 아직 연결되어 있습니다. 와이파이/랜선을 끊고 다시 실행하세요 (결과는 참고용)')

    stop, seen = threading.Event(), set()
    def watch():
        while not stop.is_set():
            seen.update(external_connections(watched_pids()))
            stop.wait(1)
    watcher = threading.Thread(target=watch, daemon=True); watcher.start()

    model = Store(ROOT / 'data' / 'shipmail.sqlite3').settings()['model'] if (ROOT / 'data' / 'shipmail.sqlite3').exists() else ''
    with tempfile.TemporaryDirectory() as tmp:
        server = make_server(Path(tmp) / 'check.sqlite3', 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        c = Client(server.server_port)
        _, boot = c.call('/api/bootstrap'); c.token = boot['token']
        if model:
            c.call('/api/settings', {**boot['settings'], 'model': model})
        _, st = c.call('/api/status')
        names = [m['name'] for m in st.get('models', [])]
        check('Ollama 로컬 연결', st.get('connected', False), f"Ollama {st.get('version', '?')} · 설치 모델: {', '.join(names) or '없음'}")
        check('선택 모델 설치 확인', bool(model) and model in names, model or '선택된 모델 없음')

        if st.get('connected') and model in names:
            status, err, out = c.job({'kind': 'translate', 'original': SAMPLE})
            ok = status == 'done'
            check('해석 (실제 모델)', ok, f'{out[1]}초 · ' + ' / '.join(s['korean'] for s in out[0]['segments']) if ok else err)
            status, err, out = c.job({'kind': 'reply', 'original': SAMPLE, 'korean': KOREAN})
            ok = status == 'done'
            english = out[0]['english'] if ok else ''
            check('영어 회신 (실제 모델)', ok, f'{out[1]}초 · {english}' if ok else err)
            if ok:
                status, err, out = c.job({'kind': 'back', 'english': english})
                check('한국어 뜻 확인 (실제 모델)', status == 'done', f"{out[1]}초 · {out[0]['korean_meaning']}" if status == 'done' else err)
            _, ps = c.call('/api/status')
            for p in ps.get('processes', []):
                log(f"      메모리: {p['name']} 전체 {p['size']/1024**3:.2f}GB / GPU {p['size_vram']/1024**3:.2f}GB")
        else:
            log('      (모델이 연결되지 않아 AI 기능 점검을 건너뜀) → start-ollama-local.bat 실행 후 다시 시도')

        s1, saved = c.call('/api/save', {'kind': 'terms', 'record': {'english': 'OFFLINE TEST TERM', 'korean': '오프라인 시험 용어'}})
        _, found = c.call('/api/records?kind=terms&q=' + 'offline')
        check('자료실 추가·검색', s1 == 200 and any(r['english'] == 'OFFLINE TEST TERM' for r in found))
        _, snap = c.call('/api/backup', {})
        c.call('/api/delete', {'kind': 'terms', 'id': saved['id']})
        s2, _ = c.call('/api/restore', {'snapshot': snap})
        _, after = c.call('/api/records?kind=terms&q=offline')
        check('백업 → 삭제 → 복원 후 자료 유지', s2 == 200 and len(after) == 1)
        _, page = c.call('/')
        check('화면 파일에 외부 주소 없음', b'https://' not in page and b'http://' not in page.replace(b'http://127.0.0.1', b''))
        server.shutdown(); server.server_close()

    time.sleep(1.5); stop.set(); watcher.join()
    check('외부로 나가는 연결 없음 (ShipMail·Ollama 프로세스 감시)', not seen, ', '.join(sorted(seen)) if seen else '점검 중 루프백(127.0.0.1) 외 연결 없음')

    passed = sum(results)
    log(f'\n결과: {passed}/{len(results)} 통과' + ('' if not online else ' · ⚠ 인터넷이 연결된 상태에서 실행됨'))
    out_dir = ROOT / 'evals' / 'results'; out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / f'offline-check-{datetime.now():%Y%m%d-%H%M%S}.txt'
    report.write_text('\n'.join(lines), encoding='utf-8')
    log(f'결과 파일: {report}')

if __name__ == '__main__':
    main()
