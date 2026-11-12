"""Command-line workflow, tabular result export, diagnostics and animation."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import sqlite3

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

from .city import City
from .taxi_simul.simulation import Simulation

UPSTREAM_SHA = "f46db88dcabad541cb08d5fbb0ff95f027c8d2ad"
STATUS = {-1:"rejected", 0:"waiting_assignment", 1:"waiting_pickup", 2:"onboard", 3:"completed"}
COLORS = ["#e7a832", "#cf534a", "#218b75", "#6c62ab"]


def validate(cfg):
    if cfg["city_type"] not in ("Manhattan", "Euclidean"):
        raise ValueError("This runnable workflow supports Manhattan and Euclidean; road movement is not implemented.")
    if cfg["policy"] not in ("simple", "sharing", "batch"):
        raise ValueError("policy must be simple, sharing or batch")
    for k in ["length_miles","speed_mph","duration_hours","resolution_seconds","snapshot_seconds"]:
        if not isinstance(cfg[k],(float,int)) or not math.isfinite(cfg[k]) or cfg[k]<=0:
            raise ValueError(f"{k} must be finite and positive")
    if not isinstance(cfg['fleet_size'],int) or cfg['fleet_size']<=0:
        raise ValueError('fleet_size must be a positive integer')
    for k in ["arrival_rate_per_hour","detour_distance_miles"]:
        if not math.isfinite(cfg[k]) or cfg[k]<0:
            raise ValueError(f'{k} must be finite and nonnegative')
    if cfg['resolution_seconds'] > cfg['duration_hours']*3600:
        raise ValueError('resolution_seconds exceeds duration')
    if cfg['snapshot_seconds'] < cfg['resolution_seconds']:
        raise ValueError('snapshot_seconds must be >= resolution_seconds')
    if not isinstance(cfg['animation_fps'],int) or cfg['animation_fps']<=0:
        raise ValueError('animation_fps must be a positive integer')


def execute(cfg):
    validate(cfg)
    city = City(cfg['city_type'],length=cfg['length_miles'],max_v=cfg['speed_mph'],
                seed=cfg['seeds']['demand_locations'],vehicle_seed=cfg['seeds']['vehicle_locations'])
    sim = Simulation(city,T=cfg['duration_hours'],lmd=cfg['arrival_rate_per_hour'],
                     fleet_size=cfg['fleet_size'],lr=cfg['local_reallocation'],swap=cfg['swap'],
                     gr=False,split=False,arrival_seed=cfg['seeds']['arrivals'])
    sim.snapshot_interval = max(1,round(cfg['snapshot_seconds']/cfg['resolution_seconds']))
    res = cfg['resolution_seconds']/3600
    if cfg['policy']=='sharing':
        sim.sharing_serve(res, cfg['detour_distance_miles'])
    elif cfg['policy']=='simple':
        sim.simple_serve(res)
    else:
        sim.batch_serve(res,cfg['batch_interval_seconds']/3600,
                        math.inf if cfg['pickup_radius_miles'] is None else cfg['pickup_radius_miles'])
    return sim


def delta(b,a):
    return None if a is None or b is None else (b-a)*60


def frames(sim):
    records=[]
    for zone,events in sim.events.items():
        for p in events.record.values():
            records.append({
                'passenger_id':str(p.id),'zone_id':str(zone),'vehicle_id':None if p.vehicle is None else str(p.vehicle),
                'origin_x':p.x,'origin_y':p.y,'destination_x':p.dx,'destination_y':p.dy,
                'request_time_h':p.t_start,'assigned_time_h':p.t_a,'pickup_time_h':p.t_s,'dropoff_time_h':p.t_end,
                'status_code':p.status,'status':STATUS[p.status],
                'assigned_to_busy_vehicle':bool(p.shared),'experienced_shared_ride':bool(p.ever_shared),
                'wait_min':delta(p.t_s,p.t_start),'ride_min':delta(p.t_end,p.t_s),'total_min':delta(p.t_end,p.t_start),
                'direct_distance_miles':p.dist()})
    cols=['passenger_id','zone_id','vehicle_id','origin_x','origin_y','destination_x','destination_y',
          'request_time_h','assigned_time_h','pickup_time_h','dropoff_time_h','status_code','status',
          'assigned_to_busy_vehicle','experienced_shared_ride','wait_min','ride_min','total_min','direct_distance_miles']
    pax=pd.DataFrame(records,columns=cols)
    demand=pax[['passenger_id','origin_x','origin_y','destination_x','destination_y','request_time_h']].copy()
    starts=np.sort(pax.request_time_h.to_numpy(dtype=float))
    series=pd.DataFrame({'time_h':sim.timeline,'time_min':sim.timeline*60,
                         'assigned':sim.na,'in_service':sim.ns,'idle':sim.ni,'inter':sim.ninter,
                         'arrivals_cumulative':np.searchsorted(starts,sim.timeline+1e-12,side='right'),
                         'processed_unique_cumulative':sim.p})
    vehicles=pd.DataFrame([{'vehicle_id':str(v.id),'assigned_hours':v.ta,'service_hours':v.ts,'idle_hours':v.ti,
                           'assigned_distance_miles':v.dist_a,'service_distance_miles':v.dist_s,
                           'idle_distance_miles':v.dist_idle,'initial_assignments':v.freq,'final_status':v.status,
                           'final_x':v.x,'final_y':v.y}
                          for f in sim.fleet.values() for v in f.vehicles.values()])
    paths=pd.DataFrame(sim.snapshots)
    return {'requests':demand,'fleet_timeseries':series,'passengers':pax,'vehicles':vehicles,'trajectories':paths}


def finite_mean(series):
    return None if series.dropna().empty else float(series.mean())


def summarize(cfg,tables):
    p=tables['passengers'];done=p[p.status_code==3];n=len(p)
    assigned=int(p.vehicle_id.notna().sum());completed=len(done);rejected=int((p.status_code==-1).sum())
    final={str(k):int(v) for k,v in p.status.value_counts().items()}
    summary={'scenario':cfg['scenario'],'policy':cfg['policy'],'requests_generated':n,'requests_assigned':assigned,
             'requests_completed':completed,'requests_rejected':rejected,
             'requests_unfinished_at_end':n-completed-rejected,
             'completion_rate':completed/n if n else None,'rejection_rate':rejected/n if n else None,
             'assigned_to_busy_vehicle_count':int(p.assigned_to_busy_vehicle.sum()),
             'experienced_shared_ride_count':int(p.experienced_shared_ride.sum()),
             'completed_mean_wait_min':finite_mean(done.wait_min),
             'completed_p95_wait_min':float(done.wait_min.quantile(.95)) if len(done) else None,
             'completed_mean_ride_min':finite_mean(done.ride_min),
             'completed_mean_total_min':finite_mean(done.total_min),
             'observed_pickup_mean_wait_min':finite_mean(p.wait_min),
             'fleet_size':cfg['fleet_size'],'duration_hours':cfg['duration_hours'],
             'status_counts':final,
             'definitions':{'completion_rate':'completed / all requests generated within [0,T)',
                            'completed_mean_wait_min':'request-to-pickup, completed requests only',
                            'assigned_to_busy_vehicle_count':'new requests inserted into an already serving vehicle',
                            'experienced_shared_ride_count':'passengers who actually overlapped onboard with another passenger',
                            'unfinished':'waiting_assignment, waiting_pickup or onboard at T; not rejection',
                            'drain_period':'none; simulation stops at T'}}
    ts=tables['fleet_timeseries']
    summary['vehicle_conservation_passed']=bool((ts[['assigned','in_service','idle','inter']].sum(axis=1)==cfg['fleet_size']).all())
    summary['request_accounting_passed']=bool(p.passenger_id.is_unique and p.status_code.isin([-1,0,1,2,3]).all() and completed+rejected+summary['requests_unfinished_at_end']==n)
    if not summary['vehicle_conservation_passed'] or not summary['request_accounting_passed']:
        raise AssertionError('Conservation check failed')
    for col_a,col_b in [('request_time_h','assigned_time_h'),('assigned_time_h','pickup_time_h'),('pickup_time_h','dropoff_time_h')]:
        available=p[[col_a,col_b]].dropna()
        if (available[col_b]+1e-10 < available[col_a]).any():
            raise AssertionError(f'Invalid event order: {col_a} -> {col_b}')
    return summary


def write_workbook(out, tables, cfg, summary):
    """Use upstream's XlsxWriter export approach for reproducible program output."""
    scalar={k:v for k,v in summary.items() if not isinstance(v,dict)}
    summary_frame=pd.DataFrame({'metric':list(scalar),'value':list(scalar.values())})
    config_frame=pd.DataFrame({'parameter':list(cfg),'value':[json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for v in cfg.values()]})
    sheets={'summary':summary_frame,'config':config_frame,**tables}
    with pd.ExcelWriter(out/'results.xlsx',engine='xlsxwriter') as writer:
        workbook=writer.book
        header=workbook.add_format({'bold':True,'font_color':'white','bg_color':'#16394B','text_wrap':True,'valign':'vcenter'})
        number=workbook.add_format({'num_format':'0.0000'})
        for name,df in sheets.items():
            df.to_excel(writer,sheet_name=name,index=False)
            sh=writer.sheets[name];sh.freeze_panes(1,0);sh.set_row(0,32)
            for c,label in enumerate(df.columns):
                sh.write(0,c,label,header)
                width=48 if name in ('summary','config') and c==0 else 21
                if name=='config' and c==1:width=75
                sh.set_column(c,c,width,number if pd.api.types.is_float_dtype(df[label]) else None)
            sh.autofilter(0,0,len(df),len(df.columns)-1)
        chart=workbook.add_chart({'type':'line'})
        for col,name,color in [(2,'Assigned',COLORS[0]),(3,'In service',COLORS[1]),(4,'Idle',COLORS[2])]:
            chart.add_series({'name':name,'categories':['fleet_timeseries',1,1,len(tables['fleet_timeseries']),1],
                              'values':['fleet_timeseries',1,col,len(tables['fleet_timeseries']),col],
                              'line':{'color':color,'width':1.0}})
        chart.set_title({'name':'Fleet states'});chart.set_x_axis({'name':'Simulation time (minutes)'})
        chart.set_y_axis({'name':'Vehicles'});chart.set_size({'width':660,'height':340})
        writer.sheets['summary'].insert_chart('D2',chart)


