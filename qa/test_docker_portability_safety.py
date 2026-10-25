"""Safety guards for the Docker QA runner; no daemon is accessed."""
from pathlib import Path
import os
from unittest.mock import patch
import tempfile
import unittest
from qa.docker_portability import Runner,PortabilityError,check_project,test_counts


class DockerQaSafetyTests(unittest.TestCase):
    def test_qa_project_prefix_is_strict(self):
        check_project('geocattle-portability-qa-abcdef')
        for name in ('geocattle-simulation','geocattle-docker-academic','geocattle-portability-qa-abcdef-more','geocattle-portability-qa-XYZ'):
            with self.subTest(name=name),self.assertRaises(PortabilityError):check_project(name)

    def test_parser_requires_completed_backend_suite_without_skips(self):
        self.assertEqual(test_counts('109 passed, 1 warning in 1s','pytest'),109)
        for text in ('2 passed, 1 skipped','no tests ran','1 failed'):
            with self.subTest(text=text),self.assertRaises(PortabilityError):test_counts(text,'pytest')

    def test_unittest_count_is_dynamic_but_requires_ok(self):
        self.assertEqual(test_counts('Ran 82 tests in 1.0s\n\nOK\n','unittest'),82)
        with self.assertRaises(PortabilityError):test_counts('Ran 82 tests in 1s\nFAILED','unittest')

    def test_compose_uses_only_generated_qa_configuration_and_profiles(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'backend').mkdir();(root/'compose.yaml').write_text('services: {}');(root/'backend/Dockerfile').write_text('FROM test')
            runner=Runner(root)
            args=runner.compose('down')
            self.assertIn(runner.project,args);self.assertIn(str(runner.env_file),args)
            self.assertIn('iot',args);self.assertIn('lorawan',args)
            self.assertNotIn('-v',args)
            for value in runner.secrets:self.assertNotIn(value,' '.join(args))
            self.assertNotIn(runner.config['POSTGRES_PASSWORD'],runner.redact(runner.config['POSTGRES_PASSWORD']))

    def test_live_ports_are_rejected_before_creating_config(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'backend').mkdir();(root/'compose.yaml').write_text('services: {}');(root/'backend/Dockerfile').write_text('FROM test')
            with self.assertRaises(PortabilityError):Runner(root,8084,55434)
            self.assertFalse((root/'.runtime').exists())

    def test_changed_project_cannot_stop_an_existing_deployment(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'backend').mkdir();(root/'compose.yaml').write_text('services: {}');(root/'backend/Dockerfile').write_text('FROM test')
            runner=Runner(root);runner.project='geocattle-simulation'
            with self.assertRaises(PortabilityError):runner.compose('down')


    def test_host_operational_settings_cannot_change_qa_contract(self):
        inherited = {'SESSION_HOURS':'0', 'MQTT_TLS':'true', 'MQTT_ACK_TOPIC':'outside/committed',
            'MQTT_CLIENT_ID':'outside-client', 'PREVENTIVE_RULES_VALIDATED':'true',
            'WORKER_INTERVAL_SECONDS':'9999', 'CONFIG_TIMEOUT_SECONDS':'1',
            'NOTIFICATION_WEBHOOK_URL':'https://outside.invalid/never',
            'NOTIFICATION_WEBHOOK_TOKEN':'outside-token', 'NOTIFICATION_MAX_ATTEMPTS':'999',
            'NOTIFICATION_EXPIRY_HOURS':'999', 'ADMIN_PASSWORD':'outside-password',
            'V3_ADMIN_PASSWORD':'outside-admin-password'}
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,inherited):
            root=Path(folder);(root/'backend').mkdir();(root/'compose.yaml').write_text('services: {}');(root/'backend/Dockerfile').write_text('FROM test')
            runner=Runner(root)
            expected={'SESSION_HOURS':'12','MQTT_TLS':'false','MQTT_ACK_TOPIC':'geocattle/academic/committed',
                'PREVENTIVE_RULES_VALIDATED':'false','WORKER_INTERVAL_SECONDS':'15',
                'CONFIG_TIMEOUT_SECONDS':'3600','NOTIFICATION_WEBHOOK_URL':'','NOTIFICATION_WEBHOOK_TOKEN':'',
                'NOTIFICATION_MAX_ATTEMPTS':'3','NOTIFICATION_EXPIRY_HOURS':'24','ADMIN_PASSWORD':'','V3_ADMIN_PASSWORD':''}
            for key,value in expected.items():
                with self.subTest(key=key):self.assertEqual(runner.env[key],value)
            self.assertEqual(runner.env['MQTT_CLIENT_ID'],runner.project+'-ingestor')
            self.assertEqual(os.environ['MQTT_TLS'],'true')

    def test_old_smoke_credentials_compose_files_and_database_urls_do_not_leak_into_qa(self):
        inherited={'SMOKE_USERNAME':'outside@example.invalid','SMOKE_PASSWORD':'outside-password',
            'SMOKE_VIEWER_USERNAME':'viewer@example.invalid','COMPOSE_FILE':'outside.yaml',
            'COMPOSE_PROFILES':'tools','COMPOSE_ENV_FILES':'outside.env',
            'DATABASE_URL':'postgresql://outside.invalid/never','TEST_DATABASE_URL':'postgresql://outside.invalid/never'}
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,inherited):
            root=Path(folder);(root/'backend').mkdir();(root/'compose.yaml').write_text('services: {}');(root/'backend/Dockerfile').write_text('FROM test')
            runner=Runner(root)
            self.assertTrue(all(key not in runner.env for key in inherited))
            self.assertEqual(os.environ['SMOKE_USERNAME'],'outside@example.invalid')
            self.assertEqual(runner.env['APP_ENV'],'simulation')
            self.assertEqual(runner.env['SIMULATION_ENABLED'],'true')


if __name__=='__main__':unittest.main()
