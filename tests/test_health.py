import unittest

from app.health import evaluate


def base(**changes):
    data = {'cameras': [{'id': 'main', 'name': 'Cozinha', 'enabled': True, 'state': 'online', 'fps': 12, 'analysis_active': True}],
            'whatsapp': {'state': 'connected'}, 'whatsapp_enabled': True, 'notebook': {'state': 'ok', 'battery': 90, 'plugged': True},
            'disk_free_gb': 80, 'min_free_gb': 2, 'resources': {'cpu': 20, 'mem_used': 2, 'mem_total': 8, 'temp': 50},
            'backup': {'last_ok': 1000}, 'backup_enabled': True, 'recognition': {'ready': True},
            'failed_clips': 0, 'processing_clips': 0, 'failed_deliveries': 0, 'alerts': [], 'uptime': 10}
    data.update(changes)
    return data


class HealthTests(unittest.TestCase):
    def test_all_well(self):
        report = evaluate(base(), now=1000 + 3600)
        self.assertEqual((report['level'], report['summary']), ('ok', 'Tudo certo.'))

    def test_problems_are_ranked_worst_first_with_a_hint(self):
        report = evaluate(base(cameras=[{'id': 'main', 'name': 'Cozinha', 'enabled': True, 'state': 'offline', 'error': 'sem sinal'}],
                               whatsapp={'state': 'disconnected'}, disk_free_gb=3, notebook={'state': 'battery', 'battery': 40}), now=1000 + 3600)
        self.assertEqual(report['level'], 'error')
        self.assertEqual([i['level'] for i in report['items']][:2], ['error', 'error'])
        self.assertTrue(all(i['hint'] for i in report['items'] if i['level'] in ('warn', 'error')))
        self.assertEqual(report['counts']['error'], 2)
        self.assertEqual(report['summary'], '2 problema(s) e 2 aviso(s).')

    def test_slow_camera_hot_computer_old_backup_and_failed_videos_warn(self):
        slow = [{'id': 'main', 'name': 'Cozinha', 'enabled': True, 'state': 'online', 'fps': 2, 'analysis_active': True}]
        report = evaluate(base(cameras=slow, resources={'cpu': 95, 'mem_used': 6.8, 'mem_total': 8, 'temp': 80}, failed_clips=2, failed_deliveries=1), now=1000 + 5 * 86400)
        levels = {i['key']: i['level'] for i in report['items']}
        self.assertEqual((levels['camera-main'], levels['resources'], levels['backup'], levels['videos']), ('warn', 'warn', 'warn', 'warn'))

    def test_switched_off_things_are_not_problems(self):
        report = evaluate(base(whatsapp={'state': 'unavailable'}, whatsapp_enabled=False, backup_enabled=False, notebook={'state': 'disabled'},
                               cameras=[{'id': 'door', 'name': 'Portão', 'enabled': False, 'state': 'paused'}]), now=2000)
        self.assertEqual(report['level'], 'info')
        self.assertEqual(report['summary'], 'Tudo certo.')

    def test_backup_error_after_the_last_success_is_an_error(self):
        report = evaluate(base(backup={'last_ok': 1000, 'last_error': 'HD ausente', 'last_error_at': 2000}), now=3000)
        self.assertEqual({i['key']: i['level'] for i in report['items']}['backup'], 'error')


if __name__ == '__main__':
    unittest.main()
