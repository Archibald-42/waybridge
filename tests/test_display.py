"""Readiness indicator must agree with a running Tailscale connection."""
import copy
from pathlib import Path
import unittest
from test_core import cfg
from waybridge.display import tailscale_ready


class TailscaleReadinessTests(unittest.TestCase):
    def setUp(self):
        self.config=cfg(Path('/tmp/waybridge-display-fixture'))
        self.value={'BackendState':'Running',
                    'Self':{'Online':False,'TailscaleIPs':[self.config.own_ip]},
                    'Peer':{'paired':{'Online':True,'TailscaleIPs':[self.config.peer_ip]}}}

    def test_local_online_false_or_absent_does_not_hide_working_connection(self):
        self.assertTrue(tailscale_ready(self.value,self.config))
        del self.value['Self']['Online']
        self.assertTrue(tailscale_ready(self.value,self.config))

    def test_stopped_backend_wrong_local_address_and_offline_peer_are_not_ready(self):
        for change in ('backend','address','peer','missing'):
            value=copy.deepcopy(self.value)
            if change=='backend':value['BackendState']='Stopped'
            elif change=='address':value['Self']['TailscaleIPs']=[]
            elif change=='peer':value['Peer']['paired']['Online']=False
            else:value['Peer']=None
            with self.subTest(change=change):self.assertFalse(tailscale_ready(value,self.config))


if __name__=='__main__':unittest.main()
