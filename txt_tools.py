"""TXT files explicitly selected in the local Windows file picker."""
import codecs
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
from urllib.parse import urlsplit


def choose_txt_file():
    class OpenFileName(ctypes.Structure):
        _fields_ = [
            ('size', wintypes.DWORD), ('owner', wintypes.HWND),
            ('instance', wintypes.HINSTANCE), ('filter', wintypes.LPCWSTR),
            ('custom_filter', wintypes.LPWSTR), ('max_custom_filter', wintypes.DWORD),
            ('filter_index', wintypes.DWORD), ('file', wintypes.LPWSTR),
            ('max_file', wintypes.DWORD), ('file_title', wintypes.LPWSTR),
            ('max_file_title', wintypes.DWORD), ('initial_dir', wintypes.LPCWSTR),
            ('title', wintypes.LPCWSTR), ('flags', wintypes.DWORD),
            ('file_offset', wintypes.WORD), ('file_extension', wintypes.WORD),
            ('default_extension', wintypes.LPCWSTR), ('custom_data', wintypes.LPARAM),
            ('hook', ctypes.c_void_p), ('template_name', wintypes.LPCWSTR),
            ('reserved', ctypes.c_void_p), ('reserved_value', wintypes.DWORD),
            ('flags_ex', wintypes.DWORD),
        ]
    dialog = ctypes.WinDLL('comdlg32', use_last_error=True)
    dialog.GetOpenFileNameW.argtypes = [ctypes.POINTER(OpenFileName)]
    dialog.GetOpenFileNameW.restype = wintypes.BOOL
    filename = ctypes.create_unicode_buffer(32768)
    options = OpenFileName()
    options.size = ctypes.sizeof(options)
    options.filter = 'TXT 文件 (*.txt)\0*.txt\0\0'
    options.file = ctypes.cast(filename, wintypes.LPWSTR)
    options.max_file = len(filename)
    options.title = '选择要搜索替换的 TXT 文件'
    options.default_extension = 'txt'
    options.flags = 0x00080000 | 0x00001000 | 0x00000800 | 0x00000008
    if dialog.GetOpenFileNameW(ctypes.byref(options)):
        return filename.value
    if dialog.CommDlgExtendedError():
        raise OSError('无法打开文件选择窗口')
    return None


def decode_txt(raw):
    for bom, encoding in [
        (codecs.BOM_UTF32_LE, 'utf-32-le'), (codecs.BOM_UTF32_BE, 'utf-32-be'),
        (codecs.BOM_UTF8, 'utf-8'),
        (codecs.BOM_UTF16_LE, 'utf-16-le'), (codecs.BOM_UTF16_BE, 'utf-16-be'),
    ]:
        if raw.startswith(bom):
            return raw[len(bom):].decode(encoding), encoding, bom
    try:
        return raw.decode('utf-8'), 'utf-8', b''
    except UnicodeDecodeError:
        return raw.decode('gb18030'), 'gb18030', b''


class TxtFiles:
    def __init__(self):
        self.files = {}
        self.lock = threading.Lock()

    def open(self):
        selected = choose_txt_file()
        if not selected:
            return {'cancelled': True}
        path = Path(selected).resolve()
        if path.suffix.lower() != '.txt':
            raise ValueError('请选择 .txt 文件')
        raw = path.read_bytes()
        text, encoding, bom = decode_txt(raw)
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.files[token] = [path, hashlib.sha256(raw).digest(), encoding, bom]
        return {'token': token, 'name': path.name, 'path': str(path),
                'text': text, 'encoding': encoding.upper()}

    def save(self, token, text):
        if not isinstance(token, str) or token not in self.files:
            raise ValueError('请重新选择 TXT 文件')
        if not isinstance(text, str):
            raise ValueError('文件内容无效')
        with self.lock:
            path, expected, encoding, bom = self.files[token]
            if hashlib.sha256(path.read_bytes()).digest() != expected:
                raise FileExistsError('文件已被其他程序修改，请重新打开后再替换')
            raw = bom + text.encode(encoding)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
                    temporary = output.name
                    output.write(raw)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, path)
            finally:
                if temporary and os.path.exists(temporary):
                    os.unlink(temporary)
            self.files[token][1] = hashlib.sha256(raw).digest()
        return {'ok': True}


TXT_FILES = TxtFiles()


def handle_txt_request(handler, send):
    if handler.path not in ('/__txt/open', '/__txt/save'):
        return False
    origin = urlsplit(handler.headers.get('Origin', ''))
    if origin.scheme not in ('http', 'https') or origin.netloc != handler.headers.get('Host'):
        handler.close_connection = True
        send(b'{"error":"Invalid origin"}', 'application/json', 403)
        return True
    try:
        size = int(handler.headers.get('Content-Length', '0'))
        if handler.headers.get_content_type() != 'application/json' or not 0 < size <= 64 * 1024 * 1024:
            handler.close_connection = True
            raise ValueError('请求格式或文件大小不支持')
        body = json.loads(handler.rfile.read(size).decode('utf-8'))
        if not isinstance(body, dict):
            raise ValueError('请求格式无效')
        result = TXT_FILES.open() if handler.path == '/__txt/open' else TXT_FILES.save(body.get('token'), body.get('text'))
        code = 200
    except FileExistsError as error:
        result, code = {'error': str(error)}, 409
    except UnicodeError:
        result, code = {'error': '当前编码无法读取或保存这些文字，请检查文件编码'}, 400
    except ValueError as error:
        result, code = {'error': str(error)}, 400
    except OSError:
        result, code = {'error': '无法读写文件，请检查文件权限或是否被其他程序占用'}, 400
    send(json.dumps(result, ensure_ascii=False).encode('utf-8'), 'application/json; charset=utf-8', code)
    return True
