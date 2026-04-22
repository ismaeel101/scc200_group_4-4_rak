#!/usr/bin/env python3
from __future__ import annotations
import io, sqlite3, zipfile, hashlib
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import requests
except ImportError:
    raise SystemExit("Run first: pip3 install requests --break-system-packages")

DB = '/tmp/busrak_fresh.db'
TMP = Path('/workspace/backend/data/busrak_timetables')
TX_NS = 'http://www.transxchange.org.uk/'
ns = {'tx': TX_NS}
NW_PREFIXES = ('250', '259', '082', '180', '258', '280', '119', '090')
DATASET_IDS = [16147,20830,22805,14109,14598,20920,20951,19206,22523,18047,18067,18508]

def is_nw(sid): return any(sid.startswith(p) for p in NW_PREFIXES)
def hms_to_secs(t):
    if not t: return None
    p=t.strip().split(':')
    try: return int(p[0])*3600+int(p[1])*60+(int(p[2]) if len(p)>2 else 0)
    except: return None
def secs_to_hms(s):
    if s is None: return None
    s=int(s)%86400
    return f'{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}'
def parse_dur(d):
    if not d or not d.startswith('P'): return 0
    tp=d[1:].split('T',1)[1] if 'T' in d else d[1:]
    secs,num=0,''
    for c in tp:
        if c.isdigit() or c=='.': num+=c
        elif c=='H': secs+=int(float(num))*3600;num=''
        elif c=='M': secs+=int(float(num))*60;num=''
        elif c=='S': secs+=int(float(num));num=''
    return secs
def make_prefix(ds_id, xml_name):
    return hashlib.md5(f'{ds_id}_{xml_name}'.encode()).hexdigest()[:8]

def download_datasets():
    TMP.mkdir(parents=True, exist_ok=True)
    base = 'https://transport.scc.lancs.ac.uk/timetable/dataset/{}/download/'
    files = []
    for i, ds_id in enumerate(DATASET_IDS, 1):
        dest = TMP / f'dataset_{ds_id}.xml'
        if dest.exists():
            print(f'  [{i}/{len(DATASET_IDS)}] Already exists: dataset_{ds_id}.xml')
        else:
            url = base.format(ds_id)
            print(f'  [{i}/{len(DATASET_IDS)}] Downloading {url} ...')
            r = requests.get(url, timeout=120)
            r.raise_for_status()
            dest.write_bytes(r.content)
            print(f'    Saved {len(r.content)//1024}KB')
        files.append(dest)
    return files

def process_xml(data, cur, counter, prefix):
    try: root=ET.fromstring(data)
    except Exception as e: print(f'      SKIP parse: {e}'); return
    stop_names={}
    for sp in root.findall('.//tx:AnnotatedStopPointRef',ns):
        ref=sp.find('tx:StopPointRef',ns); cn=sp.find('tx:CommonName',ns)
        if ref is not None and ref.text and cn is not None and cn.text:
            sid=ref.text.strip()
            if is_nw(sid): stop_names[sid]=cn.text.strip()
    for sp in root.findall('.//tx:StopPoint',ns):
        a=sp.find('tx:AtcoCode',ns); cn=sp.find('tx:CommonName',ns)
        if a is not None and a.text and cn is not None and cn.text:
            sid=a.text.strip()
            if is_nw(sid): stop_names[sid]=cn.text.strip()
    for atco,name in stop_names.items():
        cur.execute('INSERT OR IGNORE INTO bus_stops (atco_code,common_name) VALUES (?,?)',(atco,name))
    for svc in root.findall('.//tx:Service',ns):
        sc=svc.find('tx:ServiceCode',ns)
        ln=svc.find('tx:Lines/tx:Line/tx:LineName',ns)
        op=svc.find('tx:RegisteredOperatorRef',ns)
        if op is None: op=svc.find('tx:OperatorRef',ns)
        if sc is not None and sc.text:
            code=sc.text.strip()
            name=ln.text.strip() if ln is not None and ln.text else ''
            oper=op.text.strip() if op is not None and op.text else ''
            cur.execute('INSERT OR IGNORE INTO services (id,line_name,operator) VALUES (?,?,?)',(code,name,oper))
    jptl_info={}
    jps_links={}
    for jps in root.findall('.//tx:JourneyPatternSection',ns):
        jps_id=jps.get('id')
        if not jps_id: continue
        links=[]
        for jptl in jps.findall('tx:JourneyPatternTimingLink',ns):
            jptl_id=jptl.get('id')
            if not jptl_id: continue
            rt=jptl.find('tx:RunTime',ns)
            run=parse_dur(rt.text.strip()) if rt is not None and rt.text else 0
            fr=jptl.find('tx:From/tx:StopPointRef',ns)
            to=jptl.find('tx:To/tx:StopPointRef',ns)
            jptl_info[jptl_id]=(fr.text.strip() if fr is not None and fr.text else None,
                                 to.text.strip() if to is not None and to.text else None, run)
            links.append(jptl_id)
        jps_links[jps_id]=links
    jp_links={}
    for jp in root.findall('.//tx:JourneyPattern',ns):
        jp_id=jp.get('id')
        if not jp_id: continue
        all_links=[]
        for sr in jp.findall('tx:JourneyPatternSectionRefs',ns):
            if sr.text and sr.text.strip() in jps_links:
                all_links.extend(jps_links[sr.text.strip()])
        jp_links[jp_id]=all_links
    for vj in root.findall('.//tx:VehicleJourney',ns):
        vjc=vj.find('tx:VehicleJourneyCode',ns)
        if vjc is None or not vjc.text: continue
        trip_id=f'{prefix}_{vjc.text.strip()}'
        sref=vj.find('tx:ServiceRef',ns)
        svc_id=sref.text.strip() if sref is not None and sref.text else None
        jp_ref=vj.find('tx:JourneyPatternRef',ns)
        jp_id=jp_ref.text.strip() if jp_ref is not None and jp_ref.text else None
        dt_el=vj.find('tx:DepartureTime',ns)
        dep_str=dt_el.text.strip() if dt_el is not None and dt_el.text else None
        if not jp_id or jp_id not in jp_links: continue
        link_ids=jp_links[jp_id]
        if not link_ids: continue
        vj_overrides={}
        for vjtl in vj.findall('tx:VehicleJourneyTimingLink',ns):
            ref=vjtl.find('tx:JourneyPatternTimingLinkRef',ns)
            rt=vjtl.find('tx:RunTime',ns)
            if ref is not None and ref.text and rt is not None and rt.text:
                vj_overrides[ref.text.strip()]=parse_dur(rt.text.strip())
        stops=[]
        for i,jptl_id in enumerate(link_ids):
            if jptl_id not in jptl_info: continue
            from_stop,to_stop,jp_run=jptl_info[jptl_id]
            run=vj_overrides.get(jptl_id,jp_run)
            if i==0 and from_stop: stops.append((from_stop,0))
            if to_stop: stops.append((to_stop,run))
        if not stops: continue
        if not any(is_nw(s) for s,_ in stops): continue
        cur.execute('INSERT OR IGNORE INTO trips (id,service_id,departure_time) VALUES (?,?,?)',(trip_id,svc_id,dep_str))
        cur_secs=hms_to_secs(dep_str) or 0
        seq=1
        for i,(stop_id,run_secs) in enumerate(stops):
            if i>0: cur_secs+=run_secs
            if not is_nw(stop_id): continue
            t=secs_to_hms(cur_secs)
            cur.execute('INSERT INTO stop_times (trip_id,stop_id,arrival_time,departure_time,sequence) VALUES (?,?,?,?,?)',
                        (trip_id,stop_id,t,t,seq))
            seq+=1; counter[0]+=1
        if counter[0]%50000==0 and counter[0]>0:
            print(f'      {counter[0]:,} stop_times...')

