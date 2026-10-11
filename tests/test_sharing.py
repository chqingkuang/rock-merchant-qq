import contextlib
import io
import json
import logging
from pathlib import Path, PurePosixPath
import tempfile
import threading
import unittest
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import desktop_app as app
import rock_merchant_bot as bot


class SharingTests(unittest.TestCase):
    def test_configuration_is_independent_and_deduplicated(self):
        base = bot.deep_merge(bot.DEFAULT_CONFIG, {})
        config = app.make_settings(base, "http://127.0.0.1:3000/", "example-token",
                                   "100000001，100000002,100000001", "private", True, False)
        self.assertEqual(config["qq"]["target_ids"], ["100000001", "100000002"])
        self.assertEqual(base["qq"]["target_ids"], [])
        self.assertFalse(config["subscription_commands"]["enabled"])

    def test_bad_configuration_is_rejected(self):
        for url, targets in [("127.0.0.1:3000", "100000001"),
                             ("http://user:password@localhost", "100000001"),
                             ("http://localhost", "someone"), ("http://localhost", "")]:
            with self.subTest(url=url, targets=targets), self.assertRaises(ValueError):
                app.make_settings(bot.DEFAULT_CONFIG, url, "", targets, "private", True, False)

    def test_preview_after_successful_push_does_not_send_or_modify_state(self):
        now = datetime(2026, 6, 15, 12, 5, tzinfo=bot.CHINA_TZ)
        batch = bot.MerchantBatch(2, [{"name": "示例商品", "price": "100"}])
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            state = {"sent": [], "last_sent_date": now.date().isoformat(), "last_batch": 2}
            bot.save_state(state_path, state)
            before = state_path.read_bytes()
            config = bot.deep_merge(bot.DEFAULT_CONFIG, {"monitor": {"state_file": str(state_path)}})
            with patch.object(bot, "fetch_batches", return_value=[batch]) as fetch, \
                 patch.object(bot, "send_qq_message") as send, \
                 patch.object(bot, "process_subscription_commands") as commands, \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertTrue(bot.run_once(config, logging.getLogger("preview"), preview=True, now=now))
            fetch.assert_called_once()
            send.assert_not_called()
            commands.assert_not_called()
            self.assertIn("示例商品", output.getvalue())
            self.assertEqual(before, state_path.read_bytes())

    def test_linux_units_quote_paths_and_percent_signs(self):
        service, timer = app.linux_units(PurePosixPath('/home/demo/app space%'),
                                        PurePosixPath('/home/demo/app space%/config.json'),
                                        PurePosixPath('/home/demo/app space%/RockMerchantQQ'))
        self.assertIn('WorkingDirectory=/home/demo/app space%%\n', service)
        self.assertIn('"--config" "/home/demo/app space%%/config.json" "--once"', service)
        self.assertIn("OnUnitInactiveSec=5min", timer)
        with self.assertRaises(ValueError):
            app.systemd_quote("/tmp/invalid\npath")

    def test_local_onebot_login_and_test_message_use_own_target(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requests.append((self.path, payload, self.headers.get("Authorization")))
                data = {"user_id": 100000003, "nickname": "示例机器人"} if self.path == "/get_login_info" else {"message_id": 1}
                body = json.dumps({"status": "ok", "retcode": 0, "data": data}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            config = app.make_settings(bot.DEFAULT_CONFIG,
                                       f"http://127.0.0.1:{server.server_port}", "example-token",
                                       "100000001", "private", True, False)
            self.assertIn("100000003", app.check_login(config))
            bot.send_qq_message(config["qq"], "中文测试")
            self.assertEqual(requests[1][1], {"user_id": 100000001, "message": "中文测试"})
            self.assertTrue(all(r[2] == "Bearer example-token" for r in requests))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_example_contains_no_login_or_targets(self):
        template = json.loads((app.APP_DIR / "config.example.json").read_text(encoding="utf-8"))
        self.assertEqual(template["qq"]["target_ids"], [])
        self.assertEqual(template["qq"]["target_id"], "")
        self.assertEqual(template["qq"]["access_token"], "")

    def test_private_subscription_cannot_add_a_user_id_to_group_targets(self):
        with self.assertRaises(ValueError):
            app.make_settings(bot.DEFAULT_CONFIG, "http://localhost:3000", "",
                              "100000001", "group", True, True)
        config = bot.deep_merge(bot.DEFAULT_CONFIG, {"qq": {"target_type": "group", "target_ids": ["100000001"]}})
        with patch.object(bot, "qq_request") as request:
            self.assertEqual(bot.process_subscription_commands(config, {}, None, logging.getLogger("groups")), [])
        request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
