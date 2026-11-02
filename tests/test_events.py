import threading
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from comfy import Comfy, ComfyError
from events import Events


class EventTests(unittest.TestCase):
    def test_notifications_coalesce_and_reconnect_gets_snapshot(self):
        events = Events()
        events.publish()
        events.publish()
        self.assertEqual(events.wait(-1, 0), 2)
        self.assertEqual(events.wait(2, 0), 2)

    def test_notification_wakes_waiter(self):
        events = Events()
        result = []
        worker = threading.Thread(target=lambda: result.append(events.wait(0, 1)))
        worker.start()
        events.publish()
        worker.join(2)
        self.assertEqual(result, [1])

    def test_history_recovers_completion_without_socket_event(self):
        client = Comfy()
        record = {'status': {'completed': True}}
        with patch.object(client, '_json', return_value={'prompt': record}):
            self.assertEqual(client.wait('prompt'), record)

    def test_history_failure_is_not_treated_as_completion(self):
        client = Comfy()
        record = {'status': {'status_str': 'error', 'messages': [
            ['execution_error', {'exception_message': 'failure'}]]}}
        with patch.object(client, '_json', return_value={'prompt': record}):
            with self.assertRaisesRegex(ComfyError, 'failure'):
                client.wait('prompt')