def process_file(path,cur,counter,ds_id):
    print(f'  {path.name}')
    raw=path.read_bytes()
    if raw[:2]==b'PK':
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                xml_files=[n for n in zf.namelist() if n.lower().endswith('.xml')]
                print(f'    {len(xml_files)} XMLs in ZIP')
                for xml_name in xml_files:
                    prefix=make_prefix(ds_id,xml_name)
                    try: process_xml(zf.read(xml_name),cur,counter,prefix)
                    except Exception as e: print(f'    SKIP {xml_name}: {e}')
        except Exception as e: print(f'    SKIP zip: {e}')
    else:
        prefix=make_prefix(ds_id,path.name)
        try: process_xml(raw,cur,counter,prefix)
        except Exception as e: print(f'    SKIP: {e}')

def main():
    print('='*60)
    print('Step 1: Downloading timetable XMLs')
    print('='*60)
    files = download_datasets()

    for p in [DB,DB+'-shm',DB+'-wal']:
        try: Path(p).unlink()
        except: pass

    print('\n'+'='*60)
    print('Step 2: Creating database')
    print('='*60)
    conn=sqlite3.connect(DB)
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS services (id TEXT PRIMARY KEY, line_name TEXT, operator TEXT);
        CREATE TABLE IF NOT EXISTS trips (id TEXT PRIMARY KEY, service_id TEXT, departure_time TEXT);
        CREATE TABLE IF NOT EXISTS stop_times (id INTEGER PRIMARY KEY AUTOINCREMENT, trip_id TEXT, stop_id TEXT, arrival_time TEXT, departure_time TEXT, sequence INTEGER);
        CREATE TABLE IF NOT EXISTS bus_stops (atco_code TEXT PRIMARY KEY, common_name TEXT, latitude REAL, longitude REAL);
        CREATE TABLE IF NOT EXISTS stop_points (atco_code TEXT PRIMARY KEY, common_name TEXT);
    ''')
    conn.commit()
    print(f'Created {DB}')

    print('\n'+'='*60)
    print('Step 3: Parsing XMLs (Northwest only)')
    print('='*60)
    cur=conn.cursor(); counter=[0]
    for ds_id,path in zip(DATASET_IDS,files):
        process_file(path,cur,counter,ds_id)
        conn.commit()

    print('\n'+'='*60)
    print('Step 4: Building indexes')
    print('='*60)
    conn.executescript('''
        CREATE INDEX IF NOT EXISTS idx_st_stop     ON stop_times(stop_id);
        CREATE INDEX IF NOT EXISTS idx_st_trip     ON stop_times(trip_id);
        CREATE INDEX IF NOT EXISTS idx_st_trip_seq ON stop_times(trip_id,sequence);
        CREATE INDEX IF NOT EXISTS idx_trips_svc   ON trips(service_id);
        CREATE INDEX IF NOT EXISTS idx_bs_atco     ON bus_stops(atco_code);
    ''')
    conn.commit()

    print('\n'+'='*60)
    print('Summary')
    print('='*60)
    for t in ('services','trips','stop_times','bus_stops'):
        n=conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
        print(f'  {t}: {n:,}')
    conn.close()

    print(f'\nDone! Now run:')
    print(f'  cp {DB} /workspace/backend/bus.db')
    print(f'  cp {DB} /workspace/bus.db')

if __name__=='__main__':
    main()
