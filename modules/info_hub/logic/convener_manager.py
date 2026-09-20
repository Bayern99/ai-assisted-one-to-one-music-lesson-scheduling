import csv
import json
import logging
import os
import re
import pandas as pd
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Tuple, Dict

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "data")
CONVENER_CACHE_FILE = os.path.join(DATA_DIR, "conveners.json")
CSV_SOURCE_FILE = os.path.join(DATA_DIR, "Course Convener .csv")

@dataclass
class CourseConvener:
    course_code: str        # "MUS1263"
    course_title: str       # "Demo Course I (Piano) (1001)"
    convener_name: str      # "Instructor 0008"
    teachers: List[str]     # ["Instructor 0009", ...]
    instrument_family: str  # "Piano"
    year_level: int         # 1, 2, 3, 4

    @staticmethod
    def from_dict(data: dict) -> 'CourseConvener':
        return CourseConvener(**data)

class ConvenerManager:
    def __init__(self):
        self.conveners: List[CourseConvener] = []
        self._load_data()

    def _load_data(self):
        """Load from JSON cache if exists, otherwise try to import from Source CSV."""
        if os.path.exists(CONVENER_CACHE_FILE):
            with open(CONVENER_CACHE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.conveners = [CourseConvener.from_dict(d) for d in data]
    def import_conveners_from_csv(self, file_obj=None) -> int:
        """Parses the specific format of the Course Convener CSV."""
        source = file_obj if file_obj else CSV_SOURCE_FILE
        
        # Determine how to read based on input type
        # If string (path) and not exists, return 0
        if isinstance(source, str) and not os.path.exists(source):
            return 0
            
        try:
            # Using pandas is more robust for encoding/BOM than raw csv module
            encodings = ['utf-8', 'utf-8-sig', 'gbk', 'iso-8859-1']
            df = None
            
            for enc in encodings:
                try:
                    # Reset buffer position if file-like object
                    if hasattr(source, 'seek'):
                        source.seek(0)
                    df = pd.read_csv(source, encoding=enc)
                    break
                except UnicodeDecodeError:
                    continue
                except Exception as e:
                    logger.warning("Read error with encoding %s: %s", enc, e)
                    continue

            if df is None:
                logger.error("Failed to read CSV with any encoding.")
                return 0

            # Fuzzy Match Headers ONCE (outside loop)
            def get_col(candidates):
                for c in df.columns:
                    c_clean = str(c).strip().lower()
                    for cand in candidates:
                        if cand.lower() in c_clean:
                            return c
                return None

            col_code = get_col(['Course Code', 'Code', 'Subject Code'])
            col_title = get_col(['Course (Session) Title', 'Title', 'Course Title'])
            col_teacher = get_col(['Teacher', 'Instructor'])
            col_convener = get_col(['Course Convener', 'Convener'])
            
            logger.debug("Found columns: code=%s, title=%s, teacher=%s, convener=%s", col_code, col_title, col_teacher, col_convener)
            
            if not col_code:
                logger.error("Could not find Course Code column!")
                return 0
            
            # Process DataFrame
            new_data = []
            for _, row in df.iterrows():
                # Safe access using column names directly
                c_code = str(row[col_code]).strip() if col_code and col_code in row.index else ""
                if not c_code or c_code.lower() == 'nan': 
                    continue
                
                c_title = str(row[col_title]).strip() if col_title and col_title in row.index else ""
                c_convener = str(row[col_convener]).strip() if col_convener and col_convener in row.index else ""
                
                c_teachers_raw = str(row[col_teacher]).strip() if col_teacher and col_teacher in row.index else ""
                teachers = [t.strip() for t in c_teachers_raw.split('&') if t.strip()]
                
                inst, year = self.extract_instrument_and_year(c_code, c_title)
                
                convener = CourseConvener(
                    course_code=c_code,
                    course_title=c_title,
                    convener_name=c_convener,
                    teachers=teachers,
                    instrument_family=inst,
                    year_level=year
                )
                new_data.append(convener)
                
            if new_data:
                self.conveners = new_data
                self._save_cache()
                logger.info("Successfully imported %d conveners.", len(self.conveners))
                return len(self.conveners)
            
            return 0

        except Exception as e:
            logger.error("Error importing CSV: %s", e)
            import traceback
            traceback.print_exc()
            return 0

    def _save_cache(self):
        with open(CONVENER_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump([asdict(c) for c in self.conveners], f, indent=2, ensure_ascii=False)

    def extract_instrument_and_year(self, course_code: str, title: str) -> Tuple[str, int]:
        """
        Extracts Instrument Family and Year Level.
        Year Logic:
        PI I   -> Year 1
        PI III -> Year 2
        PI V   -> Year 3
        PI VII -> Year 4
        """
        # 1. Instrument Family from Title
        # "Demo Course I (Piano) ..." -> Piano
        # "Demo Instruction I (Chinese Instruments) ..." -> Chinese Instruments
        # "Demo Instruction I (Woodwind) ..." -> Woodwinds (Standardize?) user uses "Woodwind" in CSV
        
        inst = "Unknown"
        title_lower = title.lower()
        if "piano" in title_lower: inst = "Piano"
        elif "voice" in title_lower: inst = "Voice"
        elif "strings" in title_lower: inst = "Strings"
        elif "woodwind" in title_lower: inst = "Woodwinds" # Standardize to plural usually used in system
        elif "brass" in title_lower: inst = "Brass"
        elif "percussion" in title_lower: inst = "Percussion"
        elif "chinese" in title_lower: inst = "Chinese Instruments"
        
        # 2. Year Level from Title Roman Numerals
        # PI I -> 1, III -> 2, V -> 3, VII -> 4
        year = 1
        if " VII" in title: year = 4
        elif " V" in title: year = 3
        elif " III" in title: year = 2
        elif " I" in title: year = 1
        
        return inst, year

    def get_convener_for_course(self, course_code: str) -> Optional[str]:
        for c in self.conveners:
            if c.course_code == course_code:
                return c.convener_name
        return None

    def get_courses_for_convener(self, convener_name: str) -> List[CourseConvener]:
        """Return full objects, not just codes."""
        return [c for c in self.conveners if c.convener_name == convener_name]

    def get_course_code_by_instrument_and_year(self, instrument: str, year: str) -> Optional[str]:
        """
        Lookup Course Code.
        instrument: "Piano", "Voice"...
        year: "1", "2", "3", "4"
        """
        # Map year string to int
        try:
            y_int = int(year)
        except:
            return None
            
        # Standardize instrument string matching
        # The CSV has "Woodwind", system often uses "Woodwinds". "Strings" matches.
        
        for c in self.conveners:
            # Check Year
            if c.year_level != y_int:
                continue
                
            # Check Instrument (fuzzy match)
            # System: "Woodwinds" vs CSV "Woodwind"
            # CSS: "Chinese Instruments"
            
            # Simple containment
            c_inst = c.instrument_family.lower()
            target_inst = instrument.lower()
            
            # Special handling for plurals
            if "woodwind" in target_inst and "woodwind" in c_inst: return c.course_code
            if "string" in target_inst and "string" in c_inst: return c.course_code
            if target_inst in c_inst or c_inst in target_inst:
                return c.course_code
                
        return None
