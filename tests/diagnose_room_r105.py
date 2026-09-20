
import json
import sys
import os
from datetime import datetime, timedelta

def check_overlaps(file_path):
    print(f"📂 Loading {file_path}...")
    with open(file_path, 'r') as f:
        data = json.load(f)
        
    r105_events = [e for e in data if e.get('resourceId') == 'R105']
    print(f"found {len(r105_events)} events in R105")
    
    # Expand to concrete slots
    # Map: Date -> List of (StartMin, EndMin, Title, Type)
    from collections import defaultdict
    schedule = defaultdict(list)
    
    start_sem = datetime(2026, 2, 24)
    end_sem = datetime(2026, 6, 30)
    
    for evt in r105_events:
        etype = evt.get('type', 'unknown')
        title = evt.get('title', 'No Title')
        inst = evt.get('extendedProps', {}).get('Instructor', 'Unknown')
        
        # 1. Studio
        if etype == 'studio_class':
            if 'start' in evt:
                dt_str = evt['start']
                # ISO
                dt = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S")
                date_key = dt.strftime("%Y-%m-%d")
                s_min = dt.hour * 60 + dt.minute
                
                if 'end' in evt:
                    end_dt = datetime.strptime(evt['end'], "%Y-%m-%dT%H:%M:%S")
                    e_min = end_dt.hour * 60 + end_dt.minute
                else:
                    e_min = s_min + 60
                    
                schedule[date_key].append({
                    's': s_min, 'e': e_min, 'title': title, 'inst': inst, 'type': 'studio', 'id': evt['id']
                })
        
        # 2. Weekly
        elif etype == 'weekly_lesson':
            days = evt.get('daysOfWeek', [])
            st_str = evt.get('startTime', '00:00:00')
            et_str = evt.get('endTime', '00:00:00')
            
            sh, sm = map(int, st_str.split(':')[:2])
            eh, em = map(int, et_str.split(':')[:2])
            s_min = sh * 60 + sm
            e_min = eh * 60 + em
            
            # Expand
            curr = start_sem
            while curr <= end_sem:
                # JS Day: 0=Sun, 1=Mon...
                # Py Day: 0=Mon, 6=Sun
                # Check match
                py_dow = curr.weekday() # 0=Mon
                js_dow = (py_dow + 1) % 7 # 1=Mon
                
                if js_dow in days:
                    date_key = curr.strftime("%Y-%m-%d")
                    schedule[date_key].append({
                        's': s_min, 'e': e_min, 'title': title, 'inst': inst, 'type': 'weekly', 'id': evt['id']
                    })
                curr += timedelta(days=1)

    # Check overlaps
    print("\n🔍 Scanning for Overlaps...")
    found_any = False
    sorted_dates = sorted(schedule.keys())
    
    for d in sorted_dates:
        evts = schedule[d]
        evts.sort(key=lambda x: x['s'])
        
        for i in range(len(evts)):
            for j in range(i+1, len(evts)):
                e1 = evts[i]
                e2 = evts[j]
                
                # Intersection?
                # (Start1 < End2) and (End1 > Start2)
                if (e1['s'] < e2['e']) and (e1['e'] > e2['s']):
                    print(f"⚠️ OVERLAP on {d} (Wed?):")
                    print(f"   1. {e1['s']//60}:{e1['s']%60:02d}-{e1['e']//60}:{e1['e']%60:02d} | {e1['inst']} ({e1['type']})")
                    print(f"   2. {e2['s']//60}:{e2['s']%60:02d}-{e2['e']//60}:{e2['e']%60:02d} | {e2['inst']} ({e2['type']})")
                    found_any = True

    if not found_any:
        print("✅ No overlaps found in bookings.json data.")

if __name__ == "__main__":
    check_overlaps("data/bookings.json")
