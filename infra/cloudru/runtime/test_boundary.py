import importlib.util,os,tempfile,unittest
from pathlib import Path
from fastapi.testclient import TestClient
class Boundary(unittest.TestCase):
 def test_auth_capabilities_and_no_false_job(self):
  with tempfile.TemporaryDirectory() as tmp:
   os.environ.update(LAB_PRODUCT_DB=tmp+'/state.sqlite',LAB_REQUIRE_AUTH='1',LAB_AUTH_USERNAME='internal_proxy',LAB_AUTH_PASSWORD='test-only-no-deployment',LAB_COOKIE_SECURE='1')
   spec=importlib.util.spec_from_file_location('cloud_boundary',Path(__file__).with_name('cloud_server.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
   with TestClient(module.app) as c:
    for path in ['/','/api/lab/capabilities','/saved-demo','/api/lab/saved-demo','/api/lab/readyz']:
     self.assertEqual(c.get(path).status_code,401)
    c.auth=('internal_proxy','test-only-no-deployment')
    self.assertEqual(c.get('/api/lab/capabilities').json()['new_independent_checks'],'UNAVAILABLE')
    self.assertIn('UNAVAILABLE',c.get('/').text)
    for operation,mode in [('verify','REPLAY'),('analysis','LIVE RUN'),('prepare','LIVE RUN')]:
     r=c.post('/api/lab/jobs',json={'operation':operation,'mode':mode});self.assertEqual(r.status_code,409);self.assertFalse(r.json()['job_created'])
    self.assertEqual(c.post('/api/lab/apply').status_code,403)
    self.assertFalse(module.app.state.store.rows('jobs'))
if __name__=='__main__':unittest.main()
