"""One-click startup checks without services, USB, or process termination."""
from contextlib import ExitStack
import unittest
from unittest.mock import patch
from scripts.start_capture import main


class CaptureStartupTests(unittest.TestCase):
    def invoke(self, status, readiness=True):
        with ExitStack() as stack:
            stack.enter_context(patch('sys.argv',['start-capture']))
            stack.enter_context(patch('scripts.start_capture.os.chdir'))
            stack.enter_context(patch('scripts.start_capture.capture_context',return_value={'backend':'native','directory':'fixture','base_url':'http://127.0.0.1:8084','environment':'development','env_file':'fixture.env'}))
            stack.enter_context(patch('scripts.start_capture.recent_status',return_value=status))
            ready=stack.enter_context(patch('scripts.start_capture.api_ready',side_effect=readiness if isinstance(readiness,list) else None,return_value=readiness))
            prepare=stack.enter_context(patch('scripts.start_capture.subprocess.run'))
            capture=stack.enter_context(patch('scripts.start_capture.subprocess.call',return_value=0))
            result=main()
            return result,ready,prepare,capture

    def test_running_new_capture_is_reused_without_opening_another(self):
        result,ready,prepare,capture=self.invoke({'capture_version':2,'state':'waiting_device'})
        self.assertEqual(result,0);ready.assert_called_once();prepare.assert_not_called();capture.assert_not_called()

    def test_running_capture_still_recovers_missing_api_without_duplicate_usb(self):
        result,_,prepare,capture=self.invoke({'capture_version':2,'state':'waiting_device'},[False,True])
        self.assertEqual(result,0);prepare.assert_called_once();capture.assert_not_called()

    def test_paused_capture_can_start_again(self):
        result,_,prepare,capture=self.invoke({'capture_version':2,'state':'receiving','error':'Captura pausada para cargar firmware'})
        self.assertEqual(result,0);prepare.assert_not_called();capture.assert_called_once()
        self.assertIn('auto',capture.call_args.args[0]);self.assertIn('--directory',capture.call_args.args[0])

    def test_old_reader_requires_one_time_pause(self):
        with self.assertRaisesRegex(SystemExit,'lector anterior'):
            self.invoke({'port':'COM5','connected':False,'error':'old port missing'})

    def test_missing_api_prepares_services_without_starting_a_second_usb(self):
        result,_,prepare,capture=self.invoke(None,[False,True])
        self.assertEqual(result,0);prepare.assert_called_once();capture.assert_called_once()
        self.assertEqual(prepare.call_args.args[0][-2:],['start','--no-usb'])


if __name__=='__main__':unittest.main()
