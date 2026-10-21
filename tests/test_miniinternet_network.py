import json
import tempfile
import unittest
from pathlib import Path
from miniinternet.config import load_config, ConfigError
from miniinternet.runner import run_probe

ROOT=Path(__file__).resolve().parents[1]

class MiniNetworkTests(unittest.TestCase):
    def _quiet_config(self, source='topology-upper.json', mutate=None):
        data=json.loads((ROOT/'config'/source).read_text())
        data['quiet']=True
        if mutate: mutate(data)
        temp=tempfile.NamedTemporaryFile(mode='w',suffix='.json',delete=False,encoding='utf-8')
        json.dump(data,temp);temp.close()
        self.addCleanup(lambda: Path(temp.name).unlink(missing_ok=True))
        return temp.name
    def test_upper_and_lower_routes(self):
        for config in ('topology-upper.json','topology-lower.json'):
            with self.subTest(path=config):
                path=self._quiet_config(config)
                for source,destination in (('H1','H2'),('H2','H1')):
                    result=run_probe(path,source,destination,20,0.005,2.0)
                    self.assertEqual(result['received'],20)
                    self.assertEqual(result['timeout_count'],0)
    def test_unknown_destination_times_out_boundedly(self):
        result=run_probe(self._quiet_config(),'H1','192.0.2.99',1,0,0.35)
        self.assertEqual(result['received'],0)
        self.assertEqual(result['timeout_count'],1)
    def test_hop_limit_loop_expires(self):
        def make_loop(cfg):
            cfg['hop_limit']=5
            cfg['devices']['RB']['forwarding']['10.0.0.2']='RA'
        result=run_probe(self._quiet_config(mutate=make_loop),'H1','H2',1,0,0.35)
        self.assertEqual(result['received'],0)
        self.assertEqual(result['timeout_count'],1)
    def test_forced_loss_is_not_retransmitted_by_core(self):
        def force_drop(cfg):
            cfg['devices']['RA']['links']={'RB':{'force_drop_first':1,'seed':77}}
        result=run_probe(self._quiet_config(mutate=force_drop),'H1','H2',1,0,0.35)
        self.assertEqual(result['received'],0)
        self.assertEqual(result['timeout_count'],1)
    def test_config_rejects_non_neighbor_next_hop(self):
        data=json.loads((ROOT/'config/topology-upper.json').read_text())
        data['devices']['RA']['forwarding']['10.0.0.2']='H2'
        temp=tempfile.NamedTemporaryFile(mode='w',suffix='.json',delete=False,encoding='utf-8')
        json.dump(data,temp);temp.close();self.addCleanup(lambda:Path(temp.name).unlink(missing_ok=True))
        with self.assertRaises(ConfigError): load_config(temp.name)
