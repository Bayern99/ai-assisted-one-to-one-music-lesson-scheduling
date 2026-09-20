import datetime
import logging
import re

from modules.shared.time_parser import TimeParser

logger = logging.getLogger(__name__)

def parse_chinese_date(date_str):
    """
    Parses '2026年3月30日' or '2026年3月30日 星期一' into 'YYYY-MM-DD'.
    Returns None if failed.
    """
    if not date_str or not isinstance(date_str, str):
        return None
        
    try:
        # Regex for YYYY年M月D日
        m = re.search(r'(\d{4})年(\d+)月(\d+)日', date_str)
        if m:
            y, m, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return f"{y:04d}-{m:02d}-{d:02d}"
    except Exception:
        pass
    return None

def generate_semester_dates(start_date_str, end_date_str, target_weekday_idx):
    """
    Generates a list of YYYY-MM-DD strings for every occurrence of 
    target_weekday_idx (0=Mon, 6=Sun) between start and end (inclusive).
    """
    try:
        start = TimeParser.parse_date(start_date_str)
        end = TimeParser.parse_date(end_date_str)
        if start is None or end is None:
            raise ValueError("invalid semester bounds")
        
        dates = []
        curr = start
        
        # Advance to first occurrence
        while curr.weekday() != target_weekday_idx:
            curr += datetime.timedelta(days=1)
            
        # Collect all
        while curr <= end:
            dates.append(curr.strftime("%Y-%m-%d"))
            curr += datetime.timedelta(days=7)
            
        return dates
    except Exception as e:
        logger.warning("Calendar Gen Error: %s", e)
        return []

def is_date_in_range(date_str, start_str, end_str):
    """Checks if a date is within semester bounds"""
    try:
        d = TimeParser.parse_date(date_str)
        s = TimeParser.parse_date(start_str)
        e = TimeParser.parse_date(end_str)
        if d is None or s is None or e is None:
            return False
        return s <= d <= e
    except:
        return False
