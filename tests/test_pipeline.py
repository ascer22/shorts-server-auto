import unittest
from datetime import datetime, timezone
from unittest.mock import patch
import pipeline

RSS = b'''<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015">
 <entry><yt:videoId>old123</yt:videoId><title>Old</title><published>2026-10-25T13:00:00Z</published></entry>
 <entry><yt:videoId>new456</yt:videoId><title>New</title><published>2026-10-28T11:00:00Z</published></entry>
</feed>'''

class PipelineTest(unittest.TestCase):
    def test_feed(self):
        items = pipeline.parse_rss(RSS)
        self.assertEqual([x['id'] for x in items], ['new456', 'old123'])
        self.assertEqual(items[0]['shorts_url'], 'https://www.youtube.com/shorts/new456')

    def test_duration_filter(self):
        self.assertTrue(pipeline.is_eligible({'duration': 72}, 180))
        self.assertFalse(pipeline.is_eligible({'duration': 400}, 180))
        self.assertFalse(pipeline.is_eligible({'duration': 72, 'live_status': 'is_live'}, 180))

    def test_schedule_today_and_tomorrow(self):
        self.assertEqual('2026-10-28T15:00:00.000Z', pipeline.next_publication(datetime(2026,10,28,8,0,tzinfo=timezone.utc)))
        self.assertEqual('2026-10-29T15:00:00.000Z', pipeline.next_publication(datetime(2026,10,28,14,45,tzinfo=timezone.utc)))

    def test_flat_short_listing(self):
        entries = [{'id': 'hp3q_LmqOnc', 'title': 'Test short', 'upload_date': '20261027'},
                   {'id': 'bad!', 'title': 'Invalid'}]
        clips = pipeline.parse_channel_playlist({'entries': entries})
        self.assertEqual(len(clips), 1)
        self.assertEqual(clips[0]['published'], '2026-10-27')

    @patch('pipeline.load_channel_via_ytdlp')
    @patch('pipeline.urlopen')
    def test_rss_404_fallback(self, open_mock, fallback_mock):
        from urllib.error import HTTPError
        open_mock.side_effect = HTTPError('https://youtube.com/rss', 404, 'Not found', {}, None)
        fallback_mock.return_value = [{'id': 'hp3q_LmqOnc'}]
        clips = pipeline.load_channel_feed('UC123', '@i11ush')
        self.assertEqual(clips[0]['id'], 'hp3q_LmqOnc')
        fallback_mock.assert_called_once_with('@i11ush')

    @patch('pipeline.load_channel_feed')
    def test_three_sources_and_no_duplicate_ids(self, mock):
        mock.side_effect = [
            [{'id': 'AAAAAAAAAAA', 'title': 'A', 'published': '2026-10-28', 'shorts_url': 'https://youtube.com/shorts/AAAAAAAAAAA'}],
            [{'id': 'BBBBBBBBBBB', 'title': 'B', 'published': '2026-10-28', 'shorts_url': 'https://youtube.com/shorts/BBBBBBBBBBB'}],
            [{'id': 'AAAAAAAAAAA', 'title': 'dup', 'published': '2026-10-28', 'shorts_url': 'https://youtube.com/shorts/AAAAAAAAAAA'},
             {'id': 'CCCCCCCCCCC', 'title': 'C', 'published': '2026-10-28', 'shorts_url': 'https://youtube.com/shorts/CCCCCCCCCCC'}],
        ]
        cfg = {'youtube_sources': [
            {'handle': '@i11ush', 'channel_id': 'UC1'},
            {'handle': '@keymood_yt'},
            {'handle': '@world_edges'},
        ]}
        found = pipeline.collect_source_shorts(cfg, {'scheduled': {}})
        self.assertEqual([v['source_handle'] for v in found], ['@i11ush', '@keymood_yt', '@world_edges'])
        self.assertEqual(len(set(v['id'] for v in found)), 3)
        self.assertEqual(mock.call_count, 3)
        self.assertEqual(mock.call_args_list[1].args, (None, '@keymood_yt'))

    @patch('pipeline.load_channel_feed')
    def test_round_robin_after_previous_post(self, mock):
        mock.side_effect = [
            [{'id': 'AAAAAAAAAAA', 'title': 'A'}],
            [{'id': 'BBBBBBBBBBB', 'title': 'B'}],
            [{'id': 'CCCCCCCCCCC', 'title': 'C'}],
        ]
        cfg = {'youtube_sources': [
            {'handle': '@i11ush'},
            {'handle': '@keymood_yt'},
            {'handle': '@world_edges'},
        ]}
        state = {'scheduled': {}, 'last_scheduled_source': '@i11ush'}
        found = pipeline.collect_source_shorts(cfg, state)
        self.assertEqual([v['source_handle'] for v in found], ['@keymood_yt', '@world_edges', '@i11ush'])

    @patch('pipeline.load_channel_feed')
    def test_failed_source_does_not_block_others(self, mock):
        mock.side_effect = [
            RuntimeError('unavailable'),
            [{'id': 'BBBBBBBBBBB', 'title': 'B'}],
            [{'id': 'CCCCCCCCCCC', 'title': 'C'}],
        ]
        cfg = {'youtube_sources': [
            {'handle': '@i11ush'},
            {'handle': '@keymood_yt'},
            {'handle': '@world_edges'},
        ]}
        found = pipeline.collect_source_shorts(cfg, {'scheduled': {}})
        self.assertEqual([v['source_handle'] for v in found], ['@keymood_yt', '@world_edges'])

    def test_cloudinary_split_secret_normalization(self):
        from unittest.mock import patch
        import os
        from verify_connections import normalize_cloudinary_url_env
        values = {"CLOUDINARY_CLOUD_NAME": "example_cloud",
                  "CLOUDINARY_API_KEY": "123456789012345",
                  "CLOUDINARY_API_SECRET": "test@secret:with#symbols"}
        with patch.dict(os.environ, values, clear=True):
            result = normalize_cloudinary_url_env()
            self.assertEqual(result, "cloudinary://123456789012345:test%40secret%3Awith%23symbols@example_cloud")
            self.assertEqual(os.environ["CLOUDINARY_URL"], result)

    @patch('pipeline.gql')
    def test_find_buffer_tiktok(self, mock):
        mock.side_effect = [
            {'account': {'organizations': [{'id': 'o1', 'name': 'One'}]}},
            {'channels': [{'id': 'c1', 'name': 'kaspy_58', 'service': 'tiktok', 'isQueuePaused': False}]},
        ]
        self.assertEqual('c1', pipeline.buffer_tiktok_channel('secret', 'kaspy_58'))

    @patch('pipeline.gql')
    def test_buffer_post_payload(self, mock):
        mock.return_value = {'createPost': {'post': {'id': 'p123'}}}
        value = pipeline.create_buffer_post('key', 'c1', 'Test "hello"', 'https://media.example/video.mp4', '2026-10-28T15:00:00.000Z', '#facts')
        self.assertEqual('p123', value)
        query = mock.call_args.args[1]
        self.assertIn('mode: customScheduled', query)
        self.assertIn('schedulingType: automatic', query)
        self.assertIn('Test \\"hello\\"', query)

    @patch('pipeline.gql')
    def test_mutation_error(self, mock):
        mock.return_value = {'createPost': {'message': 'media unavailable'}}
        with self.assertRaisesRegex(RuntimeError, 'media unavailable'):
            pipeline.create_buffer_post('key','c1','one','https://media.example/v.mp4','2026-10-29T15:00:00.000Z','#facts')

if __name__ == '__main__':
    unittest.main()