def write_plots(out,tables,cfg,summary):
    plt.rcParams.update({'font.size':9,'axes.spines.top':False,'axes.spines.right':False})
    ts=tables['fleet_timeseries'];p=tables['passengers'];done=p[p.status_code==3]
    fig,ax=plt.subplots(figsize=(8,3.8),dpi=130)
    for field,label,color in zip(['assigned','in_service','idle'],['Assigned / picking up','In service','Idle'],COLORS):
        ax.plot(ts.time_min,ts[field],label=label,color=color,lw=1)
    ax.set(xlabel='Simulation time (minutes)',ylabel='Vehicles',title='Minimal scenario: fleet states',ylim=(-.5,cfg['fleet_size']+1))
    ax.legend(ncol=3,frameon=False,loc='upper center');ax.grid(alpha=.18);fig.tight_layout()
    fig.savefig(out/'fleet_states.png');plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(8,3.5),dpi=130)
    if len(done):
        axes[0].hist(done.wait_min,bins=12,color='#218b75',edgecolor='white')
    axes[0].set(xlabel='Request-to-pickup wait (minutes)',ylabel='Completed requests',title=f'Completed requests only (n={len(done)})')
    vals=[summary['requests_completed'],summary['requests_rejected'],summary['requests_unfinished_at_end']]
    bars=axes[1].bar(['Completed','Rejected','Unfinished'],vals,color=['#218b75','#cf534a','#e7a832'])
    axes[1].bar_label(bars,padding=3);axes[1].set(ylabel='Requests',title=f'Outcomes at T={cfg["duration_hours"]:g} h',ylim=(0,max(vals+[1])*1.2))
    fig.tight_layout();fig.savefig(out/'passenger_outcomes.png');plt.close(fig)
    # OD points of the simulated demand, not the unrelated XLS road graph.
    fig,ax=plt.subplots(figsize=(5,5),dpi=130)
    ax.scatter(p.origin_x,p.origin_y,s=15,c='#218b75',label='Origins',alpha=.75)
    ax.scatter(p.destination_x,p.destination_y,s=18,c='#cf534a',marker='x',label='Destinations',alpha=.7)
    ax.set(xlim=(0,cfg['length_miles']),ylim=(0,cfg['length_miles']),xlabel='x (miles)',ylabel='y (miles)',title='Generated demand in the virtual city')
    ax.set_aspect('equal');ax.grid(alpha=.18);ax.legend(frameon=False);fig.tight_layout();fig.savefig(out/'demand_map.png');plt.close(fig)


