import sqlite3
import unittest
from warm import validation_proxy
from factory import FLAGS, FactoryError, notes, payload, proxy, run

ROW = dict(Email='test@example.com', Password='secret', Proxy='example.com:8080:user:pass:colon', CODE='', PhoneNumber='00123')

class Fake:
    def __init__(self, slots=5, uncertain=False):
        self.items=[]; self.slots=slots; self.creates=0; self.uncertain=uncertain
    def profiles(self): return self.items.copy()
    def call(self, path, body=None):
        if path=='/workspace/folders': return {'folders':[{'name':'batch','folder_id':'f'}]}
        if path=='/workspace/statistics': return {'profiles_cloud_limit':self.slots,'profiles_cloud_count':len(self.items)}
        if path=='/profile/create':
            self.creates+=1
            self.items.append(dict(id=str(self.creates),name=body['name'],folder_id='f'))
            if self.uncertain: raise FactoryError('Connection lost')
            return {'ids':[str(self.creates)]}
        raise AssertionError(path)

class Tests(unittest.TestCase):
    def db(self):
        d=sqlite3.connect(':memory:')
        d.execute('CREATE TABLE jobs (folder TEXT,email TEXT,signature TEXT,profile_id TEXT,status TEXT,PRIMARY KEY(folder,email))')
        return d
    def test_pair_and_notes(self):
        p=payload(ROW,'f')
        self.assertEqual(p['name'],ROW['Email'])
        self.assertEqual(p['parameters']['proxy']['password'],'pass:colon')
        self.assertIn('PhoneNumber: 00123',p['notes'])
        self.assertNotIn(ROW['Proxy'],p['notes'])
        self.assertFalse(p['parameters']['storage']['is_local'])
    def test_invalid_port(self):
        with self.assertRaises(FactoryError): proxy('host:99999:user:pass')
    def test_resume_no_duplicate(self):
        c=Fake(); d=self.db()
        run([ROW],'batch',c,d); run([ROW],'batch',c,d)
        self.assertEqual(c.creates,1)
    def test_capacity(self):
        c=Fake(slots=0); run([ROW],'batch',c,self.db())
        self.assertEqual(c.creates,0)
    def test_uncertain_write_not_retried(self):
        c=Fake(uncertain=True); d=self.db()
        with self.assertRaises(FactoryError): run([ROW],'batch',c,d)
        with self.assertRaises(FactoryError): run([ROW],'batch',c,d)
        self.assertEqual(c.creates,1)
    def test_changed_pair_stops(self):
        c=Fake(); d=self.db(); run([ROW],'batch',c,d)
        with self.assertRaises(FactoryError): run([dict(ROW,Proxy='other:80:u:p')],'batch',c,d)
        self.assertEqual(c.creates,1)
    def test_existing_outside_folder_does_not_block_batch(self):
        c=Fake(); c.items=[dict(name=ROW['Email'],id='old',folder_id='elsewhere')]
        run([ROW],'batch',c,self.db())
        self.assertEqual(c.creates,1)
    def test_proxy_validation_omits_profile_only_flag(self):
        checked = validation_proxy(ROW['Proxy'])
        self.assertNotIn('save_traffic', checked)
        self.assertEqual(checked['password'],'pass:colon')

if __name__=='__main__': unittest.main()
