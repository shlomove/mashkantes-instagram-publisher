import json
import unittest
import tempfile
from pathlib import Path
from PIL import Image
from render import render
from cloud_runner import RemoteLedger

class FakeRepo:
    def __init__(self): self.data=None; self.version=0; self.fail=False
    def get(self,path): return self.data,str(self.version) if self.data else None
    def put(self,path,data,sha=None):
        if self.fail: raise RuntimeError('Remote write failed')
        if self.data is not None and sha!=str(self.version): raise RuntimeError('Conflict')
        self.data=data;self.version+=1;return str(self.version),'commit'

class DurableLedgerTests(unittest.TestCase):
    def test_hebrew_renderer_and_overflow_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            source={'format':'image','slides':[{'title':'בדיקת עברית','body':'מסר ברור מהפריים הראשון.'}]}
            output=render(source,Path(folder))
            with Image.open(output[0]) as image:
                self.assertEqual(image.size,(1080,1350))
                self.assertEqual(image.format,'JPEG')
            source['slides'][0]['body']='טקסט ארוך ' * 500
            with self.assertRaises(ValueError): render(source,Path(folder))
    def test_duplicate_claim_from_another_runner(self):
        r=FakeRepo();a=RemoteLedger(r,'2026-11-12');a.claim('slot','digest')
        with self.assertRaises(RuntimeError): RemoteLedger(r,'2026-11-12').claim('slot','digest')
    def test_failed_intent_is_not_marked_saved(self):
        r=FakeRepo();a=RemoteLedger(r,'2026-11-12');a.claim('slot','digest');r.fail=True
        with self.assertRaises(RuntimeError): a.save('slot','publish_pending',{'id':'123'})
        self.assertEqual(json.loads(r.data)['status'],'claimed')
    def test_published_state_survives_new_process(self):
        r=FakeRepo();a=RemoteLedger(r,'2026-11-12');a.claim('slot','digest');a.save('slot','published',{'media_id':'123'})
        self.assertEqual(RemoteLedger(r,'2026-11-12').get('slot')[1],'published')

if __name__=='__main__': unittest.main()
