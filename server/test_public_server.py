"""Public upload/run/review boundaries, using disposable fixtures only."""
import copy
import http.cookiejar
import json
import shutil
import threading
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from unittest.mock import patch

import app
from public_server import PublicHandler


class PublicWorkspaces(unittest.TestCase):
    def setUp(self):
        self.temp = Path(__file__).parent / ('test_public_tmp_' + uuid.uuid4().hex)
        self.temp.mkdir()
        self.original = (app.STORE, app.UPLOADS, app.JOBS)
        app.STORE = self.temp / 'runs'
        app.UPLOADS = self.temp / 'uploads'
        app.STORE.mkdir()
        app.UPLOADS.mkdir()
        app.JOBS = {}
        self.server = app.ThreadingHTTPServer(('127.0.0.1', 0), PublicHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.a, self.b = [urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())) for _ in range(2)]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        app.STORE, app.UPLOADS, app.JOBS = self.original
        assert self.temp.resolve().parent == Path(__file__).parent.resolve()
        shutil.rmtree(self.temp)

    def request(self, client, path, data=None, raw=None, origin=None):
        headers = {'X-App-Token': app.TOKEN}
        if origin:
            headers['Origin'] = origin
        if data is not None:
            raw = json.dumps(data).encode()
            headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(self.base + path, data=raw, headers=headers)
        with client.open(req) as response:
            return json.load(response), response.headers

    def test_browser_workspaces_isolate_uploads_runs_images_and_bulk_clear(self):
        _, headers = self.request(self.a, '/api/state')
        self.request(self.b, '/api/state')
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn('SameSite=Lax', headers['Set-Cookie'])
        uploaded, _ = self.request(self.a, '/api/uploads?name=fixture.SGY', raw=b'0' * 3840)
        self.assertNotIn('path', uploaded)
        self.assertNotIn('owner_session', uploaded)
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request(self.b, '/api/jobs', {'uploads': [uploaded['id']]})
        self.assertEqual(error.exception.code, 404)
        with patch.object(app.POOL, 'submit'):
            run, _ = self.request(self.a, '/api/jobs', {'uploads': [uploaded['id']], 'title': 'Disposable isolation fixture'})
        self.assertNotIn('owner_session', run)
        run_id = run['id']
        self.assertEqual(len(self.request(self.a, '/api/state')[0]['jobs']), 1)
        self.assertEqual(self.request(self.b, '/api/state')[0]['jobs'], [])
        app.JOBS[run_id].update(status='done', candidates=[dict(candidate_id='C1', review_label='similar', notes='private note', reviewer='A')])
        before = copy.deepcopy(app.JOBS[run_id])
        for path, data in [(f'/api/jobs/{run_id}', None), (f'/runs/{run_id}/images/test.png', None),
                           (f'/api/jobs/{run_id}/clear-reviews', {'confirm_job_id': run_id})]:
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.request(self.b, path, data)
            self.assertEqual(error.exception.code, 404)
        self.assertEqual(app.JOBS[run_id], before)
        cleared, _ = self.request(self.a, f'/api/jobs/{run_id}/clear-reviews', {'confirm_job_id': run_id})
        self.assertEqual(cleared['cleared_count'], 1)
        disk = json.loads((app.STORE / run_id / 'job.json').read_text(encoding='utf-8'))
        self.assertEqual(disk['candidates'][0]['review_history'][0]['notes'], 'private note')
        self.assertEqual(disk['owner_session'], before['owner_session'])

    def test_local_fixtures_and_cross_origin_requests_are_not_exposed(self):
        for path in ['/api/demo', '/api/local-test']:
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.request(self.a, path, {})
            self.assertEqual(error.exception.code, 404)
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request(self.a, '/api/state', origin='https://unrelated.example')
        self.assertEqual(error.exception.code, 403)


if __name__ == '__main__':
    unittest.main()
