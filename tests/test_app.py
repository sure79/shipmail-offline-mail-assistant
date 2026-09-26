import http.client
import json
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import make_server, App
from checks import segments, compare, extract
from model import endpoint, validate_settings, validate_output, request, Call, ModelError, generate, ensure_local, installed, runtime_error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from store import Store, export_csv, DEFAULTS
TEST_TMP = Path(__file__).resolve().parent / '.tmp'
TEST_TMP.mkdir(exist_ok=True)
MODEL = {**DEFAULTS, 'model': 'qwen3:4b-instruct-2507-q4_K_M'}

class DBTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=TEST_TMP)
        self.path = Path(self.tmp.name)/'test.db'
        self.db = Store(self.path)
    def tearDown(self):
        self.tmp.cleanup()
    def test_seed_drafts_only(self):
        self.assertEqual(len(self.db.list('examples')),32)
        self.assertEqual(len(self.db.list('terms')),15)
        self.assertFalse(self.db.references('MSBD POWER DIAGRAM'))
        self.assertEqual(self.db.list('history'),[])
    def test_crud_persists(self):
        i=self.db.save('projects',{'name':'H001','notes':'440 V'})
        self.db.save('projects',{'name':'H002','notes':'220 V'},i)
        self.assertEqual(Store(self.path).list('projects')[0]['name'],'H002')
        self.db.delete('projects',i)
        self.assertFalse(self.db.list('projects'))
    def test_reviewed_reference_and_search(self):
        row=self.db.list('terms','MSBD')[0]
        row['status']='reviewed'
        self.db.save('terms',row,row['id'])
        self.assertEqual(len(self.db.references('Check msbd.')),1)
        self.assertTrue(self.db.list('terms','배전'))
    def test_import_duplicate_and_merge(self):
        rows=[{'english':'TEST','korean':'시험'},{'english':'test','korean':'시험2'}]
        self.assertTrue(self.db.preview_import('terms',rows)[1]['conflict'])
        self.assertEqual(self.db.import_rows('terms',rows,'skip'),1)
        self.assertEqual(self.db.import_rows('terms',rows,'merge'),2)
        self.assertEqual(self.db.list('terms','test')[0]['korean'],'시험2')
    def test_bad_import_atomic(self):
        before=self.db.snapshot()
        with self.assertRaises(ValueError):
            self.db.import_rows('terms',[{'english':'X','korean':'가'},{'english':99,'korean':'나'}],'merge')
        self.assertEqual(before,self.db.snapshot())
    def test_restore_with_backup_and_bad_settings(self):
        snap=self.db.snapshot()
        self.db.save('projects',{'name':'Will be backed up'})
        name=self.db.restore(snap,validate_settings)
        self.assertTrue((self.path.parent/'backups'/name).exists())
        self.assertFalse(self.db.list('projects'))
        snap['settings']['endpoint']='http://example.com'
        with self.assertRaises(ValueError):
            self.db.restore(snap,validate_settings)
        self.assertEqual(len(self.db.list('examples')),32)
    def test_csv_formula_neutralized(self):
        csv=export_csv('projects',[{'name':' =HYPERLINK("x")','notes':'@SUM(A1)'}])
        self.assertIn("' =HYPERLINK",csv)
        self.assertIn("'@SUM",csv)
    def test_unknown_fields_rejected(self):
        with self.assertRaises(ValueError):
            self.db.save('projects',{'name':'A','path':'../../evil'})

