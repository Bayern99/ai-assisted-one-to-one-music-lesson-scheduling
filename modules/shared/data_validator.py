import pandas as pd
from typing import List, Dict

class DataValidator:
    """
    Validates Data Integrity between Input (Uploads) and Output (Bookings).
    Ensures 'Three Layers of Truth'.
    """
    
    def validate_round_trip(self, input_df, output_bookings, failed_list):
        """
        Verify: Input Count = Output Count + Failed Count
        This ensures NO data is silently dropped.
        """
        if input_df is None:
            return {"status": "SKIP", "messages": ["⚠️ No input data provided for validation"]}
            
        input_count = len(input_df)
        
        # Filter for only auto-generated output events (to match input)
        # Note: We need to be careful if output includes Studio but input_df is only Weekly.
        # Ideally we pass total input count.
        # Assuming input_df is the PRIMARY driver (Weekly).
        
        output_count = len([b for b in output_bookings 
                            if b.get('extendedProps', {}).get('auto_generated') 
                            and b.get('type') == 'weekly_lesson'])
                            
        # Filter failed list for Weekly only (FIX 1)
        # Check if 'id' starts with 'wk_' or if strict type metadata exists
        weekly_failed = [f for f in failed_list if str(f.get('id', '')).startswith('wk_')]
        failed_count = len(weekly_failed)
        
        total_accounted = output_count + failed_count
        
        report = {
            "input_count": input_count,
            "output_count": output_count,
            "failed_count": failed_count,
            "total_accounted": total_accounted,
            "balanced": input_count == total_accounted,
            "messages": []
        }
        
        if not report["balanced"]:
            diff = input_count - total_accounted
            report["status"] = "FAIL"
            report["messages"].append(
                f"❌ IMBALANCED: Input={input_count} != Output({output_count}) + Failed({failed_count}). Missing {diff} records."
            )
        else:
            report["status"] = "PASS"
            report["messages"].append(
                f"✅ BALANCED: {input_count} Input = {output_count} Scheduled + {failed_count} Unassigned"
            )
        
        return report

    def validate_field_integrity(self, bookings):
        """
        Verify all 8 standard fields exist in extendedProps for generated events.
        """
        from modules.shared.field_schema import WEEKLY_FIELDS
        
        issues = []
        checked_count = 0
        
        for b in bookings:
            props = b.get('extendedProps', {})
            # Only validate events marked as ours
            if not props.get('auto_generated'):
                continue
            
            checked_count += 1
            missing = []
            for field in WEEKLY_FIELDS:
                if field not in props:
                    missing.append(field)
            
            if missing:
                issues.append(f"Event {b.get('id')} missing fields: {missing}")
                
        status = "PASS"
        if issues:
            status = "FAIL"
            
        return {
            "status": status,
            "total_checked": checked_count,
            "issues": issues,
            "issue_count": len(issues)
        }

    def generate_diff_report(self, old_bookings, new_bookings):
        """
        Compare before/after snapshot.
        """
        added = len(new_bookings) - len(old_bookings)
        return f"Changes: {added} events added."
