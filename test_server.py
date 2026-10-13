import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import server
import json
import threading
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer

class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=patch.object(server,'DB',Path(self.tmp.name)/'test.sqlite3')
        self.db.start(); server.init()
        server.patrol_attempts.clear()
        server.browser_token=None
        self.mint='So11111111111111111111111111111111111111112'
    def tearDown(self):
        self.db.stop();self.tmp.cleanup()
    def test_dashboard_does_not_fetch_network(self):
        with patch.object(server,'fetch',side_effect=AssertionError('network')):
            self.assertEqual(server.watches(),[])
    def test_track_persists_snapshot_and_is_idempotent(self):
        payload={'address':self.mint,'label':'WARN','risk_score':40}
        with patch.object(server,'fetch',return_value=payload) as fetch:
            server.scan(self.mint);server.scan(self.mint)
            self.assertEqual(fetch.call_count,2)
        with patch.object(server,'fetch',side_effect=AssertionError('network')):
            rows=server.watches()
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['scan']['risk_score'],40)
    def test_invalid_address_never_fetches(self):
        with patch.object(server,'fetch') as fetch:
            with self.assertRaises(ValueError):server.scan('../bad')
            fetch.assert_not_called()
    def test_wrong_mint_response_is_not_saved(self):
        with patch.object(server,'fetch',return_value={'address':'wrong'}):
            with self.assertRaises(ValueError):server.scan(self.mint)
        self.assertEqual(server.watches(),[])

    def test_baseline_survives_updates_and_duplicate_findings_make_no_events(self):
        first={'address':self.mint,'risk_score':10,'label':'GOOD','creator_position':{'status':'holding','current_share_pct':5}}
        second={**first,'risk_score':50,'label':'WARN','creator_position':{'status':'sold','current_share_pct':0}}
        with patch.object(server,'fetch',side_effect=[first,second,second]):
            server.scan(self.mint);server.scan(self.mint);server.scan(self.mint)
        row=server.watches()[0]
        self.assertEqual(row['baseline']['scan'],first)
        self.assertEqual(len(row['events']),4)
        self.assertEqual(row['scan'],second)

    def test_preview_is_not_watch_and_reuses_saved_scan(self):
        payload={'address':self.mint,'label':'WARN','risk_score':40}
        with patch.object(server,'fetch',return_value=payload) as fetch:
            server.follow_browser(self.mint)
            server.follow_browser(self.mint)
            self.assertEqual(fetch.call_count,1)
            self.assertEqual(server.watches(),[])
            server.scan(self.mint)
            server.browser_token=None
            server.follow_browser(self.mint)
            self.assertEqual(fetch.call_count,2)

    def test_paused_patrol_and_recent_scan_do_not_fetch(self):
        with patch.object(server,'fetch',return_value={'address':self.mint}):server.scan(self.mint)
        with patch.object(server,'fetch') as fetch:
            server.patrol_once()
            with server.connect() as db:
                db.execute("UPDATE settings SET value='off' WHERE key='patrol'")
                db.execute('UPDATE watches SET scanned=0')
            server.patrol_once()
            fetch.assert_not_called()

    def test_failed_patrol_retains_data_and_waits_before_retry(self):
        with patch.object(server,'fetch',return_value={'address':self.mint}):server.scan(self.mint)
        with server.connect() as db:db.execute('UPDATE watches SET scanned=0')
        with patch.object(server,'fetch',side_effect=OSError('offline')) as fetch:
            server.patrol_once();server.patrol_once()
            self.assertEqual(fetch.call_count,1)
            self.assertEqual(server.watches()[0]['scanned_at'],0)

    def test_bridge_key_persists_across_restart(self):
        token=server.BRIDGE_TOKEN
        server.init()
        self.assertEqual(server.BRIDGE_TOKEN,token)

    def test_removed_watch_is_not_restored_by_background_scan(self):
        with patch.object(server,'fetch',return_value={'address':self.mint}):server.scan(self.mint,existing_only=True)
        self.assertEqual(server.watches(),[])