def write_gif(out,tables,cfg):
    size=(500,400);left,top,side=62,48,300;length=cfg['length_miles'];frames_out=[]
    try:font=ImageFont.truetype('DejaVuSans.ttf',12)
    except OSError:font=ImageFont.load_default()
    for t,frame in tables['trajectories'].groupby('time_h',sort=True):
        im=Image.new('RGB',size,'white');d=ImageDraw.Draw(im)
        d.text((left,12),f"{cfg['city_type']} / {cfg['policy']} | t={t*60:.1f} min",fill='#16394B',font=font)
        for i in range(7):
            q=i*side/6;d.line((left+q,top,left+q,top+side),fill='#e2e8eb');d.line((left,top+q,left+side,top+q),fill='#e2e8eb')
        for row in frame.itertuples():
            x=left+row.x/length*side;y=top+side-row.y/length*side
            d.ellipse((x-4,y-4,x+4,y+4),fill=COLORS[row.status],outline='white')
            if row.onboard>=2:d.ellipse((x-7,y-7,x+7,y+7),outline='#142E40',width=2)
        for i,(label,color) in enumerate(zip(['Assigned','In service','Idle','Inter-zone'],COLORS)):
            y=60+i*27;d.ellipse((382,y,390,y+8),fill=color);d.text((396,y-2),label,fill='#16394B',font=font)
        d.text((left,360),'Dark ring: 2 passengers onboard',fill='#16394B',font=font)
        d.text((left,379),f'City side: {length:g} mi; one frame / {cfg["snapshot_seconds"]:g} simulated sec',fill='#617583',font=font)
        frames_out.append(im.quantize(colors=48))
    frames_out[0].save(out/'simulation.gif',save_all=True,append_images=frames_out[1:],duration=round(1000/cfg['animation_fps']),loop=0,optimize=True)


