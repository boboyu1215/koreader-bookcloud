import http.client
import json
import ssl
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import app


class RetryTests(unittest.TestCase):
    def test_gateway_error_retried_then_succeeds(self):
        responses = []
        for status in (502, 503, 200):
            response = MagicMock(status=status)
            response.getheader.return_value = ''
            response.read.side_effect = [b'book', b'']
            conn = MagicMock(sock=None)
            conn.getresponse.return_value = response
            responses.append(conn)
        with patch.object(app, 'public_target', return_value=(app.urlsplit('https://example.org/a'), '93.184.216.34')), \
             patch.object(app, 'PinnedHTTPS', side_effect=responses) as connect, patch.object(app.time, 'sleep') as sleep:
            self.assertEqual(app.fetch('https://example.org/a'), b'book')
        self.assertEqual(connect.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertTrue(all(c.close.call_count == 1 for c in responses))

    def test_permanent_error_and_bad_certificate_not_retried(self):
        for error in (app.UpstreamError('HTTP 404', 404), ssl.SSLCertVerificationError('invalid')):
            with patch.object(app, '_fetch_once', side_effect=error) as fetch, patch.object(app.time, 'sleep') as sleep:
                with self.assertRaises(app.UpstreamError): app.fetch('https://example.org/a')
                self.assertEqual(fetch.call_count, 1)
                sleep.assert_not_called()

    def test_retries_are_bounded_and_share_deadline(self):
        with patch.object(app, '_fetch_once', side_effect=app.UpstreamError('HTTP 502', 502, True)) as fetch, patch.object(app.time, 'sleep'):
            with self.assertRaises(app.UpstreamError): app.fetch('https://example.org/a')
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(len({call.args[-1] for call in fetch.call_args_list}), 1)

    def test_invalid_target_is_never_retried(self):
        with patch.object(app, 'public_target', side_effect=ValueError('private address')) as validate:
            with self.assertRaises(ValueError): app.fetch('https://example.org/a')
        self.assertEqual(validate.call_count, 1)


class BackendFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        app.DATA = Path(self.tmp.name)
        app.init()
        app.PAIRING.clear()
        app.JOBS.clear()
        app.AUTH_FAILURES.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def test_pairing_one_use_expiry_and_attempt_budget(self):
        issued = app.create_pairing()
        self.assertEqual(len(issued['code']), 8)
        self.assertEqual(app.redeem_pairing(issued['code'])['device_token'], app.token('device-token'))
        with self.assertRaises(ValueError): app.redeem_pairing(issued['code'])
        issued = app.create_pairing()
        app.PAIRING['expires'] = time.time()-1
        with self.assertRaises(ValueError): app.redeem_pairing(issued['code'])
        issued = app.create_pairing()
        for _ in range(10):
            with self.assertRaises(ValueError): app.redeem_pairing('wrong')
        with self.assertRaises(ValueError): app.redeem_pairing(issued['code'])

    def test_pairing_admin_only_and_status_requires_device_auth(self):
        server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def request(path, headers=None, body=None):
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
            conn.request('POST' if body is not None else 'GET', '/bookcloud'+path,
                         json.dumps(body) if body is not None else None, headers or {})
            response = conn.getresponse()
            result = response.status, json.loads(response.read())
            conn.close()
            return result
        try:
            device = {'Authorization': 'Bearer '+app.token('device-token'), 'X-BookCloud': '1'}
            self.assertEqual(request('/admin/pairing', device, {})[0], 403)
            self.assertEqual(request('/api/v1/status')[0], 401)
            self.assertEqual(request('/api/v1/status', device)[0], 200)
            admin = {'Cookie': 'bookcloud_admin='+app.token('admin-token'), 'X-BookCloud': '1'}
            status, issued = request('/admin/pairing', admin, {})
            self.assertEqual(status, 200)
            status, redeemed = request('/api/v1/pair', body={'code': issued['code']})
            self.assertEqual(status, 200)
            self.assertEqual(redeemed['device_token'], app.token('device-token'))
            self.assertNotIn(app.token('admin-token'), json.dumps(redeemed))
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def wait_job(self, eid):
        for _ in range(300):
            with app.LOCK: result = dict(app.JOBS[eid])
            if result['status'] != 'preparing': return result
            time.sleep(.01)
        self.fail('download preparation did not finish')

    def test_file_is_ready_only_after_upstream_fetch_and_validation(self):
        source = app.source_list()[0]
        edition = app.normalized_book(source, {'title': 'Example', 'url': 'https://example.org/a.pdf', 'format': 'pdf'})
        gate = threading.Event()
        def fetch(*args):
            gate.wait(2)
            return b'%PDF-test'
        with patch.object(app, 'fetch', side_effect=fetch) as remote:
            self.assertEqual(app.download_state(edition, True)['status'], 'preparing')
            self.assertNotIn('url', app.download_state(edition))
            gate.set()
            self.assertEqual(self.wait_job(edition['edition_id'])['status'], 'ready')
            self.assertEqual(app.download_state(edition)['status'], 'ready')
            self.assertEqual(app.prepared_path(edition['edition_id'], 'pdf').read_bytes(), b'%PDF-test')
            self.assertEqual(remote.call_count, 1)

    def test_failure_names_source_and_stage_without_marking_file_ready(self):
        source = app.source_list()[0]
        edition = app.normalized_book(source, {'title': 'Example', 'url': 'https://example.org/a.pdf', 'format': 'pdf'})
        with patch.object(app, 'fetch', side_effect=app.UpstreamError('HTTP 502', 502, True)):
            app.download_state(edition, True)
            result = self.wait_job(edition['edition_id'])
        self.assertEqual(result['status'], 'failed')
        self.assertIn(source['name'], result['error'])
        self.assertIn('获取文件', result['error'])
        self.assertTrue(result['retryable'])
        self.assertFalse(app.prepared_path(edition['edition_id'], 'pdf').exists())
        self.assertIn('HTTP 502', app.db().execute('SELECT message FROM source_status WHERE id=?', (source['id'],)).fetchone()[0])

    def test_author_search_sorts_series_volumes_naturally(self):
        source = app.source_list()[0]
        titles = ['系列10', '系列2', '系列1', '另一系列第十二卷', '另一系列第二卷']
        books = [app.normalized_book(source, {'title': t, 'authors': ['作者'], 'url': 'https://example.org/'+str(i)+'.epub'}) for i, t in enumerate(titles)]
        with patch.object(app, 'provider_search', return_value=books):
            ordered = [w['title'] for w in app.search('作者')['works']]
        self.assertLess(ordered.index('系列2'), ordered.index('系列10'))
        self.assertLess(ordered.index('另一系列第二卷'), ordered.index('另一系列第十二卷'))
        self.assertEqual(len(ordered), 5)
        self.assertEqual(app.natural_title('第一性原理'), ((0, '第一性原理'),))
