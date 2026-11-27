"""Reinstall acceptance must isolate an installation without hiding duplicates."""
from pathlib import Path
import tempfile,unittest
from tools.agent_service.box.acceptance import _service_processes

class ProcessScopeTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.root=Path(t.name);self.proc=self.root/'proc';self.proc.mkdir();self.run=self.root/'own/run'
    def process(self,pid,run=None,extra=()):
        p=self.proc/str(pid);p.mkdir()
        argv=[b'/python',b'-I',b'/release/app/tools/agent_service/box/launch.py']
        if run is not None:argv += [b'--run',str(run).encode()]
        argv+=list(extra);(p/'cmdline').write_bytes(b'\0'.join(argv)+b'\0')
    def test_other_installations_do_not_break_own_reinstall(self):
        self.process(101,self.run);self.process(102,self.root/'foreign/run');self.process(103,Path('/var/lib/agent-bitbucket/run'))
        self.assertEqual(_service_processes(self.run,proc_root=self.proc),[101])
    def test_two_processes_in_the_selected_installation_are_still_detected(self):
        self.process(101,self.run);self.process(104,self.run)
        self.assertEqual(sorted(_service_processes(self.run,proc_root=self.proc)),[101,104])
    def test_unscoped_global_inventory_remains_available(self):
        self.process(101,self.run);self.process(102,self.root/'foreign/run')
        self.assertEqual(sorted(_service_processes(proc_root=self.proc)),[101,102])
    def test_missing_conflicting_or_other_run_arguments_do_not_match(self):
        self.process(101,None);self.process(102,self.run,extra=(b'--run',str(self.root/'other').encode()))
        self.assertEqual(_service_processes(self.run,proc_root=self.proc),[])
