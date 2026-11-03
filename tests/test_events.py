import threading
import sys
from pathlib import Path
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from comfy import Comfy, ComfyError
from events import Events
import studio


class EventTests(unittest.TestCase):
    def test_socket_without_context_manager_connects_and_closes(self):
        class StopListener(BaseException):
            pass
        connection = SimpleNamespace(recv=Mock(side_effect=StopListener), close=Mock())
        dependency = SimpleNamespace(create_connection=Mock(return_value=connection), WebSocketTimeoutException=TimeoutError)
        client = Comfy()
        with patch('comfy.websocket', dependency), self.assertRaises(StopListener):
            client._listen()
        self.assertEqual(client.event_status()['connections'], 1)
        connection.close.assert_called_once()

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

    def test_progress_is_coalesced_and_does_not_request_history(self):
        client = Comfy()
        received = []
        client.on_event = received.append
        with patch('comfy.time.monotonic', side_effect=[1.0, 1.1, 1.3]):
            for value in range(3):
                client._receive_event({'type': 'progress', 'data': {'prompt_id': 'a', 'value': value}})
        self.assertEqual([event['data']['value'] for event in received], [0, 2])
        self.assertEqual(client._event_revision, 0)
        self.assertEqual(client._terminal_revisions, {})

    def test_terminal_event_is_not_lost_in_progress_burst(self):
        client = Comfy()
        received = []
        client.on_event = received.append
        client._receive_event({'type': 'progress', 'data': {'prompt_id': 'a', 'value': 1}})
        client._receive_event({'type': 'execution_success', 'data': {'prompt_id': 'a'}})
        client._receive_event({'type': 'executing', 'data': {'prompt_id': 'b', 'node': None}})
        self.assertEqual(client._terminal_revisions, {'a': 1, 'b': 1})
        self.assertEqual([event['type'] for event in received], ['progress', 'execution_success', 'executing'])

    def test_executing_events_are_not_throttled_like_progress(self):
        client = Comfy()
        received = []
        client.on_event = received.append
        with patch('comfy.time.monotonic', return_value=1.0):
            client._receive_event({'type':'executing', 'data':{'prompt_id':'p', 'node':'1'}})
            client._receive_event({'type':'executing', 'data':{'prompt_id':'p', 'node':'2'}})
        self.assertEqual([event['data']['node'] for event in received], ['1', '2'])

    def test_node_durations_use_only_observed_boundaries_and_safe_node_classes(self):
        worker = object.__new__(studio.Studio)
        worker.lock = threading.RLock()
        worker.events = Events()
        worker.jobs = [{'state':'running', 'timing':{}}]
        worker._comfy_event({'type':'studio_submitted', 'data':{'prompt_id':'p',
            'node_classes':{'1':'LoadImage', '2':'SamplerCustomAdvanced', '3':'sensitive prompt text'}}})
        with patch('studio.time.monotonic', side_effect=[1, 3, 8, 9]):
            for node in ('1', '2', '3', None):
                worker._comfy_event({'type':'executing', 'data':{'prompt_id':'p', 'node':node}})
        self.assertEqual(worker.jobs[0]['timing']['observed_nodes'], {
            'LoadImage':{'seconds':2, 'spans':1}, 'SamplerCustomAdvanced':{'seconds':5, 'spans':1}})

    def test_disconnect_discards_unfinished_node_span(self):
        worker = object.__new__(studio.Studio)
        worker.lock = threading.RLock()
        worker.events = Events()
        worker.jobs = [{'state':'running', 'timing':{}}]
        worker._comfy_event({'type':'studio_submitted', 'data':{'prompt_id':'p', 'node_classes':{'1':'LoadImage'}}})
        worker._comfy_event({'type':'executing', 'data':{'prompt_id':'p', 'node':'1'}})
        worker._comfy_event({'type':'studio_socket_disconnected', 'data':{}})
        worker._comfy_event({'type':'executing', 'data':{'prompt_id':'p', 'node':None}})
        self.assertNotIn('observed_nodes', worker.jobs[0]['timing'])

    def test_token_and_preview_events_do_not_publish_job_changes(self):
        client = Comfy()
        received = []
        client.on_event = received.append
        for event in ('progress_text', 'b_preview', 'status', 'executed'):
            client._receive_event({'type': event, 'data': {'prompt_id': 'a'}})
        self.assertEqual(received, [])

    def test_reconnection_is_observable_and_wakes_reconciliation(self):
        client = Comfy()
        client._connection_changed(True)
        client._connection_changed(False, 'connection reset')
        self.assertFalse(client.event_status()['connected'])
        self.assertEqual(client.event_status()['last_error'], 'connection reset')
        client._connection_changed(True)
        self.assertEqual(client.event_status()['connections'], 2)
        self.assertIsNone(client.event_status()['last_error'])
        self.assertEqual(client._event_revision, 3)

    def test_mutating_request_is_not_retried_after_ambiguous_failure(self):
        client = Comfy()
        with patch('urllib.request.urlopen', side_effect=TimeoutError) as request:
            with self.assertRaises(TimeoutError):
                client._json('/prompt', {'prompt': {}})
        self.assertEqual(request.call_count, 1)
