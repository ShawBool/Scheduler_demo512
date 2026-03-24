import copy
import statistics
from scheduler.config import load_config
from scheduler.simulation import generate_task_pool
from scheduler.planner import plan_baseline

cfg = load_config('config')
seeds = [3,7,11,17,23,29,31,37,41,43]

def run(conf):
    rows=[]
    for s in seeds:
        tasks=generate_task_pool(conf,s)
        r=plan_baseline(tasks,conf)
        rows.append((s,len(tasks),len(r.scheduled_items),r.constraint_stats.get('solver_status')))
    ratio=statistics.mean(sc/t for _,t,sc,_ in rows)
    return ratio,rows

r1,rows1=run(cfg)
print('baseline_ratio',round(r1,3))
print('baseline_rows',rows1)

cfg2=copy.deepcopy(cfg)
cfg2['runtime']['solver_timeout_sec']=300
r2,rows2=run(cfg2)
print('timeout300_ratio',round(r2,3))
print('timeout300_rows',rows2)

cfg3=copy.deepcopy(cfg)
cfg3['constraints']['attitude_time_per_degree']=0.0
r3,rows3=run(cfg3)
print('no_attitude_ratio',round(r3,3))
print('no_attitude_rows',rows3)
