"""Public entry point with a separate anonymous workspace per browser."""
import argparse
import io
import json
import os
import re
import secrets
from http.cookies import SimpleCookie, CookieError
from urllib.parse import unquote, urlparse

import app

COOKIE = 'aquascope_workspace'
MAX_UPLOAD = int(os.environ.get('MAX_UPLOAD_BYTES', 512 * 1024**2))


def public_data(value):
    if isinstance(value, dict):
        return {key: public_data(item) for key, item in value.items()
                if key not in ('owner_session', 'path')}
    if isinstance(value, list):
        return [public_data(item) for item in value]
    return value


class PublicHandler(app.Handler):
    def prepare_workspace(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
        except CookieError:
            pass
        value = cookie.get(COOKIE)
        value = value.value if value else ''
        self.new_workspace = not re.fullmatch('[a-f0-9]{64}', value)
        self.workspace = secrets.token_hex(32) if self.new_workspace else value
        self.request_path = unquote(urlparse(self.path).path)

    def end_headers(self):
        if getattr(self, 'new_workspace', False):
            secure = '; Secure' if self.headers.get('X-Forwarded-Proto', '').split(',')[0].strip() == 'https' else ''
            self.send_header('Set-Cookie', f'{COOKIE}={self.workspace}; Path=/; HttpOnly; SameSite=Lax; Max-Age=31536000{secure}')
        self.send_header('Referrer-Policy', 'strict-origin-when-cross-origin')
        super().end_headers()

    def headers_ok(self):
        origin = self.headers.get('Origin')
        host = self.headers.get('Host', '')
        allowed = {f'https://{host}', f'http://{host}'}
        allowed.update(s.strip().rstrip('/') for s in os.environ.get('PUBLIC_ORIGINS', '').split(',') if s.strip())
        return not origin or origin.rstrip('/') in allowed

    def owns_run(self):
        parts = self.request_path.strip('/').split('/')
        run_id = parts[2] if parts[:2] == ['api', 'jobs'] and len(parts) > 2 else parts[1] if parts[0] == 'runs' and len(parts) > 1 else None
        if run_id is None:
            return True
        with app.LOCK:
            job = app.JOBS.get(run_id)
            return bool(job and job.get('owner_session') == self.workspace)

    def send(self, data, ctype='application/json; charset=utf-8', status=200, attachment=None):
        if self.command == 'POST' and status == 200 and isinstance(data, dict):
            if self.request_path == '/api/uploads' and 'id' in data and 'size' in data:
                data['owner_session'] = self.workspace
                (app.UPLOADS / f'{data["id"]}.json').write_text(json.dumps(data), encoding='utf-8')
            elif self.request_path == '/api/jobs' and data.get('id') in app.JOBS:
                with app.LOCK:
                    data['owner_session'] = self.workspace
                    app.write_job(data)
        super().send(public_data(data), ctype, status, attachment)

    def do_GET(self):
        self.prepare_workspace()
        if not self.headers_ok():
            return self.error('Source not allowed.', 403)
        if self.request_path == '/health':
            return self.send(dict(status='ok'))
        if not self.owns_run():
            return self.error('Run not found in this browser workspace.', 404)
        if self.request_path == '/api/state':
            with app.LOCK:
                history = [{key: job[key] for key in ['id', 'title', 'created', 'status', 'progress', 'message']} |
                           {'candidate_count': len(job['candidates'])}
                           for job in sorted(app.JOBS.values(), key=lambda job: job['created'], reverse=True)
                           if job.get('owner_session') == self.workspace]
            return self.send(dict(token=app.TOKEN, model='Fairview v3', threshold=.9855765700340271,
                                  jobs=history, known_reference=None, demo=None))
        super().do_GET()

    def do_POST(self):
        self.prepare_workspace()
        if not self.headers_ok() or self.headers.get('X-App-Token') != app.TOKEN:
            return self.error('Please use the application page.', 403)
        if not self.owns_run():
            return self.error('Run not found in this browser workspace.', 404)
        if self.request_path in ('/api/local-test', '/api/demo'):
            return self.error('Survey fixtures are not included in the public deployment.', 404)
        if self.request_path == '/api/uploads':
            try:
                size = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                return self.error('Invalid upload size.')
            if size > MAX_UPLOAD:
                return self.error(f'This deployment accepts up to {MAX_UPLOAD // 1024**2} MB per file.', 413)
        elif self.request_path == '/api/jobs':
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 1024**2:
                    return self.error('Invalid request size.', 413)
                body = self.rfile.read(length)
                data = json.loads(body)
                uploads = data.get('uploads', [])
                if not isinstance(uploads, list) or not 1 <= len(uploads) <= 128:
                    return self.error('Each run supports 1–128 files.')
                for upload_id in uploads:
                    if not isinstance(upload_id, str) or not re.fullmatch('[a-f0-9]{32}', upload_id):
                        return self.error('Invalid upload ID.')
                    metadata = json.loads((app.UPLOADS / f'{upload_id}.json').read_text(encoding='utf-8'))
                    if metadata.get('owner_session') != self.workspace:
                        return self.error('Upload not found in this browser workspace.', 404)
                self.rfile = io.BytesIO(body)
            except (ValueError, OSError):
                return self.error('Upload not found in this browser workspace.', 404)
        super().do_POST()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default=os.environ.get('HOST', '0.0.0.0'))
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT', '7860')))
    args = parser.parse_args()
    server = app.ThreadingHTTPServer((args.host, args.port), PublicHandler)
    print(f'AquaScope GPR listening on {args.host}:{server.server_port}', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
