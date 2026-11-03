import codecs
from email.message import Message
from io import BytesIO
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import txt_tools


class TxtTests(unittest.TestCase):
    def test_round_trip_preserves_encoding_bom_and_mixed_newlines(self):
        before = '第一章\r\n张三说：你好\n张三告别\r\n'
        after = before.replace('张三', '李四')
        for encoding, bom in [('utf-8', b''), ('utf-8', codecs.BOM_UTF8),
                              ('gb18030', b''), ('utf-16-le', codecs.BOM_UTF16_LE),
                              ('utf-16-be', codecs.BOM_UTF16_BE)]:
            with self.subTest(encoding=encoding, bom=bom), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / '小说.txt'
                path.write_bytes(bom + before.encode(encoding))
                files = txt_tools.TxtFiles()
                with patch.object(txt_tools, 'choose_txt_file', return_value=str(path)):
                    opened = files.open()
                self.assertEqual(opened['text'], before)
                files.save(opened['token'], after)
                self.assertEqual(path.read_bytes(), bom + after.encode(encoding))
                files.save(opened['token'], after + '继续')
                self.assertEqual(path.read_bytes(), bom + (after + '继续').encode(encoding))

    def test_external_changes_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'book.txt'
            path.write_bytes(b'original')
            files = txt_tools.TxtFiles()
            with patch.object(txt_tools, 'choose_txt_file', return_value=str(path)):
                opened = files.open()
            path.write_bytes(b'edited outside')
            with self.assertRaises(FileExistsError):
                files.save(opened['token'], 'replacement')
            self.assertEqual(path.read_bytes(), b'edited outside')

    def test_failed_save_leaves_original_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'book.txt'
            path.write_bytes(b'original')
            files = txt_tools.TxtFiles()
            with patch.object(txt_tools, 'choose_txt_file', return_value=str(path)):
                opened = files.open()
            with patch.object(txt_tools.os, 'replace', side_effect=PermissionError), self.assertRaises(PermissionError):
                files.save(opened['token'], 'replacement')
            self.assertEqual(path.read_bytes(), b'original')
            self.assertEqual(list(Path(folder).iterdir()), [path])

    def test_only_selected_files_can_be_written_and_cancellation_is_empty(self):
        files = txt_tools.TxtFiles()
        with patch.object(txt_tools, 'choose_txt_file', return_value=None):
            self.assertEqual(files.open(), {'cancelled': True})
        self.assertEqual(files.files, {})
        for token in [None, '../arbitrary.txt', '/tmp/book.txt']:
            with self.assertRaises(ValueError):
                files.save(token, 'replacement')

    def test_empty_replacement_can_save_an_empty_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'book.txt'
            path.write_bytes(b'contents')
            files = txt_tools.TxtFiles()
            with patch.object(txt_tools, 'choose_txt_file', return_value=str(path)):
                opened = files.open()
            files.save(opened['token'], '')
            self.assertEqual(path.read_bytes(), b'')

    def test_cross_origin_requests_cannot_open_native_picker(self):
        headers = Message()
        headers['Origin'] = 'https://other.example'
        headers['Host'] = 'localhost:8765'
        request = SimpleNamespace(path='/__txt/open', headers=headers, rfile=BytesIO(b'{}'))
        responses = []
        with patch.object(txt_tools.TXT_FILES, 'open') as picker:
            self.assertTrue(txt_tools.handle_txt_request(request, lambda *args: responses.append(args)))
            picker.assert_not_called()
        self.assertEqual(responses[0][2], 403)


if __name__ == '__main__':
    unittest.main()
