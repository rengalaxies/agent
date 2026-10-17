from pathlib import Path
import tempfile
import unittest
from change_completion.store import RunStore
from change_completion.workflow_store import WorkflowStore
from change_completion.state_transfer import snapshot, restore

class StateTransferTest(unittest.TestCase):
    def test_restart_restore_and_corruption(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); state=root/'state'; runs=RunStore(state/'runs.sqlite3'); WorkflowStore(state/'workflow.sqlite3')
            run=runs.claim('t','f')['run_id']; runs.finish(run,'STOP',{'status':'STOP'})
            with self.assertRaises(ValueError): snapshot(state,root/'backup')
            snapshot(state,root/'backup',quiesced=True)
            restore(root/'backup',root/'restored')
            self.assertEqual(RunStore(root/'restored/runs.sqlite3').get(run)['status'],'STOP')
            with self.assertRaises(FileExistsError): restore(root/'backup',root/'restored')
            with (root/'backup/runs.sqlite3').open('ab') as f:f.write(b'corrupt')
            with self.assertRaises(ValueError):restore(root/'backup',root/'bad')
    def test_inflight_and_symlink_denied(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); runs=RunStore(root/'state/runs.sqlite3'); runs.claim('t','f')
            with self.assertRaises(ValueError):snapshot(root/'state',root/'backup',quiesced=True)
            (root/'link').symlink_to(root/'state',target_is_directory=True)
            with self.assertRaises(ValueError):snapshot(root/'link',root/'backup',quiesced=True)

    def test_restore_invalidates_old_review(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); state=root/'state'; runs=RunStore(state/'runs.sqlite3')
            run=runs.claim('t','f')['run_id']; runs.finish(run,'STOP',{'status':'STOP'})
            workflows=WorkflowStore(state/'workflow.sqlite3')
            workflows.register(run,'0'*64,{'c':'owner'},'acceptor')
            workflows.review(run,'owner','approve','0'*64)
            snapshot(state,root/'backup',quiesced=True); restore(root/'backup',root/'restored')
            result=WorkflowStore(root/'restored/workflow.sqlite3').get(run)
            self.assertEqual(result['status'],'STALE'); self.assertEqual(result['reviews'],{})
