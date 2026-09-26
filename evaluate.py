"""Run the evaluation set against a REAL local model and write a report for human review.

Usage:  py -3 evaluate.py --model qwen3:4b-instruct-2507-q4_K_M [--runtime ollama] [--only N01,R02]
        py -3 evaluate.py --cases my_real_mails.json      (사용자 실제 메일 평가 세트, source: "user")

The automatic hints are signals only. Pass/fail is decided by a person reading the report.
Reports are written under evals/results/ (git-ignored; may contain business text if user cases are used).
"""
import argparse
import json
import platform
import secrets
import sys
import time
from datetime import datetime
from pathlib import Path
from app import App, ROOT
from model import Call, ModelError, installed, request, validate_settings

def hint_flags(case, result):
    hints, flags = case.get('hints', {}), []
    if case['kind'] == 'translate':
        text = '\n'.join(s['korean'] for s in result['segments'])
    else:
        text = result['subject'] + '\n' + result['english']
    lower = text.lower()
    for token in hints.get('keep', []):
        if token.lower().replace(' ', '') not in lower.replace(' ', ''):
            flags.append(f'표기 누락 가능: {token}')
    for key in ('any', 'any_en'):
        if hints.get(key) and not any(t.lower() in lower for t in hints[key]):
            flags.append('기대 표현 없음(의미 확인 필요): ' + ' / '.join(hints[key]))
    for key in ('none', 'none_en'):
        for t in hints.get(key, []):
            if t.lower() in lower:
                flags.append(f'금지 표현 발견: {t}')
    for key in ('keep_words', 'keep_words_en'):
        if hints.get(key) and not any(t in text for t in hints[key]):
            flags.append('용어 확인: ' + ' / '.join(hints[key]))
    if hints.get('unanswered') and not result.get('unanswered'):
        flags.append('미답변 가능 항목이 비어 있음')
    return text, flags

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model')
    parser.add_argument('--runtime', choices=['ollama', 'openai'])
    parser.add_argument('--endpoint')
    parser.add_argument('--cases', default=str(ROOT / 'evals' / 'cases.json'))
    parser.add_argument('--only', default='')
    parser.add_argument('--context', type=int)
    args = parser.parse_args()

    app = App(ROOT / 'data' / 'shipmail.sqlite3')
    settings = app.db.settings()
    overrides = {k: v for k, v in {'model': args.model, 'runtime': args.runtime, 'endpoint': args.endpoint, 'context_size': args.context}.items() if v is not None}
    if args.runtime and not args.endpoint:
        overrides['endpoint'] = {'ollama': 'http://127.0.0.1:11434', 'openai': 'http://127.0.0.1:1234'}[args.runtime]
    settings = validate_settings({**settings, **overrides, 'signature': ''})
    try:
        models = installed(settings)
    except ModelError as e:
        sys.exit(f'[미검증] 로컬 런타임에 연결하지 못했습니다: {e}')
    info = next((m for m in models if m['name'] == settings['model']), None)
    if not info:
        sys.exit(f"[미검증] 모델 '{settings['model']}'이 설치되어 있지 않습니다. 설치된 모델: {', '.join(m['name'] for m in models) or '없음'}")
    version = request(settings, '/api/version', timeout=3).get('version', '?') if settings['runtime'] == 'ollama' else 'LM Studio'

    data = json.loads(Path(args.cases).read_text(encoding='utf-8'))
    cases = [c for c in data['cases'] if not args.only or c['id'] in args.only.split(',')]
    rows, peak = [], []
    print(f"모델 {settings['model']} · {len(cases)}건 평가 시작 (실제 로컬 모델 호출)")
    for case in cases:
        kind = case['kind']
        clean = {'original': case.get('original', ''), 'context': '', 'korean': case.get('korean', ''), 'english': ''}
        job = {'id': secrets.token_hex(4), 'status': 'running', 'progress': '', 'started': time.monotonic(), 'result': None, 'error': '', 'call': Call()}
        app.run(job, kind, clean, settings)
        row = {'id': case['id'], 'source': case.get('source', 'user'), 'kind': kind, 'input': case.get('original', '') if kind == 'translate' else case['korean'], 'meaning': case.get('meaning', ''), 'status': job['status']}
        if job['status'] == 'done':
            r = job['result']
            row['output'], row['flags'] = hint_flags(case, r)
            row['seconds'] = r['seconds']
            row['extra'] = {k: r[k] for k in ('requests', 'conditions', 'uncertainties', 'unanswered', 'korean_meaning') if k in r}
        else:
            row['output'], row['flags'], row['seconds'] = '', ['실패: ' + job['error']], round(time.monotonic() - job['started'], 2)
        if settings['runtime'] == 'ollama':
            try:
                peak.extend(request(settings, '/api/ps', timeout=3).get('models', []))
            except ModelError:
                pass
        print(f"  {row['id']} {row['status']} {row['seconds']}s  주의 {len(row['flags'])}건")
        rows.append(row)

    loaded = max((p for p in peak if p.get('name') == settings['model']), key=lambda p: p.get('size', 0), default=None)
    memory = f"전체 {loaded['size']/1024**3:.2f}GB, GPU {loaded['size_vram']/1024**3:.2f}GB" + (' (CPU로 실행)' if loaded['size_vram'] == 0 else ' (CPU/GPU 분할)' if loaded['size_vram'] < loaded['size'] else ' (GPU에 전부 로드)') if loaded else '측정 불가'
    done = [r for r in rows if r['status'] == 'done']
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    out_dir = ROOT / 'evals' / 'results'
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = settings['model'].replace(':', '_').replace('/', '_')
    meta = {'date': datetime.now().isoformat(timespec='seconds'), 'runtime': settings['runtime'], 'runtime_version': version, 'model': settings['model'],
            'quantization': (info.get('details') or {}).get('quantization_level', '?'), 'parameter_size': (info.get('details') or {}).get('parameter_size', '?'),
            'file_size_gb': round(info['size']/1024**3, 2) if info.get('size') else '?', 'context_size': settings['context_size'], 'memory': memory,
            'os': platform.platform(), 'cpu': platform.processor(), 'python': platform.python_version(),
            'cases': len(rows), 'completed': len(done), 'avg_seconds': round(sum(r['seconds'] for r in done)/len(done), 2) if done else None}
    (out_dir / f'{stamp}-{safe}.json').write_text(json.dumps({'meta': meta, 'rows': rows}, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = [f"# ShipMail 실제 모델 평가 보고서 · {meta['date']}", '',
             '> 자동 힌트는 참고 신호일 뿐 합격 판정이 아닙니다. 각 항목의 "사람 판정"을 직접 기입하세요. 중요한 의미 오류는 예문 DB로 덮지 말고 모델 한계로 기록합니다.', '',
             '| 항목 | 값 |', '|---|---|'] + [f'| {k} | {v} |' for k, v in meta.items()] + ['']
    for source, title in (('developer', '개발자가 만든 평가 예문'), ('user', '사용자가 제공한 실제 메일')):
        group = [r for r in rows if r['source'] == source]
        if not group:
            continue
        lines += [f'## {title} ({len(group)}건)', '']
        for r in group:
            lines += [f"### {r['id']} · {'해석' if r['kind'] == 'translate' else '영작'} · {r['status']} · {r['seconds']}초", '',
                      f"- 입력: {r['input']}", f"- 확인할 의미: {r['meaning']}", '- 출력:', '', '```', r['output'] or '(없음)', '```', '']
            if r.get('extra'):
                lines += ['- 부가 결과: ' + json.dumps(r['extra'], ensure_ascii=False)]
            lines += ['- 자동 힌트: ' + ('; '.join(r['flags']) if r['flags'] else '특이 신호 없음 (의미 일치를 보장하지 않음)'),
                      '- 사람 판정: [ ] 의미 보존  [ ] 경미한 표현 문제  [ ] 중요 의미 오류 — 메모:', '']
    report = out_dir / f'{stamp}-{safe}.md'
    report.write_text('\n'.join(lines), encoding='utf-8')
    print(f'\n완료 {len(done)}/{len(rows)} · 평균 {meta["avg_seconds"]}초 · 메모리 {memory}\n보고서: {report}')

if __name__ == '__main__':
    main()