class ReviewTests(unittest.TestCase):
    def test_sentence_ids_offsets(self):
        text='Please indicate No.1 DG and No.2 DG separately.\n440 V, 3.7 kW, No.2 pump. Rev.E supersedes Rev.D.'
        result=segments(text)
        self.assertEqual(len(result),3)
        for s in result:
            self.assertEqual(s['text'],text[s['start']:s['end']])
        self.assertIn('3.7',result[1]['text'])
    def test_revisions_and_equipment(self):
        r=compare('No.1 DG, No.2 DG, Rev.E','No.1 DG, Rev.D')
        self.assertIn('No.2',[x['value'] for x in r['missing']])
        self.assertIn('Rev.E',[x['value'] for x in r['missing']])
    def test_units_spaces(self):
        r=compare('440 V, 3.7 kW, No.2 pump','440V, 3.7kW, No.2 펌프')
        self.assertFalse(r['missing'] or r['added'])
    def test_date_and_quantity(self):
        r=compare('2026-09-23, one, 2 pcs','2026년 9월 23일, 1개, 2개')
        self.assertFalse(r['missing'] or r['added'])
    def test_negation_not_equivalence(self):
        a='The fan is not required to stop.'
        b='The fan is required not to stop.'
        r=compare(a,b)
        self.assertEqual(len(r['source_markers']),2)
        self.assertIn('보장하지',r['notice'])
    def test_weekday_mismatch_flagged(self):
        r=compare('Could you send it by Friday?','수요일까지 보내주실 수 있나요?')
        self.assertEqual([m['value'] for m in r['missing']],['Friday'])
        self.assertEqual([m['value'] for m in r['added']],['수요일'])
        self.assertFalse(compare('by Friday','금요일까지')['missing'])
    def test_scope_word_dropped(self):
        gaps=compare('갈리 쪽만 ES3로 변경했습니다.','The Gali side has been changed to ES3.')['concept_gaps']
        self.assertEqual([g['concept'] for g in gaps],['범위 한정(만/only)'])
        self.assertFalse(compare('갈리 쪽만 ES3로 변경했습니다.','Only the galley side has been changed to ES3.')['concept_gaps'])
        gaps=compare('The fan is not required to stop.','팬은 멈춰야 합니다.')['concept_gaps']
        self.assertIn('부정(않/없/not)',[g['concept'] for g in gaps])
        self.assertFalse(compare('No.2 pump','No.2 펌프')['concept_gaps'])
    def test_korean_suffix_after_unit(self):
        r=compare('440 V, 3.7 kW, No.2 pump','No.2 펌프는 440 V, 3.7 kW입니다.')
        self.assertFalse(r['missing'] or r['added'])
        self.assertNotIn('No',[m['value'] for m in r['source_markers']])
    def test_approval_marked(self):
        r=compare('검토 후 승인 부탁드립니다.','It has been approved.')
        self.assertIn('approved',[m['value'] for m in r['target_markers']])
    def test_multiplicity(self):
        self.assertEqual(len(compare('one smoke detector and one flame detector','1개 감지기')['missing']),1)

