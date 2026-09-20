import hashlib
import json
from datetime import datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

class LessonEvent(BaseModel):
    """
    Immutable representation of a lesson slot (Weekly or Studio).
    
    Attributes:
        source_id: Unique hash of the original row data + row index.
        type: 'Weekly', 'Studio', or 'Lecture'
        student_name: Student Name
        instructor_name: Instructor Name
        course_code: Course Code (Strictly Preserved)
        start_dt: Lesson Start Datetime
        end_dt: Lesson End Datetime
        preferred_rooms: List of room IDs requested by instructor (from Excel)
        raw_row_data: Original JSON dump of the row for audit
        assigned_room: Mutable field for scheduling result
    """
    model_config = ConfigDict(frozen=False)  # assigned_room must be mutable

    source_id: str
    type: Literal['weekly_lesson', 'studio', 'lecture']
    student_name: str
    instructor_name: str
    course_code: str
    start_dt: datetime
    end_dt: datetime
    preferred_rooms: List[str] = Field(default_factory=list)
    raw_row_data: str
    
    # Scheduling Output (Mutable)
    assigned_room: Optional[str] = None
    assignment_reason: Optional[str] = None

    @staticmethod
    def generate_source_id(row_index: int, raw_data: dict) -> str:
        """
        Generates a deterministic hash from row index + content.
        Ensures uniqueness even if content is identical.
        """
        # Sort keys to ensure deterministic JSON str
        json_str = json.dumps(raw_data, sort_keys=True, default=str)
        payload = f"{row_index}:{json_str}"
        return hashlib.md5(payload.encode()).hexdigest()

    @property
    def duration_minutes(self) -> float:
        return (self.end_dt - self.start_dt).total_seconds() / 60
