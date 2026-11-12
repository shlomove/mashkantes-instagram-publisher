"""Cloud-only transport/render checks. Never publishes to Instagram."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request
from cloud_runner import Repository, RemoteLedger
from render import render
from publisher import Graph

repo=Repository(os.environ['GITHUB_REPOSITORY'],os.environ['GH_REPO_TOKEN'])
run=os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT']
source={'format':'image','slides':[{'title':'בדיקת תצוגה','body':'קובץ בדיקה בלבד.\nלא מיועד לפרסום באינסטגרם.'}]}
files=render(source,Path('smoke-image'))
source['format']='reel';source['slides']*=5
files+=render(source,Path('smoke-video'))
probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(files[-1])]))
assert float(probe['format']['duration'])==30
for file in files:
    data=file.read_bytes();name='checks/'+run+'/'+file.name
    _,commit=repo.put(name,data)
    url='https://raw.githubusercontent.com/'+repo.name+'/'+commit+'/'+name
    with urllib.request.urlopen(url,timeout=45) as response: remote=response.read()
    assert hashlib.sha256(remote).digest()==hashlib.sha256(data).digest()
    print(json.dumps({'check':'public_media','mime':'video/mp4' if file.suffix=='.mp4' else 'image/jpeg','url':url,'bytes':len(data)}))
ledger=RemoteLedger(repo,'check-'+run);ledger.claim('check-'+run,'transport-check');ledger.save('check-'+run,'verified',{'no_publication':True})
assert RemoteLedger(repo,'check-'+run).get('check-'+run)[1]=='verified'
print('Durable remote journal verified')
token=os.environ.get('IG_ACCESS_TOKEN')
if token:
    result=Graph(token).call('GET','me/assigned_instagram_accounts',fields='id,username')
    assert any(x.get('id')=='17841435230882039' and x.get('username')=='eliran_mashkantes' for x in result.get('data',[]))
    print('Instagram account verified from cloud; no publication performed')
else:
    print('Instagram secret not configured; API cloud check skipped')
