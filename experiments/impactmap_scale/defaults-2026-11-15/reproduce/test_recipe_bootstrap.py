"""Check the actual recipe bootstrap without executing measurement workers."""
from pathlib import Path
import os,tempfile,unittest
ROOT=Path.cwd()
class BootstrapTests(unittest.TestCase):
 def prefix(self):
  source=Path(os.environ.get('RECIPE_UNDER_TEST',str(ROOT/'experiments/impactmap_scale/defaults-2026-11-15/reproduce/run_default_limits_campaign.py'))).read_text()
  return source.split('identity=core_identity();source=',1)[0]
 def run_prefix(self,directory):
  previous=Path.cwd();os.chdir(directory)
  try:exec(compile(self.prefix(),'recipe-bootstrap','exec'),{})
  finally:os.chdir(previous)
 def test_fresh_output_root_is_created(self):
  with tempfile.TemporaryDirectory() as directory:
   self.run_prefix(directory)
   self.assertTrue((Path(directory)/'work/batch05-defaults').is_dir())
 def test_existing_input_is_refused_without_rewriting(self):
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'work/batch05-defaults/repos5-lines50k-implicit-input.json';path.parent.mkdir(parents=True);path.write_text('KEEP')
   with self.assertRaises(AssertionError):self.run_prefix(directory)
   self.assertEqual(path.read_text(),'KEEP')
if __name__=='__main__':unittest.main(verbosity=2)
