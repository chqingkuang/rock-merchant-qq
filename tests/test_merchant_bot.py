import logging
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import rock_merchant_bot as bot


CHINA_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


class MerchantBotTests(unittest.TestCase):
    def setUp(self):
        self.rare_config = bot.DEFAULT_CONFIG["rare"]
        self.now = datetime(2026, 6, 15, 12, 5, tzinfo=CHINA_TZ)

    def test_active_batch_number(self):
        self.assertEqual(bot.active_batch_number(self.now), 2)
        self.assertIsNone(
            bot.active_batch_number(
                datetime(2026, 6, 15, 7, 59, tzinfo=CHINA_TZ)
            )
        )

    def test_rare_detection_uses_source_flag_and_keywords(self):
        self.assertTrue(
            bot.item_is_rare(
                {"name": "国王球", "is_worth": "1", "tags": ""},
                self.rare_config,
            )
        )
        self.assertTrue(
            bot.item_is_rare(
                {"name": "测试棱镜道具", "is_worth": "0", "tags": ""},
                self.rare_config,
            )
        )
        self.assertFalse(
            bot.item_is_rare(
                {"name": "普通矿石", "is_worth": "0", "tags": "随处可见"},
                self.rare_config,
            )
        )

    def test_message_highlights_rare_items(self):
        batch = bot.MerchantBatch(
            batch=2,
            items=[
                {
                    "name": "炫彩蛋",
                    "is_worth": "1",
                    "price": "100000",
                    "buy_limit": "1",
                    "tags": "超级稀有|露头就秒",
                },
                {
                    "name": "普通矿石",
                    "is_worth": "0",
                    "price": "100",
                    "buy_limit": "0",
                    "tags": "",
                },
            ],
        )
        message = bot.format_message(batch, self.now, self.rare_config)
        self.assertIn("★ 炫彩蛋", message)
        self.assertIn("100,000洛克贝", message)
        self.assertIn("· 普通矿石", message)
        self.assertNotIn("http", message)
        self.assertNotIn("数据更新时间", message)

    def test_full_page_parser_returns_all_products_by_batch(self):
        html = """
        <ul>
          <li class="all_show li_show show_1" data-time="1781496000">
            <div class="gitem"><em>限购100</em></div>
            <em class="shop_name">蓝晶碧玺</em>
            <em class="shop_price">价格：1000 </em>
          </li>
          <li class="all_show li_show show_2" data-time="1781510400">
            <div class="gitem"><em>限购1</em></div>
            <em class="shop_name">炫彩蛋</em>
            <em class="shop_price">价格：160w </em>
          </li>
          <li class="all_show li_show show_3 show_4" data-time="1781539200">
            <div class="gitem"><em>限购5</em></div>
            <em class="shop_name">神奇的蛋</em>
            <em class="shop_price">价格：36000 </em>
          </li>
        </ul>
        """
        batches = bot.parse_full_batches(
            html,
            {"炫彩蛋": {"id": "273", "is_worth": "1", "tags": "露头就秒"}},
        )
        self.assertEqual([len(batch.items) for batch in batches], [1, 1, 1, 1])
        self.assertEqual(batches[0].items[0]["price_text"], "1000")
        self.assertEqual(batches[0].items[0]["buy_limit"], "100")
        self.assertEqual(batches[1].items[0]["is_worth"], "1")
        self.assertEqual(batches[3].items[0]["name"], "神奇的蛋")

    def test_special_all_day_product_is_added_to_all_rounds(self):
        html = """
        <li class="all_show li_show show_1" data-time="1781539200">
          <div class="gitem"><em>限购1</em></div>
          <em class="shop_name">棱镜球</em>
          <em class="shop_price">价格：200w </em>
        </li>
        """
        batches = bot.parse_full_batches(
            html,
            {
                "棱镜球": {
                    "id": "260",
                    "is_worth": "1",
                    "tags": "超级稀有",
                    "day_batch": "0",
                }
            },
        )
        self.assertEqual([len(batch.items) for batch in batches], [1, 1, 1, 1])
        self.assertTrue(batches[3].items[0]["special_all_day"])
        message = bot.format_message(batches[1], self.now, self.rare_config)
        self.assertIn("【全天商品 08:00-24:00】", message)
        self.assertIn("★ 棱镜球", message)

    def test_weekend_attribute_ball_is_labeled_as_weekend_sale(self):
        item = {
            "name": "暗星球",
            "price_text": "3000",
            "buy_limit": "200",
            "is_worth": "0",
            "tags": "",
            "special_all_day": False,
            "covers_all_rounds": True,
        }
        message = bot.format_message(
            bot.MerchantBatch(1, [item]),
            datetime(2026, 6, 12, 8, 5, tzinfo=CHINA_TZ),
            self.rare_config,
            bot.DEFAULT_CONFIG["weekend_sale"],
        )
        self.assertIn("【周末特卖 08:00-24:00】", message)
        self.assertIn("· 暗星球  3000洛克贝 / 限购200", message)

    def test_weekend_event_items_use_activity_limit_wording(self):
        items = [
            {
                "name": "残缺魔镜",
                "price_text": "48w",
                "buy_limit": "1",
                "is_worth": "0",
                "tags": "",
                "special_all_day": False,
                "covers_all_rounds": True,
            },
            {
                "name": "适格钥匙",
                "price_text": "32w",
                "buy_limit": "1",
                "is_worth": "0",
                "tags": "",
                "special_all_day": False,
                "covers_all_rounds": True,
            },
            {
                "name": "能力钥匙",
                "price_text": "16w",
                "buy_limit": "6",
                "is_worth": "0",
                "tags": "",
                "special_all_day": False,
                "covers_all_rounds": True,
            },
        ]
        message = bot.format_message(
            bot.MerchantBatch(2, items),
            datetime(2026, 6, 12, 12, 5, tzinfo=CHINA_TZ),
            self.rare_config,
            bot.DEFAULT_CONFIG["weekend_sale"],
        )
        self.assertIn("【周末特卖 08:00-24:00】", message)
        self.assertIn(
            "· 残缺魔镜  48w洛克贝 / 活动限购1",
            message,
        )
        self.assertIn(
            "· 适格钥匙  32w洛克贝 / 活动限购1",
            message,
        )
        self.assertIn(
            "· 能力钥匙  16w洛克贝 / 活动限购6",
            message,
        )
        self.assertNotIn("购买后不刷新", message)

    def test_weekend_sale_label_is_only_used_friday_through_sunday(self):
        item = {
            "name": "暗星球",
            "price_text": "3000",
            "buy_limit": "200",
            "is_worth": "0",
            "tags": "",
            "special_all_day": False,
            "covers_all_rounds": True,
        }
        message = bot.format_message(
            bot.MerchantBatch(1, [item]),
            datetime(2026, 6, 15, 8, 5, tzinfo=CHINA_TZ),
            self.rare_config,
            bot.DEFAULT_CONFIG["weekend_sale"],
        )
        self.assertNotIn("【周末特卖 08:00-24:00】", message)

    def test_excluded_special_all_day_ball_is_not_mislabeled_as_weekend_sale(self):
        item = {
            "name": "棱镜球",
            "price_text": "3000",
            "buy_limit": "1",
            "is_worth": "0",
            "tags": "",
            "special_all_day": True,
            "covers_all_rounds": True,
        }
        message = bot.format_message(
            bot.MerchantBatch(1, [item]),
            datetime(2026, 6, 12, 8, 5, tzinfo=CHINA_TZ),
            self.rare_config,
            bot.DEFAULT_CONFIG["weekend_sale"],
        )
        self.assertNotIn("【周末特卖 08:00-24:00】", message)
        self.assertIn("【全天商品 08:00-24:00】", message)

    def test_weekend_event_item_with_special_all_day_flag_is_weekend_sale(self):
        item = {
            "name": "残缺魔镜",
            "price_text": "48w",
            "buy_limit": "1",
            "is_worth": "1",
            "tags": "",
            "special_all_day": True,
            "covers_all_rounds": True,
        }
        message = bot.format_message(
            bot.MerchantBatch(1, [item]),
            datetime(2026, 6, 28, 8, 5, tzinfo=CHINA_TZ),
            self.rare_config,
            bot.DEFAULT_CONFIG["weekend_sale"],
        )
        self.assertIn("【周末特卖 08:00-24:00】", message)
        self.assertIn("活动限购1", message)
        self.assertNotIn("【全天商品 08:00-24:00】", message)

    def test_state_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            bot.save_state(path, {"sent": ["abc"]})
            self.assertEqual(bot.load_state(path)["sent"], ["abc"])

    def test_qq_target_ids_supports_multiple_and_legacy_targets(self):
        targets = bot.qq_target_ids(
            {
                "target_ids": ["100000001", "100000002"],
                "target_id": "100000001",
            }
        )
        self.assertEqual(targets, ["100000001", "100000002"])

    def test_send_qq_message_sends_to_every_target(self):
        qq_config = {
            "enabled": True,
            "base_url": "http://127.0.0.1:3000",
            "access_token": "token",
            "target_type": "private",
            "target_ids": ["100000001", "100000002"],
        }
        with patch.object(
            bot, "request_json", return_value={"status": "ok", "retcode": 0}
        ) as request:
            bot.send_qq_message(qq_config, "message")
        self.assertEqual(request.call_count, 2)
        self.assertEqual(
            [call.kwargs["payload"]["user_id"] for call in request.call_args_list],
            [100000001, 100000002],
        )

    def test_extract_subscription_request_accepts_private_friend_command(self):
        contact = {
            "chatType": 1,
            "peerUin": "123456",
            "msgId": "msg-1",
            "msgTime": "1781612000",
            "lastestMsg": {
                "post_type": "message",
                "message_type": "private",
                "user_id": 123456,
                "self_id": 100000003,
                "time": 1781612000,
                "raw_message": " 开启推送 ",
            },
        }
        result = bot.extract_subscription_request(
            contact, bot.DEFAULT_CONFIG["subscription_commands"]
        )
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "123456")

    def test_process_subscription_commands_adds_new_target(self):
        config = bot.deep_merge(
            bot.DEFAULT_CONFIG,
            {
                "qq": {
                    "enabled": True,
                    "base_url": "http://127.0.0.1:3000",
                    "access_token": "token",
                    "target_type": "private",
                    "target_ids": ["100000001"],
                },
            },
        )
        contacts = [
            {
                "chatType": 1,
                "peerUin": "123456",
                "msgId": "msg-1",
                "msgTime": "1781612000",
                "lastestMsg": {
                    "post_type": "message",
                    "message_type": "private",
                    "user_id": 123456,
                    "self_id": 100000003,
                    "time": 1781612000,
                    "raw_message": "开启推送",
                },
            }
        ]
        logger = logging.getLogger("test_process_subscription_commands")
        with patch.object(
            bot, "qq_request", return_value={"status": "ok", "retcode": 0, "data": contacts}
        ), patch.object(bot, "send_private_message_to_target") as send:
            added = bot.process_subscription_commands(config, {}, None, logger)
        self.assertEqual(added, ["123456"])
        self.assertEqual(bot.qq_target_ids(config["qq"]), ["100000001", "123456"])
        send.assert_called_once()

    def test_select_active_batch(self):
        batches = [
            bot.MerchantBatch(batch=1, items=[]),
            bot.MerchantBatch(batch=2, items=[{"name": "炫彩蛋"}]),
        ]
        selected = bot.select_active_batch(batches, self.now)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.batch, 2)

    def test_merge_batch_sources_adds_api_only_all_day_item(self):
        primary = [
            bot.MerchantBatch(1, [{"name": "冰系粉尘"}]),
            bot.MerchantBatch(2, []),
            bot.MerchantBatch(3, []),
            bot.MerchantBatch(4, []),
        ]
        secondary = [
            bot.MerchantBatch(
                1,
                [
                    {
                        "name": "冰系粉尘",
                        "special_all_day": False,
                        "covers_all_rounds": False,
                    },
                    {
                        "name": "美妙球",
                        "special_all_day": True,
                        "covers_all_rounds": True,
                    },
                ],
            ),
            bot.MerchantBatch(
                2,
                [
                    {
                        "name": "美妙球",
                        "special_all_day": True,
                        "covers_all_rounds": True,
                    }
                ],
            ),
            bot.MerchantBatch(3, []),
            bot.MerchantBatch(4, []),
        ]
        merged = bot.merge_batch_sources(primary, secondary)
        self.assertEqual(
            [item["name"] for item in merged[0].items],
            ["冰系粉尘", "美妙球"],
        )
        self.assertEqual([item["name"] for item in merged[1].items], ["美妙球"])

    def test_run_once_deduplicates_successful_push(self):
        batch = bot.MerchantBatch(
            batch=2,
            items=[
                {
                    "id": "273",
                    "name": "炫彩蛋",
                    "is_worth": "1",
                    "price": "100000",
                    "buy_limit": "1",
                    "tags": "露头就秒",
                }
            ],
        )
        logger = logging.getLogger("test_run_once")
        with tempfile.TemporaryDirectory() as temp_dir:
            config = bot.deep_merge(
                bot.DEFAULT_CONFIG,
                {
                    "qq": {"enabled": False},
                    "monitor": {
                        "state_file": str(Path(temp_dir) / "state.json"),
                        "log_file": str(Path(temp_dir) / "bot.log"),
                    },
                },
            )
            with patch.object(bot, "fetch_batches", return_value=[batch]):
                self.assertTrue(bot.run_once(config, logger, now=self.now))
                self.assertFalse(bot.run_once(config, logger, now=self.now))

    def test_low_power_mode_skips_fetch_after_batch_was_sent(self):
        logger = logging.getLogger("test_low_power_mode")
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            bot.save_state(
                state_path,
                {
                    "sent": [],
                    "last_sent_date": self.now.date().isoformat(),
                    "last_batch": 2,
                },
            )
            config = bot.deep_merge(
                bot.DEFAULT_CONFIG,
                {
                    "qq": {"enabled": False},
                    "monitor": {
                        "state_file": str(state_path),
                        "log_file": str(Path(temp_dir) / "bot.log"),
                        "low_power_mode": True,
                    },
                },
            )
            with patch.object(bot, "fetch_batches") as fetch:
                self.assertFalse(bot.run_once(config, logger, now=self.now))
            fetch.assert_not_called()

    def test_run_once_waits_when_new_batch_only_has_all_day_items(self):
        logger = logging.getLogger("test_run_once_waits_for_regular_items")
        batch = bot.MerchantBatch(
            1,
            [
                {
                    "name": "残缺魔镜",
                    "special_all_day": True,
                    "covers_all_rounds": True,
                }
            ],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            config = bot.deep_merge(
                bot.DEFAULT_CONFIG,
                {
                    "qq": {"enabled": False},
                    "monitor": {
                        "state_file": str(Path(temp_dir) / "state.json"),
                        "log_file": str(Path(temp_dir) / "bot.log"),
                        "min_batch_age_minutes": 3,
                    },
                },
            )
            with patch.object(bot, "fetch_batches", return_value=[batch]):
                self.assertFalse(
                    bot.run_once(
                        config,
                        logger,
                        now=datetime(2026, 6, 28, 8, 0, tzinfo=CHINA_TZ),
                    )
                )


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    unittest.main()
