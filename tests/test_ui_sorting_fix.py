
import pytest
from datetime import datetime

# Mimic the sort key logic from scheduling.py (current flawed version)
# And ideally the FIXED version to test against.

def _sort_key_flawed(e):
    # Day
    days = e.get('daysOfWeek', [])
    d = days[0] if days else 7 # <--- BUG: Default 7 pushes Studios to bottom
    # Time
    t_str = e.get('startTime') or e.get('start', '00:00:00')[-8:]
    if 'T' in t_str: t_str = t_str.split('T')[1]
    t_min = 0
    try:
        h, m = map(int, t_str[:5].split(':'))
        t_min = h * 60 + m
    except: pass
    return (d, t_min)

def _sort_key_fixed(e):
    # Day
    days = e.get('daysOfWeek', [])
    if days:
        d = days[0]
    else:
        d = 7
        if 'start' in e and 'T' in e['start']:
            try:
                # 2026-05-25 matches Monday
                dt = datetime.strptime(e['start'].split('T')[0], "%Y-%m-%d")
                # Python weekday: 0=Mon, 6=Sun
                py_d = dt.weekday()
                # Convert to JS: (py + 1) % 7 -> 0=Mon+1=1. 6=Sun+1=7%7=0.
                d = (py_d + 1) % 7
            except: pass
            
    # Remap for Sort: Mon(1)->1, ..., Sat(6)->6, Sun(0)->7
    sort_d = d if d != 0 else 7
    # Handling "Unknown" 7? -> 8 (Studio fail case)
    if d == 7: sort_d = 8
    
    # Time
    t_str = e.get('startTime') or e.get('start', '00:00:00')[-8:]
    if 'T' in t_str: t_str = t_str.split('T')[1]
    t_min = 0
    try:
        h, m = map(int, t_str[:5].split(':'))
        t_min = h * 60 + m
    except: pass
    return (sort_d, t_min)

def test_sorting_bug_reproduction():
    """
    Scenario:
    1. Weekly Lesson: Tuesday 10:00 (Day 1)
    2. Studio Class: Monday May 25 10:00 (Day 0)
    
    Expected: Studio (Mon) BEFORE Weekly (Tue)
    Current Bug: Studio (Day 7) AFTER Weekly (Day 1)
    """
    
    evt_weekly = {
        'id': 'w1',
        'type': 'weekly_lesson',
        'daysOfWeek': [2], # Tue (JS: 0=Sun, 1=Mon, 2=Tue)
        'startTime': '10:00:00'
    }
    
    evt_studio = {
        'id': 's1',
        'type': 'studio_class',
        # Monday May 25 2026
        'start': '2026-05-25T10:00:00', 
        'end': '2026-05-25T12:00:00'
    }
    
    # Check Flawed Logic
    k_w = _sort_key_flawed(evt_weekly)
    k_s = _sort_key_flawed(evt_studio)
    
    # Flawed: Studio(7, 600) > Weekly(1, 600) -> Studio comes LAST
    print(f"Flawed Keys: Weekly={k_w}, Studio={k_s}")
    assert k_s > k_w, "Bug reproduction failed: Flawed logic should sort Studio LAST"
    
    # Check Fixed Logic
    k_w_fix = _sort_key_fixed(evt_weekly)
    k_s_fix = _sort_key_fixed(evt_studio)
    
    # Fixed: Studio(0, 600) < Weekly(1, 600) -> Studio comes FIRST
    print(f"Fixed Keys: Weekly={k_w_fix}, Studio={k_s_fix}")
    assert k_s_fix < k_w_fix, "Fix validation failed: Studio (Mon) should sort BEFORE Weekly (Tue)"

if __name__ == "__main__":
    test_sorting_bug_reproduction()
