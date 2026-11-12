from copy import deepcopy
from pathlib import Path
import json
import math
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from drt_abm.city import City
from drt_abm.eventQueue import EventQueue
from drt_abm.passenger import Passenger
from drt_abm.taxi_simul.fleet_taxi import Taxifleet
from drt_abm.taxi_simul.simulation import Simulation
from drt_abm.runner import execute,frames,summarize


class SimulationRegressionTests(unittest.TestCase):
    def config(self):
        cfg=json.loads((ROOT/'configs/minimal.json').read_text())
        cfg['duration_hours']=0.3
        return cfg

    def test_detour_is_zero_on_shortest_path_in_every_direction(self):
        fleet=Taxifleet(0,City('Manhattan'),0)
        for sx,sy in [(1,1),(1,-1),(-1,1),(-1,-1)]:
            self.assertAlmostEqual(fleet.detour_dist((3*sx,3*sy),(sx,sy),(2*sx,2*sy)),0)
        self.assertAlmostEqual(fleet.detour_dist((0,0),(2,0),(1,1)),2)

    def test_empty_demand_and_no_out_of_horizon_request(self):
        empty=EventQueue(City('Manhattan'),1,0,0)
        self.assertTrue(empty.empty());self.assertEqual(empty.head(),(None,None))
        events=EventQueue(City('Manhattan'),.1,1000,0)
        self.assertTrue(events.record)
        self.assertTrue(all(0<=p.t_start<.1 for p in events.record.values()))
        cfg=self.config();cfg['arrival_rate_per_hour']=0
        result=summarize(cfg,frames(execute(cfg)))
        self.assertEqual(result['requests_generated'],0)
        self.assertIsNone(result['completed_mean_wait_min'])

    def test_batch_preserves_requests_with_no_idle_vehicle(self):
        sim=Simulation(City('Manhattan'),T=.2,lmd=300,fleet_size=0,lr=False,swap=False)
        sim.batch_serve(1/3600,1/60)
        events=sim.events[0]
        queued={p.id for _,p in events.queue}
        self.assertEqual(set(events.record),queued)
        self.assertEqual(len(events.queue),len(events.record))
        self.assertLessEqual(max(sim.p),len(events.record))
        self.assertEqual(sim.p,sorted(sim.p))

    def test_batch_under_supply_has_no_orphaned_requests(self):
        sim=Simulation(City('Manhattan'),T=.4,lmd=300,fleet_size=1,lr=False,swap=False)
        sim.batch_serve(1/3600,1/60)
        queued={p.id for _,p in sim.events[0].queue}
        for p in sim.events[0].record.values():
            if p.vehicle is None:self.assertIn(p.id,queued)
            else:self.assertNotIn(p.id,queued)

    def test_seeded_runs_are_reproducible(self):
        cfg=self.config()
        a=frames(execute(cfg));b=frames(execute(cfg))
        for key in a:self.assertTrue(a[key].equals(b[key]),key)

    def test_demand_is_identical_when_fleet_size_changes(self):
        cfg=self.config();other=deepcopy(cfg);other['fleet_size']=8
        a=frames(execute(cfg))['requests'];b=frames(execute(other))['requests']
        self.assertTrue(a.equals(b))

    def test_shared_pickup_and_dropoff_order(self):
        for metric in ['Manhattan','Euclidean']:
            city=City(metric,length=4,max_v=60)
            sim=Simulation(city,T=5/60,lmd=0,fleet_size=1,lr=False,swap=False)
            sim.snapshot_interval=1
            vehicle=sim.fleet[0].vehicles[(0,0)]
            vehicle.x=vehicle.y=0;vehicle.idle_position=(0,0)
            first=Passenger(0,(0,0),city);first.x=first.y=first.dy=0;first.dx=3
            second=Passenger(20/3600,(0,1),city);second.x=1;second.y=second.dy=0;second.dx=2
            sim.events[0].insert(first);sim.events[0].insert(second)
            sim.sharing_serve(1/3600,0)
            self.assertEqual(first.status,3);self.assertEqual(second.status,3)
            self.assertTrue(first.ever_shared and second.ever_shared)
            self.assertTrue(second.shared);self.assertFalse(first.shared)
            self.assertLess(first.t_s,second.t_s)
            self.assertLess(second.t_end,first.t_end)
            self.assertIsNotNone(second.t_a)
            self.assertEqual(vehicle.load,0)
            self.assertEqual(vehicle.passenger,[])
            self.assertEqual(vehicle.path2,[])
            self.assertLessEqual(max(x['registered_load'] for x in sim.snapshots),2)
            self.assertAlmostEqual(vehicle.dist_a+vehicle.dist_s+vehicle.dist_idle,3,places=9)

    def test_all_policies_conserve_fleet_and_event_times(self):
        for policy in ['simple','sharing','batch']:
            cfg=self.config();cfg['policy']=policy
            tables=frames(execute(cfg));s=summarize(cfg,tables)
            self.assertTrue(s['vehicle_conservation_passed'])
            self.assertTrue(s['request_accounting_passed'])
            self.assertEqual(s['requests_generated'],s['requests_completed']+s['requests_rejected']+s['requests_unfinished_at_end'])

    def test_heterogeneous_constructor_without_global_optimizer(self):
        sim=Simulation(City('Manhattan',max_v=25),T=.03,simul_type='heterogeneous',
                       lmd_map=[[0,10],[20,0]],fleet_map=[[2,2],[2,2]],gr=False,lr=False,swap=False)
        sim.simple_serve(1/3600)
        self.assertEqual(len(sim.fleet),4)
        self.assertTrue(all(f.city.max_v==25 for f in sim.fleet.values()))
        self.assertTrue(all(a+b+c+d==8 for a,b,c,d in zip(sim.na,sim.ns,sim.ni,sim.ninter)))

    def test_real_world_simulation_fails_explicitly(self):
        city=City('real-world',node_file=str(ROOT/'data/raw/node.xls'),link_file=str(ROOT/'data/raw/link.xls'))
        with self.assertRaisesRegex(NotImplementedError,'Road-network'):
            Simulation(city,T=1,lmd=50,fleet_size=20)

    def test_reusing_a_run_is_rejected(self):
        sim=Simulation(City('Manhattan'),T=.01,lmd=0,fleet_size=1,lr=False,swap=False)
        sim.simple_serve(1/3600)
        with self.assertRaises(RuntimeError):sim.simple_serve(1/3600)


if __name__=='__main__':unittest.main()