class BridgeHTTPTests(unittest.TestCase):
    def setUp(self):
        SnapshotTests.setUp(self)
        self.http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.port=patch.object(server,'PORT',self.http.server_port);self.port.start()
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.http.server_port}'
    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join();self.port.stop()
        SnapshotTests.tearDown(self)
    def request(self,path,headers,body=None):
        req=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body else None,headers=headers)
        try:
            with urllib.request.urlopen(req) as response:return response.status,json.load(response)
        except urllib.error.HTTPError as error:return error.code,json.load(error)
    def test_unpaired_bridge_and_web_origin_are_rejected(self):
        for headers in [{},{'X-Desk-Bridge':server.BRIDGE_TOKEN,'Origin':'https://evil.test'}]:
            with patch.object(server,'fetch') as fetch:
                status,_=self.request('/api/browser',headers,{'mint':self.mint})
                self.assertEqual(status,403);fetch.assert_not_called()
    def test_paired_extension_can_preview_but_cannot_read_pairing_key(self):
        origin='chrome-extension://'+'a'*32
        with patch.object(server,'fetch',return_value={'address':self.mint}):
            status,_=self.request('/api/browser',{'X-Desk-Bridge':server.BRIDGE_TOKEN,'Origin':origin},{'mint':self.mint})
        self.assertEqual(status,200);self.assertEqual(server.watches(),[])
        status,_=self.request('/api/dashboard',{'Origin':origin})
        self.assertEqual(status,403)

if __name__=='__main__':unittest.main()


class AskTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=patch.object(server,'DB',Path(self.tmp.name)/'test.sqlite3')
        self.db.start(); server.init()
        self.mint='So11111111111111111111111111111111111111112'
        self.scan={'address':self.mint,'label':'DANGER','risk_score':75,'token_symbol':'TEST',
                   'creator_position':{'status':'sold','exit_signature':'abc'},'evidence':{'huge':'x'*50000}}
    def tearDown(self):
        self.db.stop();self.tmp.cleanup()
    def test_answers_from_the_scan_with_rules_and_no_evidence_blob(self):
        sent={}
        def post(data):
            sent.update(json.loads(data)); return {'choices':[{'message':{'content':'The creator sold.'}}]}
        with patch.dict('os.environ',{'DEEPSEEK_API_KEY':'k'}), patch.object(server,'fetch',return_value=self.scan):
            self.assertEqual(server.ask(self.mint,'Did the creator sell?',post=post),('The creator sold.',[]))
        system=sent['messages'][0]['content']
        self.assertIn('Never tell the user to buy, sell or hold',system)
        self.assertIn('"label": "DANGER"',system)
        self.assertNotIn('xxxx',system)
        self.assertEqual(sent['model'],'deepseek-chat')
    def test_no_key_is_a_clear_message_and_no_network(self):
        with patch.dict('os.environ',{'DEEPSEEK_API_KEY':''}), patch.object(server,'fetch',side_effect=AssertionError('network')):
            with self.assertRaises(ValueError): server.ask(self.mint,'hi',post=lambda d: AssertionError())
    def test_empty_question_is_refused(self):
        with self.assertRaises(ValueError): server.ask(self.mint,'   ')

    def test_research_uses_a_tool_then_answers(self):
        replies=[{'choices':[{'message':{'content':'','tool_calls':[{'id':'c1','type':'function','function':{'name':'wallet_activity','arguments':'{"address":"So11111111111111111111111111111111111111112"}'}}]}}]},
                 {'choices':[{'message':{'content':'The funder sent 30 SOL.'}}]}]
        seen=[]
        def post(data):
            seen.append(json.loads(data)); return replies[len(seen)-1]
        tool=lambda name,args:{'rows':[{'what':'sent 30 SOL'}]}
        with patch.dict('os.environ',{'DEEPSEEK_API_KEY':'k'}), patch.object(server,'fetch',return_value=self.scan):
            answer,looked=server.ask(self.mint,[{'role':'user','content':'who funded?'}],post=post,tool=tool)
        self.assertEqual((answer,looked),('The funder sent 30 SOL.',['wallet_activity']))
        self.assertEqual(seen[1]['messages'][-1]['role'],'tool')
        self.assertIn('sent 30 SOL',seen[1]['messages'][-1]['content'])
    def test_history_must_end_with_the_user(self):
        with self.assertRaises(ValueError): server.ask(self.mint,[{'role':'assistant','content':'hi'}])
