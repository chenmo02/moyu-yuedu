#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
摸鱼阅读器 · 单文件版

双击即用，不需要装 Python。首次运行会问一次要不要把地址伪装成
    https://chat.deepseek6.com/a/chat/s/<uuid>
同意的话会请求一次管理员权限，做三件事（都只做一次）：
    1. hosts 里加 127.0.0.1 chat.deepseek6.com
    2. 把本地 CA 装进「受信任的根证书颁发机构」
    3. 把域名加进系统代理的绕过列表（没开代理就跳过）
不同意 / 没有管理员权限，就退化成 http://127.0.0.1:8765/... 打开，功能一样。

命令行：
    MoyuReader.exe            正常启动
    MoyuReader.exe --setup    只做配置（由提权后的自己调用）
    MoyuReader.exe --reset    清掉配置和本地缓存
"""
import base64
import ctypes
import hashlib
import json
import os
import socket
import ssl
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from txt_tools import handle_txt_request
from book_sources import handle_source_request

APP_NAME = 'MoyuReader'
DOMAIN = 'chat.deepseek6.com'
HTTPS_PORT = 443
FALLBACK_PORT = 8765
NO_WINDOW = 0x08000000 if os.name == 'nt' else 0


# --------------------------------------------------------------------------
# 路径
# --------------------------------------------------------------------------
def res(*parts):
    """打包后资源在临时解包目录里"""
    base = getattr(sys, '_MEIPASS', None)
    if not base:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, *parts)


def data(*parts):
    """可变数据放 %LOCALAPPDATA%，不放临时目录（每次运行都会变）"""
    base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    d = os.path.join(base, APP_NAME)
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        d = os.path.dirname(os.path.abspath(sys.executable))
    return os.path.join(d, *parts)


PAGE = res('index.html')
CERT = res('cert', 'site.pem')
KEY = res('cert', 'site.key')
CA = res('cert', 'ca.crt')
DEFAULT_ID = res('chatid.txt')

IDFILE = data('chatid.txt')
DUMP = data('dump.json')
FLAG = data('migrated.flag')
SETUP_OK = data('setup.ok')


def pem_to_der(path):
    with open(path, 'r', encoding='utf-8') as f:
        body = ''.join(l for l in f.read().splitlines() if l and not l.startswith('-----'))
    return base64.b64decode(body)


THUMB = hashlib.sha1(pem_to_der(CA)).hexdigest().upper()


def chat_id():
    try:
        with open(IDFILE, 'r', encoding='utf-8') as f:
            v = f.read().strip()
        if len(v) >= 32:
            return v
    except OSError:
        pass
    v = ''
    try:
        with open(DEFAULT_ID, 'r', encoding='utf-8') as f:
            v = f.read().strip()
    except OSError:
        pass
    if len(v) < 32:
        v = str(uuid.uuid4())
    try:
        with open(IDFILE, 'w', encoding='utf-8') as f:
            f.write(v)
    except OSError:
        pass
    return v


CHAT_ID = chat_id()
PATH = '/a/chat/s/' + CHAT_ID


def site_url(port=HTTPS_PORT):
    return 'https://%s%s%s' % (DOMAIN, '' if port == 443 else ':%d' % port, PATH)


def local_url(port=FALLBACK_PORT):
    return 'http://127.0.0.1:%d%s' % (port, PATH)


# --------------------------------------------------------------------------
# 弹窗
# --------------------------------------------------------------------------
def ask(msg, title='摸鱼阅读器'):
    return ctypes.windll.user32.MessageBoxW(None, msg, title, 0x04 | 0x20) == 6


def info(msg, title='摸鱼阅读器'):
    ctypes.windll.user32.MessageBoxW(None, msg, title, 0x40)


# --------------------------------------------------------------------------
# 配置检测 / 执行
# --------------------------------------------------------------------------
def hosts_ok():
    try:
        return socket.gethostbyname(DOMAIN) == '127.0.0.1'
    except OSError:
        return False


def cert_trusted():
    import winreg
    tail = r'\Certificates\\' + THUMB
    for root, base in ((winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\SystemCertificates\Root'),
                       (winreg.HKEY_CURRENT_USER, r'Software\Microsoft\SystemCertificates\Root')):
        try:
            k = winreg.OpenKey(root, base + tail)
            winreg.CloseKey(k)
            return True
        except OSError:
            continue
    return False


def proxy_ok():
    import winreg
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r'Software\Microsoft\Windows\CurrentVersion\Internet Settings')
        v, _ = winreg.QueryValueEx(k, 'ProxyOverride')
        winreg.CloseKey(k)
    except OSError:
        return True
    return DOMAIN in str(v)


def set_proxy():
    """代理绕过不需要管理员，当前用户就能写"""
    import winreg
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r'Software\Microsoft\Windows\CurrentVersion\Internet Settings',
                           0, winreg.KEY_READ | winreg.KEY_WRITE)
        try:
            cur, _ = winreg.QueryValueEx(k, 'ProxyOverride')
        except OSError:
            cur = '<local>'
        cur = str(cur)
        if DOMAIN not in cur:
            new = cur.rstrip(';') + ';' + DOMAIN + ';*.' + DOMAIN
            winreg.SetValueEx(k, 'ProxyOverride', 0, winreg.REG_SZ, new)
        winreg.CloseKey(k)
        return True
    except OSError:
        return False


def run_setup():
    """提权后执行：改 hosts + 装证书"""
    ok = True
    hosts = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'),
                         'System32', 'drivers', 'etc', 'hosts')
    try:
        with open(hosts, 'r', encoding='utf-8', errors='ignore') as f:
            txt = f.read()
        if DOMAIN not in txt:
            with open(hosts, 'a', encoding='utf-8') as f:
                f.write('\n# %s\n127.0.0.1\t%s\n' % (APP_NAME, DOMAIN))
    except OSError:
        ok = False
    try:
        subprocess.run(['certutil', '-addstore', '-f', 'Root', CA],
                       capture_output=True, timeout=60, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        ok = False
    try:
        subprocess.run(['ipconfig', '/flushdns'], capture_output=True,
                       timeout=20, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        pass
    if ok and hosts_ok() and cert_trusted():
        try:
            with open(SETUP_OK, 'w', encoding='utf-8') as f:
                f.write('1')
        except OSError:
            pass
        return 0
    return 1


def elevate_setup():
    try:
        os.remove(SETUP_OK)
    except OSError:
        pass
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(None, 'runas', sys.executable, '--setup', None, 1)
    except OSError:
        return False
    if rc <= 32:          # 用户点了「否」
        return False
    for _ in range(180):
        if os.path.exists(SETUP_OK):
            return True
        time.sleep(0.5)
    return False


# --------------------------------------------------------------------------
# 服务
# --------------------------------------------------------------------------
MIGRATE_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>DeepSeek</title></head><body style="margin:0;background:#fff">
<script>
(function(){
  var NEXT = %s;
  function finish(){ location.replace(NEXT); }
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
            await fetch('/__dump', {method:'POST', body: JSON.stringify({books: books, texts: texts, sources: sources, ls: ls}),
                                    headers:{'Content-Type':'application/json'}});
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
    next_url = site_url()

    def _send(self, data, ctype, code=200):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
        self.end_headers()
        self.wfile.write(data)

    def _file(self, path, ctype):
        try:
            with open(path, 'rb') as f:
                data = f.read()
        except OSError:
            self.send_error(404, 'not found')
            return
        self._send(data, ctype)

    def do_GET(self):
        if self.path.startswith('/__dump'):
            try:
                with open(DUMP, 'rb') as f:
                    self._send(f.read(), 'application/json')
            except OSError:
                self._send(b'{}', 'application/json', 404)
            return
        if self.path.startswith('/__migrate'):
            self._send((MIGRATE_PAGE % json.dumps(self.next_url)).encode('utf-8'),
                       'text/html; charset=utf-8')
            return
        if self.path.startswith('/favicon'):
            # 页面里用的是内联 SVG 图标，这里只要别 404 就行
            self._send(b'', 'image/x-icon', 204)
            return
        self._file(PAGE, 'text/html; charset=utf-8')

    def do_HEAD(self):
        self._file(PAGE, 'text/html; charset=utf-8')

    def do_POST(self):
        if handle_source_request(self, self._send):
            return
        if handle_txt_request(self, self._send):
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
            if not json.loads(body.decode('utf-8')).get('books'):
                self._send(b'{"ok":0}', 'application/json', 400)
                return
        except (ValueError, UnicodeDecodeError):
            self._send(b'{"ok":0}', 'application/json', 400)
            return
        try:
            with open(DUMP, 'wb') as f:
                f.write(body)
            with open(FLAG, 'w', encoding='utf-8') as f:
                f.write('1')
        except OSError:
            pass
        self._send(b'{"ok":1}', 'application/json')

    def log_message(self, fmt, *args):
        pass


class Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def is_running(port=HTTPS_PORT):
    """端口上已经是我们自己了？（双击第二次只开浏览器）"""
    try:
        ctx = ssl._create_unverified_context()
        raw = socket.create_connection(('127.0.0.1', port), 0.5)
        s = ctx.wrap_socket(raw, server_hostname=DOMAIN)
        s.sendall(('GET / HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n' % DOMAIN).encode())
        data = b''
        while len(data) < 4096:
            c = s.recv(2048)
            if not c:
                break
            data += c
        s.close()
        return b'DeepSeek' in data
    except (OSError, ssl.SSLError):
        return False


def main():
    if '--setup' in sys.argv:
        return run_setup()

    no_open = '--no-open' in sys.argv
    force_local = '--local' in sys.argv
    port = HTTPS_PORT
    if '--port' in sys.argv:
        try:
            port = int(sys.argv[sys.argv.index('--port') + 1])
        except (IndexError, ValueError):
            pass

    if '--reset' in sys.argv:
        for p in (IDFILE, DUMP, FLAG, SETUP_OK):
            try:
                os.remove(p)
            except OSError:
                pass
        info('本地缓存已清空。\n（hosts / 证书 需要手动删：\n'
             '  hosts 里删掉 %s 那行\n'
             '  certmgr.msc → 受信任的根证书颁发机构 → 删除 DeepSeek Local CA）' % DOMAIN)
        return 0

    if not force_local and is_running(port):
        if not no_open:
            webbrowser.open(site_url())
        return 0

    configured = (not force_local) and hosts_ok() and cert_trusted()
    if not force_local and not configured:
        if ask('要把地址伪装成\n\n    https://%s/a/chat/s/…\n\n'
               '需要管理员权限做一次性配置（hosts + 本地证书）。\n'
               '选「否」就用 http://127.0.0.1:%d 打开，功能一样。'
               % (DOMAIN, FALLBACK_PORT)):
            if elevate_setup():
                configured = hosts_ok() and cert_trusted()
            if not configured:
                info('配置没成功（可能取消了管理员授权），这次先用本地地址打开。')

    if configured:
        set_proxy()

    httpd = None
    url = local_url()
    if configured:
        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(CERT, KEY)
            httpd = Server(('0.0.0.0', port), Handler)
            httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
            Handler.next_url = site_url(port)
            url = site_url(port)
        except (OSError, ssl.SSLError):
            httpd = None
    if httpd is None:
        try:
            httpd = Server(('127.0.0.1', FALLBACK_PORT), Handler)
        except OSError:
            info('端口被占用，启动失败。')
            return 1
        Handler.next_url = local_url()
        url = local_url()

    threading.Timer(0.9, lambda: None if no_open else webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
