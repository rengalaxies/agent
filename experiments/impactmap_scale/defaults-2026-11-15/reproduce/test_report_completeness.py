"""Mutation controls: verifier must reject lost/duplicated queue verdicts."""
from pathlib import Path
import hashlib,importlib.util,json,shutil,tempfile,unittest
ROOT=Path.cwd();REPORT=ROOT/'experiments/impactmap_scale/defaults-2026-11-15'
spec=importlib.util.spec_from_file_location('defaults_verifier',REPORT/'verify_artifacts.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class CompletenessTests(unittest.TestCase):
 def check_rejected(self,mutation):
  with tempfile.TemporaryDirectory() as directory:
   target=Path(directory)/'report';shutil.copytree(REPORT,target);module.REPORT=target
   module.verify()  # A consistent unmodified copy must pass first.
   relative='acceptance/queue-repos5-lines50k-independent_prs/result.json';path=target/relative;raw=json.loads(path.read_text())
   mutation(raw);path.write_text(json.dumps(raw,indent=2)+'\n')
   hashes=json.loads((target/'artifact-hashes.json').read_text());hashes[relative]=hashlib.sha256(path.read_bytes()).hexdigest();(target/'artifact-hashes.json').write_text(json.dumps(hashes)+'\n')
   with self.assertRaises(AssertionError):module.verify()
 def test_missing_all_verdicts_is_not_success(self):self.check_rejected(lambda r:r.update(result_verdicts=[]))
 def test_duplicate_generation_cannot_replace_another_job(self):self.check_rejected(lambda r:r['result_verdicts'].__setitem__(1,r['result_verdicts'][0]))
if __name__=='__main__':unittest.main(verbosity=2)
