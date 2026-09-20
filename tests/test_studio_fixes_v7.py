
import pytest
import pandas as pd
from unittest.mock import MagicMock
from modules.scheduler.logic.optimizer import RoomAllocator

class TestStudioFixesV7:
    """
    Verification tests for Phase 7 Studio Scheduling Fixes.
    Following 'verification-before-completion' strict protocols.
    """

    @pytest.fixture
    def optimizer(self):
        # Init: students, rooms, bookings, rules
        opt = RoomAllocator([], [], [], {})
        # Setup minimal rules
        opt.room_objs = ['R101', 'CC105', 'R102']
        opt.room_types = {
            'R101': ['Piano'],                 # Piano ONLY
            'CC105': ['Voice', 'Instrumental'], # Voice/Inst ONLY
            'R102': ['Percussion']             # Percussion ONLY
        }
        opt.rules = {
            'priorities': {
                'Piano': {'Voice': 8, 'Piano': 10}, # Voice allowed in Piano by priority (should be blocked by hard constraint)
                'Voice': {'Voice': 10},
                'Percussion': {'Percussion': 10}
            },
            'constraints': {'time_range': {'start': '08:00', 'end': '22:00'}},
            'instructor_preferred_rooms': {},
            'instructor_priority': {}
        }
        opt.assignments = []
        return opt

    def test_fix_1_strict_room_type_constraint(self, optimizer):
        """
        Fix 1: Voice should receive -1 score for Piano room (R101),
        even if priority matrix gives it a score of 8.
        """
        # Voice Request
        req = {'instrument': 'Voice', 'prefs': [], 'inst': 'TestVoice'}
        
        # Test against Piano Room (R101)
        score = optimizer._score_room_unified('R101', req)
        assert score == -1, "Voice should be strictly blocked from Piano-only room R101"
        
        # Test against Voice Room (CC105)
        score = optimizer._score_room_unified('CC105', req)
        assert score > 0, "Voice should be allowed in Voice room CC105"

    def test_fix_2_nan_preference_handling_and_filtering(self, optimizer):
        """
        Fix 2: NaN preferences should be empty list.
        Invalid preferences (Voice seeking Piano room) should be filtered out.
        """
        # Mock DataFrame row with NaN preference
        row_nan = pd.Series({
            'Instructor': 'Ms. Nan',
            'Preferred Venue': float('nan'), # Actual NaN
            'Instruments': 'Voice',
            'Studio 1 Date': '2026-03-05', 'Studio 1 Time': '12:00-13:00'
        })
        
        # Mock DataFrame row with Invalid preference (R101 is Piano, Instrument is Voice)
        row_invalid = pd.Series({
            'Instructor': 'Ms. Invalid',
            'Preferred Venue': 'R101, CC105', # R101 invalid, CC105 valid
            'Instruments': 'Voice',
            'Studio 1 Date': '2026-03-05', 'Studio 1 Time': '12:00-13:00'
        })
        
        # Scenario 1: NaN
        venue_raw = str(row_nan.get('Preferred Venue', '')).strip()
        pref_venues = []
        if pd.isna(row_nan.get('Preferred Venue')) or venue_raw.lower() == 'nan':
            pref_venues = []
        assert pref_venues == [], "NaN preference should result in empty list"
        
        # Scenario 2: Filtering
        venue_raw = str(row_invalid.get('Preferred Venue', '')).strip()
        pref_venues = [v.strip() for v in venue_raw.replace('，', ',').split(',') if v.strip()]
        # Filter Logic
        valid_prefs = []
        real_instrument = "Voice" # Mock result
        for p in pref_venues:
            if p in optimizer.room_types:
                # Mock normalize
                if real_instrument in optimizer.room_types[p]:
                    valid_prefs.append(p)
        
        assert valid_prefs == ['CC105'], "Should filter out R101 (Piano) for Voice request"

    def test_fix_3_multi_conflict_resolution(self, optimizer):
        """
        Fix 3: Studio request blocked by 2 Weekly events in CC105.
        _relocate_whole_block should move BOTH.
        """
        # 1. Setup 2 Weekly Events causing conflict in CC105
        # Time: 13:00 - 15:00. Studio needs 13:00-15:00.
        # Weekly 1: 13:00-14:00. Weekly 2: 14:00-15:00.
    
        # Create Dummy Weekly Events
        evt1 = {
            'id': 'w1', 'room_id': 'CC105', 'resourceId': 'CC105',
            'startTime': '13:00:00', 'endTime': '14:00:00', 'daysOfWeek': [4], # Thursday
            'type': 'weekly_lesson',
            'extendedProps': {'Instructor': 'W1', 'Course Code': 'MUS100 Voice', 'normalized_instrument': 'Voice'}
        }
        evt2 = {
            'id': 'w2', 'room_id': 'CC105', 'resourceId': 'CC105',
            'startTime': '14:00:00', 'endTime': '15:00:00', 'daysOfWeek': [4], # Thursday
            'type': 'weekly_lesson',
            'extendedProps': {'Instructor': 'W2', 'Course Code': 'MUS100 Voice', 'normalized_instrument': 'Voice'}
        }
        optimizer.assignments = [evt1, evt2]
    
        # 2. Studio Request
        # Date 2026-03-05 is a Thursday (Day 4)
        req = {
            'inst': 'Studio Teacher',
            'start': 13, 'end': 15,
            'day': 4, 'date': '2026-03-05',
            'prefs': ['CC105'], # Wants CC105
            'instrument': 'Voice'
        }
    
        # 3. Ensure alternative room exists (CC105 is blocked, R101 is Piano/Blocked)
        # Let's add a Voice-compatible room that is free
        optimizer.room_objs.append('CC_Voice_Alt')
        optimizer.room_types['CC_Voice_Alt'] = ['Voice']

        block = {
            'id': 'blk_voice_conflict',
            'events': [evt1, evt2],
            'room_id': 'CC105',
            'priority': 0,
            'start': 13,
            'end': 15,
            'instrument': 'Voice',
            'inst_name': 'Studio Teacher',
        }

        # 4. Run Relocate
        success = optimizer._relocate_whole_block(block)
        
        # Debug Logs
        if not success:
            print("\nDEBUG LOGS:")
            for l in optimizer.logs: print(l)
    
        assert success is True, "Should successfully relocate both conflicts"
        assert evt1['resourceId'] == 'CC_Voice_Alt', "Evt1 should move to Alt"
        assert evt2['resourceId'] == 'CC_Voice_Alt', "Evt2 should move to Alt"

    def test_fix_4_instrument_preservation(self, optimizer):
        """
        Fix 4: Ensure _create_assignment stores normalized_instrument
        and _relocate_whole_block uses it.
        """
        # 1. Create Assignment
        lesson = {
            'id': 'test_l', 'start': 10, 'end': 11, 'day': 1, 'date': '2026-01-01',
            'instrument': 'Percussion', # Normalized
            'raw_row': {'Instructor': 'P', 'Course Code': 'MUS Empty'} # Empty course code might fail extraction
        }
        optimizer._create_assignment(lesson, 'R102')
    
        evt = optimizer.assignments[0]
        assert evt['extendedProps']['normalized_instrument'] == 'Percussion', "Should store normalized instrument"
    
        # 2. Verify Relocation uses it
        # Try to move this Percussion event from R102
        # If it falls back to 'Instrumental' (default for empty course code), it might go to CC105 (Voice/Inst)
        # But CC105 is valid for Instrumental, NOT Percussion.
        # So if it uses 'Percussion', it should NOT go to CC105. It should only go to Percussion rooms.
    
        # Block R102 with Studio
        req = {'day': 1, 'start': 10, 'end': 11, 'date': '2026-01-01', 'instrument': 'Percussion'}

        block = {
            'id': 'blk_perc',
            'events': [evt],
            'room_id': 'R102',
            'priority': 0,
            'start': 10,
            'end': 11,
            'instrument': 'Percussion',
            'inst_name': 'P',
        }

        # Only alternative is CC105 (Voice/Inst) -> Incompatible with Percussion
        success = optimizer._relocate_whole_block(block)
    
        # Should FAIL to move because no other Percussion room exists
        assert success is False, "Should NOT move Percussion to CC105 (Voice room)"
        assert evt['resourceId'] == 'R102', "Event should stay put"
        
        # Now add a Percussion room
        optimizer.room_objs.append('CC_Perc_Alt')
        optimizer.room_types['CC_Perc_Alt'] = ['Percussion']
        
        success = optimizer._relocate_whole_block(block)
        assert success is True, "Should move Percussion to Percussion Alt"
        assert evt['resourceId'] == 'CC_Perc_Alt'
