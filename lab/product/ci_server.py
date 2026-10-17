"""CI-only process restart/late result controls; normal server has no delay hooks."""
import os,time
import uvicorn
from .api import create_app
from .collectors import collect

def collection():
    time.sleep(float(os.getenv('LAB_CONTROL_COLLECT_DELAY','0')))
    return collect()
app=create_app(collector=collection)
original=app.state.worker.execute

def execute(job,change):
    if job['operation']=='analysis' and job['mode']=='FIXTURE / CONTROL':time.sleep(float(os.getenv('LAB_CONTROL_ANALYSIS_DELAY','0')))
    return original(job,change)
app.state.worker.execute=execute
if __name__=='__main__':uvicorn.run(app,host='127.0.0.1',port=int(os.getenv('LAB_PRODUCT_PORT','8088')),log_level='warning')
