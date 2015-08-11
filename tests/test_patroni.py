import datetime
import helpers.zookeeper
import psycopg2
import requests
import subprocess
import sys
import time
import unittest
import yaml

from patroni import Patroni, main
from helpers.dcs import Cluster, Member
from helpers.zookeeper import ZooKeeper
from six.moves import BaseHTTPServer
from test_etcd import requests_get, requests_put, requests_delete
from test_ha import true, false
from test_postgresql import Postgresql, subprocess_call, psycopg2_connect
from test_zookeeper import MockKazooClient


def nop(*args, **kwargs):
    pass


def time_sleep(*args):
    raise Exception()


class TestPatroni(unittest.TestCase):

    def __init__(self, method_name='runTest'):
        self.setUp = self.set_up
        self.tearDown = self.tear_down
        super(TestPatroni, self).__init__(method_name)

    def set_up(self):
        self.touched = False
        subprocess.call = subprocess_call
        psycopg2.connect = psycopg2_connect
        requests.get = requests_get
        requests.put = requests_put
        requests.delete = requests_delete
        self.time_sleep = time.sleep
        time.sleep = nop
        self.write_pg_hba = Postgresql.write_pg_hba
        self.write_recovery_conf = Postgresql.write_recovery_conf
        Postgresql.write_pg_hba = nop
        Postgresql.write_recovery_conf = nop
        BaseHTTPServer.HTTPServer.__init__ = nop
        with open('postgres0.yml', 'r') as f:
            config = yaml.load(f)
            self.g = Patroni(config)

    def tear_down(self):
        time.sleep = self.time_sleep
        Postgresql.write_pg_hba = self.write_pg_hba
        Postgresql.write_recovery_conf = self.write_recovery_conf

    def test_get_dcs(self):
        helpers.zookeeper.KazooClient = MockKazooClient
        self.assertIsInstance(self.g.get_dcs('', {'zookeeper': {'scope': '', 'hosts': ''}}), ZooKeeper)
        self.assertRaises(Exception, self.g.get_dcs, '', {})

    def test_patroni_main(self):
        main()
        sys.argv = ['patroni.py', 'postgres0.yml']
        time.sleep = time_sleep
        self.assertRaises(Exception, main)

    def test_patroni_run(self):
        time.sleep = time_sleep
        self.g.postgresql.is_leader = lambda: False
        self.g.ha.state_handler.sync_replication_slots = time_sleep
        self.assertRaises(Exception, self.g.run)

    def touch_member(self):
        if not self.touched:
            self.touched = True
            return False
        return True

    def test_touch_member(self):
        now = datetime.datetime.utcnow()
        member = Member(0, self.g.postgresql.name, 'b', 'c', (now + datetime.timedelta(
            seconds=self.g.shutdown_member_ttl + 10)).strftime('%Y-%m-%dT%H:%M:%S.%fZ'), None)
        self.g.ha.cluster = Cluster(True, member, 0, [member])
        self.g.touch_member()

    def test_patroni_initialize(self):
        self.g.postgresql.should_use_s3_to_create_replica = false
        self.g.ha.dcs.client._base_uri = 'http://remote'
        self.g.postgresql.data_directory_empty = true
        self.g.ha.dcs.race = true
        self.g.initialize()
        self.g.ha.dcs.race = false
        self.g.initialize()
        self.g.postgresql.data_directory_empty = false
        self.g.touch_member = self.touch_member
        self.g.initialize()
        self.g.postgresql.data_directory_empty = true
        time.sleep = time_sleep
        self.g.postgresql.sync_from_leader = false
        self.assertRaises(Exception, self.g.initialize)

    def test_schedule_next_run(self):
        self.g.next_run = time.time() - self.g.nap_time - 1
        self.g.schedule_next_run()
