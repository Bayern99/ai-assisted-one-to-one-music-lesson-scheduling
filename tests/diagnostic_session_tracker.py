"""
Diagnostic Script: Track Lost Items During Unassign+Reassign

Purpose: Identify WHERE items disappear in the unassign→reassign cycle

Usage: 
1. Add logging calls to scheduling.py at key points
2. Run application, reproduce issue
3. Analyze output to find exact failure point
"""

import json
from datetime import datetime

class SessionStateTracker:
    """Diagnostic utility to track session state changes"""
    
    def __init__(self, log_file="debug_session_state.log"):
        self.log_file = log_file
        
    def log_state(self, operation, session_state):
        """Log current session state snapshot"""
        timestamp = datetime.now().isoformat()
        
        snapshot = {
            "timestamp": timestamp,
            "operation": operation,
            "generated_assignments_count": len(session_state.get('generated_assignments', [])),
            "unassigned_lessons_count": len(session_state.get('unassigned_lessons', [])),
            "generated_assignments_ids": [a.get('id') for a in session_state.get('generated_assignments', [])],
            "unassigned_lessons_ids": [u.get('id') for u in session_state.get('unassigned_lessons', [])]
        }
        
        with open(self.log_file, 'a') as f:
            f.write(f"\n{'='*80}\n")
            f.write(f"[{timestamp}] {operation}\n")
            f.write(json.dumps(snapshot, indent=2))
            f.write(f"\n{'='*80}\n")
            
        return snapshot
    
    def verify_item_moved(self, before, after, item_id):
        """Verify if item successfully moved between lists"""
        before_in_assigned = item_id in before.get('generated_assignments_ids', [])
        before_in_unassigned = item_id in before.get('unassigned_lessons_ids', [])
        
        after_in_assigned = item_id in after.get('generated_assignments_ids', [])
        after_in_unassigned = item_id in after.get('unassigned_lessons_ids', [])
        
        print(f"\n[DIAGNOSTIC] Item Movement Verification for {item_id}")
        print(f"  BEFORE: assigned={before_in_assigned}, unassigned={before_in_unassigned}")
        print(f"  AFTER:  assigned={after_in_assigned}, unassigned={after_in_unassigned}")
        
        if not before_in_assigned and not before_in_unassigned:
            print(f"  ❌ LOST: Item not found in EITHER list before operation")
        elif not after_in_assigned and not after_in_unassigned:
            print(f"  ❌ LOST: Item vanished - not in EITHER list after operation")
        elif before_in_assigned and after_in_unassigned:
            print(f"  ✅ MOVED: assigned → unassigned")
        elif before_in_unassigned and after_in_assigned:
            print(f"  ✅ MOVED: unassigned → assigned")
        else:
            print(f"  ⚠️  UNEXPECTED STATE")

# HOW TO USE IN scheduling.py:
"""
# Add at top of file:
tracker = SessionStateTracker()

# Before unassign:
before_unassign = tracker.log_state("BEFORE_UNASSIGN", st.session_state)

# After unassign:
after_unassign = tracker.log_state("AFTER_UNASSIGN", st.session_state)
tracker.verify_item_moved(before_unassign, after_unassign, slot_id)

# Before reassign:
before_assign = tracker.log_state("BEFORE_ASSIGN", st.session_state)

# After reassign:
after_assign = tracker.log_state("AFTER_ASSIGN", st.session_state)
tracker.verify_item_moved(before_assign, after_assign, new_evt['id'])
"""
