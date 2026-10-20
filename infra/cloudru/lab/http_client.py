"""Bounded retries for read-only cloud lookups and IAM token issuance only."""
from urllib.parse import urlsplit
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
class ReadClient:
 def __init__(self,report):
  self.report=report;self.session=requests.Session()
  retry=Retry(total=2,connect=2,read=2,status=2,other=0,backoff_factor=1,status_forcelist=[429,502,503,504],allowed_methods=['GET','POST'],respect_retry_after_header=False,raise_on_status=False)
  self.session.mount('https://',HTTPAdapter(max_retries=retry))
 def request(self,method,url,**kwargs):
  parsed=urlsplit(url)
  if parsed.scheme!='https' or parsed.hostname not in {'iam.api.cloud.ru','compute.api.cloud.ru','api.ipify.org','checkip.amazonaws.com'}:raise ValueError('UNEXPECTED_READ_SERVICE')
  if method!='GET' and not (method=='POST' and parsed.hostname=='iam.api.cloud.ru' and parsed.path=='/api/v1/auth/token'):raise ValueError('MUTATION_RETRY_FORBIDDEN')
  kwargs.setdefault("allow_redirects",False)
  response=self.session.request(method,url,**kwargs)
  history=getattr(getattr(response.raw,'retries',None),'history',())
  if history:self.report.setdefault('read_retries',[]).append({'service':parsed.hostname,'method':method,'prior_attempts':[{'http_status':h.status,'error_class':type(h.error).__name__ if h.error else None} for h in history],'final_http_status':response.status_code})
  return response
 def get(self,url,**kwargs):return self.request('GET',url,**kwargs)
 def post(self,url,**kwargs):return self.request('POST',url,**kwargs)
