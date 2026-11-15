"""看板远程访问（G053）：经 tailscale serve 等代理来的请求算远程，/api/open 拒绝，vocab.js 带 BOARD_REMOTE。"""
import argparse
import gzip
import http.client
import importlib.util
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
spec = importlib.util.spec_from_file_location("board_server_remote", SRC / "board" / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class IsRemote(unittest.TestCase):
    def test_local(self):
        for host in ("127.0.0.1:3100", "localhost:3100", "localhost", "[::1]:3100", ""):
            self.assertFalse(server.is_remote({"Host": host}), host)

    def test_remote(self):
        self.assertTrue(server.is_remote({"Host": "mac.tail1234.ts.net"}))
        self.assertTrue(server.is_remote({"Host": "10.91.222.84:3100"}))
        self.assertTrue(server.is_remote({"Host": "127.0.0.1:3100", "Tailscale-User-Login": "me@example.com"}))
        self.assertTrue(server.is_remote({"Host": "127.0.0.1:3100", "X-Forwarded-For": "100.64.0.2"}))
        self.assertTrue(server.is_remote({"Host": "127.0.0.1:3100"}, "100.64.0.2"))


class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.ARGS = argparse.Namespace(verbose=False, port=0, now_dir=None, project=None)
        cls.payload = {}
        cls._team = server.team_data
        server.team_data = lambda: cls.payload
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        server.team_data = cls._team

    def req(self, method, path, headers=None, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, data

    def test_vocab_flag(self):
        _, local = self.req("GET", "/static/vocab.js")
        self.assertIn(b"window.BOARD_REMOTE = false;", local)
        _, remote = self.req("GET", "/static/vocab.js", {"Host": "mac.tail1234.ts.net", "Tailscale-User-Login": "me@example.com"})
        self.assertIn(b"window.BOARD_REMOTE = true;", remote)

    def test_open_refused_remotely(self):
        body = json.dumps({"path": "/nonexistent-g053"})
        st, data = self.req("POST", "/api/open", {"X-Board": "1", "Content-Type": "application/json",
                                                  "Host": "mac.tail1234.ts.net"}, body)
        self.assertEqual(st, 403)
        self.assertEqual(json.loads(data), {"error": "remote"})
        st, _ = self.req("POST", "/api/open", {"X-Board": "1", "Content-Type": "application/json"}, body)
        self.assertEqual(st, 400)  # 本机请求照常走路径检查（不存在的路径被拒，没有真去打开）


    def test_gzip_and_etag(self):
        st, raw = self.req("GET", "/static/project.js")
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", "/static/project.js", headers={"Accept-Encoding": "gzip"})
        r = c.getresponse()
        body = r.read()
        etag = r.getheader("ETag")
        self.assertEqual(r.getheader("Content-Encoding"), "gzip")
        self.assertEqual(r.getheader("Cache-Control"), "no-cache")
        self.assertEqual(gzip.decompress(body), raw)
        c.request("GET", "/static/project.js", headers={"If-None-Match": etag})
        r = c.getresponse()
        self.assertEqual((r.status, r.read()), (304, b""))
        c.close()

    def test_etag_ignores_generated(self):
        tags = []
        for n in (1, 2):
            Http.payload = {"a": 1, "generated": f"t{n}"}
            server.CACHE.pop("team", None)  # 班子页数据按账本指纹缓存（G056-T9）；这里换的是假数据，不是文件
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            c.request("GET", "/api/team")
            r = c.getresponse()
            r.read()
            tags.append(r.getheader("ETag"))
            c.close()
        self.assertEqual(tags[0], tags[1])
        Http.payload = {"a": 2, "generated": "t3"}
        server.CACHE.pop("team", None)
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", "/api/team", headers={"If-None-Match": tags[0]})
        r = c.getresponse()
        self.assertEqual(r.status, 200)  # 内容变了必须重传
        self.assertEqual(json.loads(r.read())["a"], 2)
        c.close()


if __name__ == "__main__":
    unittest.main()
