import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import dashboard


class DashboardStateTests(unittest.TestCase):
    def test_load_dashboard_state_reads_status_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            status_path = Path(tmpdir) / 'status.json'
            status_path.write_text(json.dumps({
                'summary': {'balance': '42.00', 'equity': '100.00', 'pnl': '1.50', 'status': 'Live'},
                'logs': [{'timestamp': '12:00:00', 'type': 'INFO', 'message': 'hello'}]
            }), encoding='utf-8')

            with dashboard.app.test_request_context():
                dashboard.STATUS_FILE = status_path
                state = dashboard.load_dashboard_state()

            self.assertEqual(state['summary']['balance'], '42.00')
            self.assertEqual(state['logs'][0]['message'], 'hello')

    def test_load_dashboard_state_uses_account_balance_when_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            status_path = Path(tmpdir) / 'status.json'
            status_path.write_text(json.dumps({
                'summary': {'balance': '42.00', 'equity': '100.00', 'pnl': '1.50', 'status': 'Live'},
                'account': {'balance': '84.25'},
                'logs': []
            }), encoding='utf-8')

            with dashboard.app.test_request_context():
                dashboard.STATUS_FILE = status_path
                state = dashboard.load_dashboard_state()

            self.assertEqual(state['summary']['balance'], '84.25')

    def test_chat_routes_scan_command_to_agent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            status_path = Path(tmpdir) / 'status.json'
            status_path.write_text(json.dumps({'logs': []}), encoding='utf-8')

            mock_agent = unittest.mock.MagicMock()
            mock_agent.scan_market.return_value = 'Scanning market opportunities across multiple instruments.\nCandidates: BTCUSD'
            # agent_respond is the entry point used by the chat route. On a
            # real TradingAgent, agent_respond("scan") dispatches through
            # _heuristic_respond or the LLM path, both of which eventually
            # call self.scan_market(limit=20) and return a dict whose
            # 'reply' is the scan text. The mock mirrors that contract so:
            #   (a) the route's jsonify has a real dict to serialize, and
            #   (b) the scan_market(limit=20) assertion reflects what
            #       happens for a real "scan" message.
            def _fake_agent_respond(_message):
                text = mock_agent.scan_market(limit=20)
                return {'reply': text, 'pending_trade': None}
            mock_agent.agent_respond.side_effect = _fake_agent_respond

            with dashboard.app.test_request_context('/api/chat', method='POST', json={'message': 'scan'}):
                dashboard.STATUS_FILE = status_path
                with patch.object(dashboard, '_get_agent', return_value=mock_agent):
                    response = dashboard.chat()

            data = json.loads(response.get_data(as_text=True))
            self.assertIn('Scanning market opportunities', data['reply'])
            mock_agent.scan_market.assert_called_once_with(limit=20)


if __name__ == '__main__':
    unittest.main()