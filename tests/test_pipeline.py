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