class UpgradeTests(unittest.TestCase):
    MAIL = "Dear Sir,\n\nGood day.\n\nCould you please send us the revised power diagram by Friday? We need to review it before updating our yard drawing.\n\nThank you for your cooperation.\n\nBest regards,\nGil Dong Hong\nElectrical Design Team"
    def test_formulas_and_signature_skip_model(self):
        from checks import rule_translations
        segs = segments(self.MAIL)
        fixed = rule_translations(segs)
        texts = {s['id']: s['text'].strip() for s in segs}
        self.assertEqual(fixed[1], '담당자님께,')
        self.assertIn('Gil Dong Hong', [v.split('  (')[0] for v in fixed.values()])
        self.assertIn('Electrical Design Team', [v.split('  (')[0] for v in fixed.values()])
        model_lines = [texts[i] for i in texts if i not in fixed]
        self.assertTrue(any('Friday' in l for l in model_lines))
        self.assertFalse(any('regards' in l.lower() for l in model_lines))
    def test_body_after_closing_is_not_signature(self):
        from checks import rule_translations
        segs = segments("Best regards,\nPlease note the drawing will be sent on Monday.")
        self.assertNotIn(2, rule_translations(segs))
    def test_named_greeting_keeps_name(self):
        from checks import formula_korean
        self.assertEqual(formula_korean('Dear Mr. Kim,'), 'Mr. Kim 님께,')
        self.assertIsNone(formula_korean('Dear Sir, please check the drawing.'))
    def test_han_characters_flagged(self):
        from app import HAN
        self.assertTrue(HAN.search('添付된 Rev.E는 Rev.D를 대체합니다.'))
        self.assertFalse(HAN.search('첨부된 Rev.E는 Rev.D를 대체합니다.'))
    def test_learn_upsert_and_undo(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as tmp:
            db = Store(Path(tmp)/'t.db')
            rec = {'english': 'We need to review our yard drawing.', 'korean': '창고 도면', 'status': 'reviewed'}
            first = db.learn('examples', rec, 'english')
            self.assertTrue(first['created'])
            second = db.learn('examples', {**rec, 'korean': '조선소 도면'}, 'english')
            self.assertFalse(second['created'])
            self.assertEqual(second['id'], first['id'])
            self.assertEqual(len(db.list('examples', 'yard drawing')), 1)
            self.assertEqual(db.list('examples', 'yard drawing')[0]['korean'], '조선소 도면')
            db.unlearn('examples', second['id'], second['previous'])
            self.assertEqual(db.list('examples', 'yard drawing')[0]['korean'], '창고 도면')
            db.unlearn('examples', first['id'], first['previous'])
            self.assertFalse(db.list('examples', 'yard drawing'))
            with self.assertRaises(ValueError):
                db.learn('history', {'name': 'x'}, 'name')
    def test_untranslated_english_detected(self):
        from app import untranslated
        self.assertTrue(untranslated('No.2 소화 펌프 기동기 shall be changed from DOL to soft starter.'))
        self.assertTrue(untranslated('No.2 소화기 펌프 제어기 shall be 변경 from DOL to 소프트 스타터.'))
        self.assertFalse(untranslated('No.2 소화 펌프 기동기를 DOL에서 soft starter로 변경해야 합니다.'))
        self.assertFalse(untranslated('우리 yard drawing을 업데이트하기 전에 검토해야 합니다.'))
    def test_glossary_check(self):
        from app import term_notes
        g = [('cable gland', '케이블 글랜드', [])]
        self.assertTrue(term_notes(g, 'Cable glands are not included.', '케이블 가드는 포함되지 않습니다.'))
        self.assertFalse(term_notes(g, 'Cable glands are not included.', '케이블 글랜드는 포함되지 않습니다.'))
        self.assertTrue(term_notes(g, '케이블 글랜드는 제외입니다.', 'Cable terminals are excluded.'))
    def test_similar_saved_example_is_referenced(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as tmp:
            db = Store(Path(tmp)/'t.db')
            db.save('examples', {'english': 'Please send us the revised power diagram by Friday.', 'korean': '금요일까지 수정된 전원 계통도를 보내 주십시오.', 'status': 'reviewed'})
            refs = db.references('Could you please send us the revised power diagram by Monday?')
            self.assertEqual(len(refs), 1)
            self.assertFalse(db.references('The fan is not required to stop.'))

class SecurityTests(unittest.TestCase):
    def test_loopback_only(self):
        for url in ['http://example.com','https://127.0.0.1','http://localhost:11434','http://127.0.0.1@evil.com','http://127.0.0.1/x','http://0.0.0.0','http://[::ffff:8.8.8.8]','http://127.0.0.1?remote=1']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                endpoint(url)
        self.assertEqual(endpoint('http://127.0.0.1:11434'),('127.0.0.1',11434))
        self.assertEqual(endpoint('http://[::1]:11434'),('::1',11434))
    def test_cloud_settings_rejected(self):
        with self.assertRaises(ValueError):
            validate_settings({'model':'gpt-oss:20b-cloud'})
    def test_remote_metadata_rejected(self):
        with patch('model.installed',return_value=[{'name':MODEL['model']}]),patch('model.request',return_value={'remote_host':'https://evil'}),self.assertRaises(ModelError):
            ensure_local(MODEL)
    def test_licence_text_is_not_remote(self):
        info={'modelfile':'FROM C:/models/blobs/sha256-abc\nLICENSE """any other electronic or remote means"""','capabilities':['completion']}
        with patch('model.installed',return_value=[{'name':MODEL['model']}]),patch('model.request',return_value=info):
            self.assertEqual(ensure_local(MODEL),['completion'])
        with patch('model.installed',return_value=[{'name':MODEL['model']}]),patch('model.request',return_value={'modelfile':'FROM https://example.com/model'}),self.assertRaises(ModelError):
            ensure_local(MODEL)
    def test_no_model_selected(self):
        with patch('model.request') as fake,self.assertRaises(ModelError) as ctx:
            ensure_local(DEFAULTS)
        self.assertIn('선택',str(ctx.exception))
        fake.assert_not_called()
    def test_output_missing_segment(self):
        with self.assertRaises(ValueError):
            validate_output('translate',{'segments':[{'id':2,'korean':'내용'}],'requests':[],'conditions':[],'uncertainties':[]},[1,2])
    def test_malformed_retry_only_once(self):
        with patch('model.request',return_value={'message':{'content':'not json'}}) as fake:
            with self.assertRaises(ModelError):
                generate(MODEL,'reply',{},Call())
            self.assertEqual(fake.call_count,2)
    def test_reasoning_is_not_exposed(self):
        body={'korean_meaning':'검토용','uncertainties':[]}
        with patch('model.request',return_value={'message':{'content':json.dumps(body),'thinking':'PRIVATE REASONING'}}):
            result,_=generate(MODEL,'back',{},Call())
            self.assertNotIn('thinking',result)
    def test_context_limit_no_truncation(self):
        with patch('model.request') as fake,self.assertRaises(ModelError):
            generate(MODEL,'reply',{'korean':'한'*9000},Call())
        fake.assert_not_called()
    def test_small_context_is_usable(self):
        from model import output_budget
        self.assertEqual(output_budget({**MODEL,'context_size':4096}),1536)
        with patch('model.request',return_value={'message':{'content':json.dumps({'korean_meaning':'뜻','uncertainties':[]})}}):
            generate({**MODEL,'context_size':4096},'back',{'english':'Please check.'},Call())
    def test_caution_notes(self):
        from checks import cautions
        self.assertIn('의무 없음',cautions('The fan is not required to stop.')[0])
        self.assertIn('금지',cautions('The fan is required not to stop.')[0])
        self.assertEqual(cautions('Motor data: 440 V.'),[])
    def test_cancel_before_request(self):
        call=Call();call.cancel()
        with self.assertRaises(ModelError):
            request(DEFAULTS,'/api/chat',{},call)

class FakeRuntime(BaseHTTPRequestHandler):
    """Loopback stand-in for Ollama / LM Studio. Records requests; never contacts the network."""
    def log_message(self,*a): pass
    def reply(self,status,body,headers=None):
        data=json.dumps(body).encode();self.send_response(status)
        for k,v in (headers or {}).items(): self.send_header(k,v)
        self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def do_GET(self):
        self.server.seen.append(('GET',self.path,None))
        if self.path=='/api/tags': return self.reply(200,{'models':[{'name':'qwen3:4b','size':2_500_000_000,'details':{'parameter_size':'4B'}},{'name':'gpt-oss:120b-cloud','size':384,'details':{'parameter_size':'116.8B'},'remote_host':'https://ollama.com'}]})
        if self.path=='/v1/models': return self.reply(200,{'data':[{'id':'qwen3-4b-instruct-2507'},{'id':'text-embedding-nomic'}]})
        self.reply(404,{'error':'not found'})
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.seen.append(('POST',self.path,body))
        mode=self.server.mode
        if mode=='oom': return self.reply(500,{'error':'model requires more system memory (9.1 GiB) than is available (5.2 GiB)'})
        if mode=='redirect': return self.reply(302,{},{'Location':'http://example.com/steal'})
        if self.path=='/api/show': return self.reply(200,{'capabilities':['completion','thinking']})
        out=json.dumps({'korean_meaning':'검토용 뜻','uncertainties':[]},ensure_ascii=False)
        if self.path=='/api/chat': return self.reply(200,{'message':{'content':out,'thinking':'SECRET'},'done_reason':'stop'})
        if self.path=='/v1/chat/completions': return self.reply(200,{'choices':[{'message':{'content':'<think>SECRET</think>'+out},'finish_reason':'stop'}]})
        self.reply(404,{'error':'not found'})

class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.srv=ThreadingHTTPServer(('127.0.0.1',0),FakeRuntime);self.srv.seen=[];self.srv.mode='ok'
        threading.Thread(target=self.srv.serve_forever,daemon=True).start()
        self.url=f'http://127.0.0.1:{self.srv.server_port}'
    def tearDown(self):
        self.srv.shutdown();self.srv.server_close()
    def test_ollama_filters_cloud_and_sends_think_only_when_capable(self):
        s={**DEFAULTS,'endpoint':self.url,'model':'qwen3:4b'}
        self.assertEqual([m['name'] for m in installed(s)],['qwen3:4b'])
        caps=ensure_local(s)
        result,_=generate({**s,'_caps':caps},'back',{'english':'Hi'},Call())
        self.assertEqual(result['korean_meaning'],'검토용 뜻')
        chat=[b for m,p,b in self.srv.seen if p=='/api/chat'][0]
        self.assertIs(chat['think'],False)
        self.assertIn('format',chat)
        result,_=generate({**s,'_caps':['completion']},'back',{'english':'Hi'},Call())
        self.assertNotIn('think',[b for m,p,b in self.srv.seen if p=='/api/chat'][-1])
    def test_lmstudio_structured_output_and_reasoning_stripped(self):
        s={**DEFAULTS,'runtime':'openai','endpoint':self.url,'model':'qwen3-4b-instruct-2507'}
        self.assertEqual([m['name'] for m in installed(s)],['qwen3-4b-instruct-2507'])
        self.assertEqual(ensure_local(s),[])
        result,_=generate(s,'back',{'english':'Hi'},Call())
        self.assertNotIn('SECRET',json.dumps(result,ensure_ascii=False))
        body=[b for m,p,b in self.srv.seen if p=='/v1/chat/completions'][0]
        self.assertEqual(body['response_format']['type'],'json_schema')
    def test_out_of_memory_message(self):
        self.srv.mode='oom'
        with self.assertRaises(ModelError) as ctx:
            request({**MODEL,'endpoint':self.url},'/api/chat',{})
        self.assertIn('메모리 부족',str(ctx.exception))
    def test_redirect_not_followed(self):
        self.srv.mode='redirect'
        with self.assertRaises(ModelError) as ctx:
            request({**MODEL,'endpoint':self.url},'/api/chat',{})
        self.assertIn('따라가지 않았습니다',str(ctx.exception))
        self.assertEqual(len(self.srv.seen),1)
    def test_runtime_error_mapping_ignores_raw_text(self):
        self.assertNotIn('secret mail',str(runtime_error(500,b'{"error":"secret mail text"}')))
    def test_invalid_runtime_rejected(self):
        for bad in [{'runtime':'openai-cloud'},{'autosave':'yes'},{'model':'x'*200}]:
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                validate_settings(bad)

class EvalTests(unittest.TestCase):
    def test_cases_file_and_hints(self):
        from evaluate import hint_flags
        cases=json.loads((Path(__file__).resolve().parents[1]/'evals'/'cases.json').read_text(encoding='utf-8'))['cases']
        self.assertTrue(20<=len(cases)<=30)
        self.assertTrue(all(c['source']=='developer' for c in cases))
        case=next(c for c in cases if c['id']=='R02')
        _,flags=hint_flags(case,{'subject':'Drawing','english':'The drawing has been approved.','unanswered':[]})
        self.assertTrue(any('금지 표현' in f for f in flags))
        case=next(c for c in cases if c['id']=='N01')
        _,flags=hint_flags(case,{'segments':[{'korean':'팬은 정지하지 않아도 됩니다.'}]})
        self.assertEqual(flags,[])

class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=TEST_TMP)
        self.server=make_server(Path(self.tmp.name)/'db.sqlite3',0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
    def call(self,path='/',data=None,headers=None):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        c.request('POST' if data is not None else 'GET',path,json.dumps(data) if data is not None else None,headers or {})
        r=c.getresponse();result=(r.status,r.read(),dict(r.getheaders()));c.close();return result
    def auth(self):
        return {'Content-Type':'application/json','X-ShipMail-Token':self.server.app.token}
    def test_second_instance_cannot_share_port(self):
        with self.assertRaises(OSError):
            make_server(Path(self.tmp.name)/'db2.sqlite3', self.server.server_port)
    def test_learn_endpoint_respects_setting(self):
        body = {'kind': 'terms', 'key': 'english', 'record': {'english': 'yard', 'korean': '조선소', 'status': 'reviewed'}}
        self.assertEqual(self.call('/api/learn', body, {'Content-Type': 'application/json'})[0], 403)
        code, raw, _ = self.call('/api/learn', body, self.auth())
        self.assertEqual(code, 200)
        saved = json.loads(raw)
        self.assertEqual(self.server.app.db.glossary()[-1][:2], ('yard', '조선소'))
        self.assertEqual(self.call('/api/unlearn', {'kind': 'terms', 'id': saved['id'], 'previous': None}, self.auth())[0], 200)
        self.assertFalse([g for g in self.server.app.db.glossary() if g[0] == 'yard'])
        self.server.app.db.settings({'auto_learn': False})
        self.assertEqual(self.call('/api/learn', body, self.auth())[0], 400)
    def test_host_origin_csrf(self):
        self.assertEqual(self.call(headers={'Host':'evil.com'})[0],403)
        self.assertEqual(self.call('/api/bootstrap',headers={'Origin':'https://evil.com'})[0],403)
        self.assertEqual(self.call('/api/settings',{}, {'Content-Type':'application/json'})[0],403)
        self.assertEqual(self.call('/api/settings',DEFAULTS,self.auth())[0],200)
    def test_csp_no_external_assets(self):
        status,body,headers=self.call()
        self.assertEqual(status,200)
        self.assertIn("connect-src 'self'",headers['Content-Security-Policy'])
        self.assertNotIn(b'https://',body)
        self.assertEqual(self.call('/../store.py')[0],404)
    def test_ui_db_work_without_external_network(self):
        original=socket.create_connection
        def guard(address,*a,**kw):
            if address[0]!='127.0.0.1':
                raise AssertionError('External network blocked')
            return original(address,*a,**kw)
        with patch('socket.create_connection',side_effect=guard):
            self.assertEqual(self.call('/api/save',{'kind':'projects','record':{'name':'Offline'}},self.auth())[0],200)
            self.assertIn('Offline',self.call('/api/records?kind=projects')[1].decode())
    def test_real_connection_refusal(self):
        # Reserve an unused port then close it, so no actual Ollama is involved.
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        self.server.app.db.settings({'endpoint':f'http://127.0.0.1:{port}'})
        result=json.loads(self.call('/api/status')[1])
        self.assertFalse(result['connected'])
    def test_model_failure_leaves_no_history(self):
        with patch('app.ensure_local',side_effect=ModelError('연결 실패')):
            code,body,_=self.call('/api/start',{'kind':'translate','original':'No.1 pump.'},self.auth())
            self.assertEqual(code,200)
            time.sleep(.1)
            job=self.server.app.job
            self.assertEqual(job['status'],'error')
            self.assertFalse(self.server.app.db.list('history'))
    def test_mock_translation_pipeline_ids_and_memory_only(self):
        def fake(settings,kind,data,call,ids=None,on_text=None):
            if on_text:
                on_text('{"segments":[{"id":1,"korean":"No.1 펌프 확인."}')
            return {'segments':[{'id':i,'korean':'No.1 펌프 확인.'} for i in ids],'requests':['확인'],'conditions':[],'uncertainties':[]},.01
        with patch('app.ensure_local'),patch('app.generate',side_effect=fake):
            self.server.app.start({'kind':'translate','original':'Check No.1 pump.'})
            for _ in range(100):
                if self.server.app.job['status']!='running':break
                time.sleep(.01)
            self.assertEqual(self.server.app.job['status'],'done')
            self.assertEqual(self.server.app.job['result']['segments'][0]['text'],'Check No.1 pump.')
            self.assertFalse(self.server.app.db.list('history'))
    def test_skip_summary_keeps_translation(self):
        def fake(settings,kind,data,call,ids=None,on_text=None):
            on_text('{"segments":[' + ','.join('{"id":%d,"korean":"해석%d"}' % (i, i) for i in ids) + '],"uncertainties":[')
            call.cancel()
            raise ModelError('작업을 취소했습니다.')
        with patch('app.ensure_local'),patch('app.generate',side_effect=fake):
            self.server.app.start({'kind':'translate','original':'Check No.1 pump. Check No.2 pump.'})
            for _ in range(100):
                if self.server.app.job['status']!='running':break
                time.sleep(.01)
            job=self.server.app.job
            self.assertEqual(job['status'],'done')
            self.assertEqual([s['korean'] for s in job['result']['segments']],['해석1','해석2'])
            self.assertIn('건너뛰었습니다',job['result']['uncertainties'][0])
    def test_cancel_before_translation_done_is_cancelled(self):
        def fake(settings,kind,data,call,ids=None,on_text=None):
            on_text('{"segments":[{"id":1,"korean":"해석1"}')
            call.cancel()
            raise ModelError('작업을 취소했습니다.')
        with patch('app.ensure_local'),patch('app.generate',side_effect=fake):
            self.server.app.start({'kind':'translate','original':'Check No.1 pump. Check No.2 pump.'})
            for _ in range(100):
                if self.server.app.job['status']!='running':break
                time.sleep(.01)
            self.assertEqual(self.server.app.job['status'],'cancelled')
    def test_busy_job_protection_and_cancel(self):
        entered=threading.Event();release=threading.Event()
        def fake(_):
            entered.set();release.wait(2);raise ModelError('취소')
        with patch('app.ensure_local',side_effect=fake):
            self.server.app.start({'kind':'translate','original':'Mail.'});entered.wait(1)
            with self.assertRaises(ValueError):
                self.server.app.start({'kind':'reply','korean':'회신'})
            self.server.app.job['call'].cancel();release.set()
            for _ in range(100):
                if self.server.app.job['status']!='running':break
                time.sleep(.01)
            self.assertEqual(self.server.app.job['status'],'cancelled')

if __name__=='__main__':
    unittest.main(verbosity=2)
