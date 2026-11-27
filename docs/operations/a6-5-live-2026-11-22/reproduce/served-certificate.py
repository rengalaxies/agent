from pathlib import Path
import ssl,socket,hashlib,json,certifi
ctx=ssl.create_default_context(cafile=certifi.where())
with socket.create_connection(('82.202.141.50',443),timeout=8) as raw:
 with ctx.wrap_socket(raw,server_hostname='82.202.141.50') as s:
  d=s.getpeercert();der=s.getpeercert(binary_form=True)
  out=dict(status='TRUSTED_PUBLIC_CERTIFICATE',serial=d['serialNumber'],not_before=d['notBefore'],not_after=d['notAfter'],sha256=hashlib.sha256(der).hexdigest(),ip_san=[x for x in d['subjectAltName'] if x[0]=='IP Address'])
Path('work/a6-5-live/served-certificate.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out))
