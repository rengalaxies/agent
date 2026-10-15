"""Loopback-only synthetic UI. Run with --state-dir on verified POSIX storage."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import RLock

from datamesh_release_protocol.evidence_pilot import SyntheticPilot

HTML = '''<!doctype html><html lang="ru"><meta charset="utf-8"><title>Пилот проверки доказательств</title>
<style>body{font:17px system-ui;max-width:980px;margin:40px auto;padding:0 20px;background:#f3f6fa;color:#182334}h1{font-size:30px}button{padding:12px;margin:5px;border:1px solid #9ab;border-radius:7px;background:white;cursor:pointer}pre{white-space:pre-wrap;background:white;padding:20px;border-radius:10px}.note{padding:15px;background:#fff2c9;border-radius:8px}</style>
<h1>Разрешение с проверкой доказательств</h1><p class="note">Только синтетический локальный сценарий. Ключи тестовые. Публикации данных нет.</p>
<p>Потребитель ожидает рубли; производитель переходит на копейки. Проверяется миграция value / 100.</p>
<button data-action="authorize">Проверить и записать решение</button><button data-action="approve">Подтвердить от тестовых владельцев</button>
<button data-action="revoke">Отозвать подтверждение потребителя</button><button data-action="restart">Перечитать журнал после перезапуска</button>
<p>После отзыва ранее выданное разрешение остается историческим фактом. Новое разрешение выдаваться не должно.</p>
<pre id="state" role="status">Загрузка...</pre><script>
async function show(response){let value=await response.json();document.getElementById('state').textContent=JSON.stringify(value,null,2);}
const buttons=[...document.querySelectorAll('button')];
buttons.forEach(button=>button.onclick=async()=>{buttons.forEach(b=>b.disabled=true);try{await show(await fetch('/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:button.dataset.action})}));}catch(error){document.getElementById('state').textContent=String(error);}finally{buttons.forEach(b=>b.disabled=false);}});
fetch('/state').then(show);
</script></html>'''


def create_server(directory, port=0):
    pilot = SyntheticPilot(directory)
    lock = RLock()
    class Handler(BaseHTTPRequestHandler):
        def send(self, code, body, content_type='application/json'):
            body = body.encode()
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == '/': return self.send(200, HTML, 'text/html; charset=utf-8')
            if self.path == '/state':
                with lock: return self.send(200, json.dumps(pilot.state()))
            self.send(404, '{}')

        def do_POST(self):
            expected_origin = 'http://127.0.0.1:' + str(self.server.server_port)
            if self.path != '/action' or self.headers.get('Content-Type') != 'application/json' or self.headers.get('Origin') not in (None, expected_origin):
                return self.send(403, '{"error":"unsupported local request"}')
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length < 1024: raise ValueError('invalid request size')
                value = json.loads(self.rfile.read(length))
                if set(value) != {'action'}: raise ValueError('action only')
                with lock: state = pilot.action(value['action'])
                return self.send(200, json.dumps(state))
            except (ValueError, TypeError, KeyError):
                self.send(400, '{"error":"invalid action or state requires reload"}')

        def log_message(self, *args): pass
    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--state-dir', required=True)
    parser.add_argument('--port', type=int, default=8090)
    args = parser.parse_args()
    server = create_server(args.state_dir, args.port)
    print('Synthetic pilot: http://127.0.0.1:' + str(server.server_port), flush=True)
    try: server.serve_forever()
    finally: server.server_close()
