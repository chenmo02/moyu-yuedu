#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
把 index.html 跑成本地 https 站点，地址栏显示成：

    https://chat.deepseek6.com/a/chat/s/<uuid>

一次性依赖（已经装好了，换机器时照做）：
  1. hosts 里把 chat.deepseek6.com 指到 127.0.0.1
  2. cert/ca.crt 装进「当前用户的受信任根证书颁发机构」：
         certutil -user -addstore -f Root cert\\ca.crt

用法：
    pythonw server.py              # 后台静默启动，自动开浏览器
    python  server.py --no-open    # 只起服务
    set DSR_DOMAIN=...             # 换域名（证书要重签）
    set DSR_HTTPS_PORT=8443        # 443 被占时换端口（地址栏会带端口）

迁移：换域名/协议 = 换 origin，浏览器里的书架和进度不会跟过来。
首次启动会先打开旧地址的 /__migrate，把旧源的书架打包上传到 /__dump，
再跳到新地址自动恢复；成功后写 migrated.flag，之后直接开新地址。
"""
import json
import os
import socket
import ssl
import sys
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from txt_tools import handle_txt_request
from book_sources import handle_source_request

ROOT = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(ROOT, 'index.html')
CERT = os.path.join(ROOT, 'cert', 'site.pem')
KEY = os.path.join(ROOT, 'cert', 'site.key')
IDFILE = os.path.join(ROOT, 'chatid.txt')
DUMP = os.path.join(ROOT, 'dump.json')
FLAG = os.path.join(ROOT, 'migrated.flag')

DOMAIN = os.environ.get('DSR_DOMAIN', 'chat.deepseek6.com')
HTTPS_PORT = int(os.environ.get('DSR_HTTPS_PORT', '443'))
HTTP_PORT = int(os.environ.get('DSR_HTTP_PORT', '80'))
HOST = os.environ.get('DSR_HOST', '')


def chat_id():
    """会话 id 固定下来，别每次重启都变"""
    try:
        with open(IDFILE, 'r', encoding='utf-8') as f:
            v = f.read().strip()
        if len(v) >= 32:
            return v
    except OSError:
        pass
    v = str(uuid.uuid4())
    try:
        with open(IDFILE, 'w', encoding='utf-8') as f:
            f.write(v)
    except OSError:
        pass
    return v


CHAT_ID = chat_id()
PATH = '/a/chat/s/' + CHAT_ID


def site_url(port=None):
    p = HTTPS_PORT if port is None else port
    return 'https://%s%s%s' % (DOMAIN, '' if p == 443 else ':%d' % p, PATH)


def pick_host():
    """挑一个最像内网系统的本机地址：172.16/12 > 10/8 > 192.168/16 > 127.0.0.1"""
    if HOST:
        return HOST
    cands = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in cands:
                cands.append(ip)
    except OSError:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        if ip not in cands:
            cands.append(ip)
        s.close()
    except OSError:
        pass

    def score(ip):
        if ip.startswith('172.') and 16 <= int(ip.split('.')[1]) <= 31:
            return 0
        if ip.startswith('10.'):
            return 1
        if ip.startswith('192.168.'):
            return 2
        return 9

    cands = [ip for ip in cands if not ip.startswith('127.')]
    if not cands:
        return '127.0.0.1'
    return sorted(cands, key=score)[0]


MIGRATE_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>DeepSeek</title></head><body style="margin:0;background:#fff">
<script>
(function(){
  var NEXT = %s;
  function finish(){ location.replace(NEXT); }
  function post(body){
    return fetch('/__dump', {method:'POST', body: body, headers:{'Content-Type':'application/json'}});
  }
  function all(db, name){
    return new Promise(function(res){
      var q = db.transaction(name, 'readonly').objectStore(name).getAll();
      q.onsuccess = function(){ res(q.result || []); };
      q.onerror = function(){ res([]); };
    });
  }
  (async function(){
    try{
      var names = [];
      if (indexedDB.databases){
        var dbs = await indexedDB.databases();
        names = dbs.map(function(d){ return d.name; });
      }
      if (names.indexOf('dsreader') >= 0){
        var db = await new Promise(function(res, rej){
          var q = indexedDB.open('dsreader');
          q.onsuccess = function(){ res(q.result); };
          q.onerror = function(){ rej(q.error); };
        });
        if (db.objectStoreNames.contains('books')){
          var books = await all(db, 'books');
          if (books.length){
            var texts = db.objectStoreNames.contains('texts') ? await all(db, 'texts') : [];
            var sources = db.objectStoreNames.contains('sources') ? await all(db, 'sources') : [];
            var ls = {};
            for (var i = 0; i < localStorage.length; i++){
              var k = localStorage.key(i);
              if (k.indexOf('dsr:') === 0) ls[k] = localStorage.getItem(k);
            }
            await post(JSON.stringify({books: books, texts: texts, sources: sources, ls: ls}));
          }
        }
      }
    } catch(e){}
    finish();
  })();
})();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = 'nginx'
    sys_version = ''
    protocol_version = 'HTTP/1.1'
    plain = False          # 走 80 明文端口时为 True

    def _send_bytes(self, data, ctype, code=200, extra=None):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path, ctype):
        try:
            with open(path, 'rb') as f:
                data = f.read()
        except OSError:
            self.send_error(404, 'not found')
            return
        self._send_bytes(data, ctype)

    def do_GET(self):
        # 迁移完成后再从旧明文地址进来，直接送去新地址，避免看到一份旧数据
        if self.plain and os.path.exists(FLAG) and not self.path.startswith('/__'):
            self.send_response(301)
            self.send_header('Location', site_url())
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        if self.path.startswith('/__dump'):
            try:
                with open(DUMP, 'rb') as f:
                    data = f.read()
            except OSError:
                self._send_bytes(b'{}', 'application/json', 404)
                return
            self._send_bytes(data, 'application/json')
            return
        if self.path.startswith('/__migrate'):
            body = (MIGRATE_PAGE % json.dumps(site_url())).encode('utf-8')
            self._send_bytes(body, 'text/html; charset=utf-8')
            return
        if self.path.startswith('/favicon'):
            # 页面用的是内联 SVG 图标，这里只要不 404 就行
            self._send_bytes(b'', 'image/x-icon', 204)
            return
        # 其余任意路径都返回页面（刷新、粘贴任意深链都不会 404）
        self._send_file(PAGE, 'text/html; charset=utf-8')

    def do_HEAD(self):
        self._send_file(PAGE, 'text/html; charset=utf-8')

    def do_POST(self):
        if handle_source_request(self, self._send_bytes):
            return
        if handle_txt_request(self, self._send_bytes):
            return
        if not self.path.startswith('/__dump'):
            self.send_error(404, 'not found')
            return
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            n = 0
        body = self.rfile.read(n) if n > 0 else b''
        try:
            obj = json.loads(body.decode('utf-8'))
            if not obj.get('books'):
                self._send_bytes(b'{"ok":0}', 'application/json', 400)
                return
        except (ValueError, UnicodeDecodeError):
            self._send_bytes(b'{"ok":0}', 'application/json', 400)
            return
        with open(DUMP, 'wb') as f:
            f.write(body)
        try:
            with open(FLAG, 'w', encoding='utf-8') as f:
                f.write('1')
        except OSError:
            pass
        self._send_bytes(b'{"ok":1}', 'application/json')

    def log_message(self, fmt, *args):
        pass


class PlainHandler(Handler):
    plain = True


class Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def is_ours(port):
    """端口上跑的是不是我们自己（避免重复启动）"""
    try:
        ctx = ssl._create_unverified_context()
        raw = socket.create_connection(('127.0.0.1', port), 0.6)
        s = ctx.wrap_socket(raw, server_hostname=DOMAIN)
        s.sendall(('GET / HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n' % DOMAIN).encode())
        data = b''
        while len(data) < 8192:
            chunk = s.recv(2048)
            if not chunk:
                break
            data += chunk
        s.close()
        return b'DeepSeek' in data
    except (OSError, ssl.SSLError):
        return False


def serve_http():
    try:
        httpd = Server(('0.0.0.0', HTTP_PORT), PlainHandler)
    except OSError:
        return
    httpd.serve_forever()


def start_url(port):
    """还没迁移过就先走旧地址的 /__migrate，它会把书架传上来再跳新地址"""
    if not os.path.exists(FLAG):
        return 'http://%s%s/__migrate' % (pick_host(), '' if HTTP_PORT == 80 else ':%d' % HTTP_PORT)
    return site_url(port)


def main():
    if is_ours(HTTPS_PORT):
        if '--no-open' not in sys.argv:
            webbrowser.open(site_url())
        return 0

    if not (os.path.exists(CERT) and os.path.exists(KEY)):
        sys.stderr.write('missing cert: %s / %s\n' % (CERT, KEY))
        return 1

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT, KEY)

    port = HTTPS_PORT
    try:
        httpd = Server(('0.0.0.0', port), Handler)
    except OSError:
        port = 8443
        try:
            httpd = Server(('0.0.0.0', port), Handler)
        except OSError:
            sys.stderr.write('443/8443 both busy\n')
            return 1
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)

    threading.Thread(target=serve_http, daemon=True).start()

    if '--no-open' not in sys.argv:
        url = start_url(port)
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