def export_results(root,out,sim,cfg,config_path,make_gif=True):
    out.mkdir(parents=True,exist_ok=True)
    tables=frames(sim);summary=summarize(cfg,tables)
    for name,table in tables.items():
        table.to_csv(out/(name+'.csv'),index=False,encoding='utf-8-sig')
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    (out/'config.json').write_text(json.dumps(cfg,indent=2)+'\n')
    with sqlite3.connect(out/'simulation.sqlite') as con:
        for name,table in tables.items():table.to_sql(name,con,if_exists='replace',index=False)
        pd.DataFrame([{'metric':k,'value':json.dumps(v,ensure_ascii=False)} for k,v in summary.items()]).to_sql('summary',con,if_exists='replace',index=False)
        pd.DataFrame([{'parameter':k,'value':json.dumps(v,ensure_ascii=False)} for k,v in cfg.items()]).to_sql('config',con,if_exists='replace',index=False)
    write_workbook(out,tables,cfg,summary)
    write_plots(out,tables,cfg,summary)
    if make_gif:write_gif(out,tables,cfg)
    elif (out/'simulation.gif').exists():(out/'simulation.gif').unlink()
    # Record exact executing source hashes without circular dependence on result commit.
    code_files=[root/'run_simulation.py',*sorted((root/'src').rglob('*.py'))]
    provenance={'created_at_utc':datetime.now(timezone.utc).isoformat(),'python':platform.python_version(),
                'packages':{p:importlib.metadata.version(p) for p in ['numpy','scipy','pandas','matplotlib','Pillow','xlrd','XlsxWriter']},
                'upstream_commit':UPSTREAM_SHA,'config_sha256':hashlib.sha256(config_path.read_bytes()).hexdigest(),
                'source_sha256':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in code_files},
                'numerical_reproducibility':'Seeded input and deterministic ID tie-breaking; compare CSV/summary, not GIF/XLSX binary bytes.'}
    (out/'run_metadata.json').write_text(json.dumps(provenance,indent=2)+'\n')
    mean_wait = 'N/A' if summary['completed_mean_wait_min'] is None else f"{summary['completed_mean_wait_min']:.3f}"
    mean_total = 'N/A' if summary['completed_mean_total_min'] is None else f"{summary['completed_mean_total_min']:.3f}"
    report=f'''# 시뮬레이션 결과: {cfg['scenario']}

설정: {cfg['city_type']}, 차량 {cfg['fleet_size']}대, 시간당 요청 {cfg['arrival_rate_per_hour']:g}건, {cfg['duration_hours']:g}시간, {cfg['resolution_seconds']:g}초 스텝, 우회거리 상한 {cfg['detour_distance_miles']:g} mile.

| 지표 | 결과 |
|---|---:|
| 생성 요청 | {summary['requests_generated']} |
| 배정 | {summary['requests_assigned']} |
| 완료 | {summary['requests_completed']} |
| 거절 | {summary['requests_rejected']} |
| 종료 시 미완료 | {summary['requests_unfinished_at_end']} |
| 서비스 중 차량에 추가 배정 | {summary['assigned_to_busy_vehicle_count']} |
| 실제 동승 경험 승객 | {summary['experienced_shared_ride_count']} |
| 완료 승객 평균 대기시간(분) | {mean_wait} |
| 완료 승객 평균 총 소요시간(분) | {mean_total} |

![차량 상태](fleet_states.png)
![승객 결과](passenger_outcomes.png)
![시뮬레이션](simulation.gif)

## 파일 보기

- [results.xlsx](results.xlsx): 내려받아 Excel에서 summary → fleet_timeseries → passengers 순으로 확인합니다.
- [summary.json](summary.json): 수치 요약과 지표 정의.
- [passengers.csv](passengers.csv): 요청별 시각, OD, 최종 상태, 대기·차내·총시간. 빈 시각은 아직 이벤트가 발생하지 않았다는 뜻입니다.
- [requests.csv](requests.csv): 실제 생성된 입력 수요. 출발·도착 좌표 단위는 mile, 요청시각 단위는 hour입니다.
- [simulation.sqlite](simulation.sqlite): 같은 결과를 저장한 SQLite DB입니다.
- [run_metadata.json](run_metadata.json): 실행 버전과 원본·실행 코드 해시.

완료 승객 평균은 종료 시 미완료 요청을 제외합니다. T 이후 승객을 끝까지 운송하는 배출 구간은 없습니다. `assigned_to_busy_vehicle`와 실제 동승 경험은 다른 지표입니다. 이 예제는 합성 Manhattan 공간이며 data/raw의 실제 도로망을 사용하지 않습니다.

재실행: 저장소 루트에서 `python run_simulation.py --config configs/minimal.json`.
상세 컬럼 해설과 DB 조회: [결과 가이드](../../docs/RESULTS_GUIDE.md).
'''
    if not make_gif:report=report.replace('![시뮬레이션](simulation.gif)\n','')
    (out/'README.md').write_text(report,encoding='utf-8')
    return summary


def main(root):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default='configs/minimal.json')
    parser.add_argument('--output',help='Override output directory; paths are relative to repository root')
    parser.add_argument('--no-gif',action='store_true')
    args=parser.parse_args()
    config_path=Path(args.config)
    if not config_path.is_absolute():config_path=root/config_path
    cfg=json.loads(config_path.read_text(encoding='utf-8'))
    out=Path(args.output or cfg['output_dir'])
    if not out.is_absolute():out=root/out
    sim=execute(cfg)
    result=export_results(root,out,sim,cfg,config_path,not args.no_gif)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    print('Results:',out)
