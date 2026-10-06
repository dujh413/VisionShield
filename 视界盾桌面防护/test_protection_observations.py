"""仅模拟时间和状态，不打开摄像头或使用真人数据。"""
import unittest

from protection_state import ProtectionState


def observation(sequence, stamp, session=None, received=False):
    return {'sequence':sequence, 'received_at' if received else 'observed_at':stamp, 'session':session}


def recorded(sequence, stamp, risk_sequence=0, risk_at=None, session=None):
    return {**observation(sequence,stamp,session), 'last_risk_sequence':risk_sequence,
            'last_risk_observed_at':risk_at}


class ObservationRecoveryTests(unittest.TestCase):
    def test_one_safe_packet_repeated_by_ui_cannot_remove_protection(self):
        state=ProtectionState()
        packet=observation(1,100)
        for now in (100.2,100.6,101.0,101.2,101.4):
            self.assertTrue(state.update(now,False,packet))
        self.assertTrue(state.update(101.6,False,packet))
        self.assertIsNone(state.safe_since)
        self.assertEqual(state.evidence_error,'stale')

    def test_safe_duration_uses_observation_time_instead_of_ui_receive_time(self):
        state=ProtectionState()
        self.assertTrue(state.update(100.7,False,observation(1,100)))
        self.assertTrue(state.update(101.4,False,observation(2,100.3)))
        self.assertTrue(state.update(101.45,False,observation(3,100.6)))
        self.assertFalse(state.update(101.5,False,observation(4,101)))

    def test_new_risk_immediately_resets_safe_interval_even_on_repeated_packet(self):
        state=ProtectionState()
        packet=observation(1,10)
        state.update(10,False,packet)
        self.assertTrue(state.update(10.6,True,packet))
        self.assertIsNone(state.safe_since)
        self.assertTrue(state.update(10.8,False,observation(2,10.8)))
        self.assertTrue(state.update(11.2,False,observation(3,11.2)))
        self.assertFalse(state.update(11.8,False,observation(4,11.8)))

    def test_sequence_gap_restarts_pending_and_already_recovered_safety(self):
        state=ProtectionState()
        state.update(0,False,observation(1,0))
        self.assertFalse(state.update(1,False,observation(2,1)))
        self.assertTrue(state.update(1.2,False,observation(5,1.2)))
        self.assertEqual(state.evidence_error,'gap')
        self.assertTrue(state.update(1.3,False,observation(5,1.2)))
        self.assertEqual(state.evidence_error,'gap')
        self.assertTrue(state.update(1.9,False,observation(6,1.9)))
        self.assertIsNone(state.evidence_error)
        self.assertFalse(state.update(2.3,False,observation(7,2.3)))

    def test_latest_only_safe_packets_with_complete_history_recover(self):
        state=ProtectionState()
        for index in range(6):
            protecting=state.update(index*.25,False,recorded(1+index*3,index*.25))
        self.assertFalse(protecting)
        self.assertIsNone(state.evidence_error)
        self.assertFalse(state.update(1.4,False,recorded(22,1.4)))

    def test_skipped_uncertain_observation_cannot_borrow_old_safe_duration(self):
        state=ProtectionState()
        state.update(0,False,recorded(1,0))
        state.update(.8,False,recorded(3,.8))
        self.assertTrue(state.update(1.1,False,recorded(6,1.1,4,.9)))
        self.assertIsNone(state.safe_since)
        self.assertTrue(state.update(1.3,False,recorded(8,1.3,4,.9)))
        self.assertTrue(state.update(1.9,False,recorded(11,1.9,4,.9)))
        self.assertFalse(state.update(2.4,False,recorded(14,2.4,4,.9)))

    def test_complete_history_does_not_bridge_observation_outage(self):
        for next_sequence in (2,20):
            with self.subTest(next_sequence=next_sequence):
                state=ProtectionState()
                state.update(0,False,recorded(1,0))
                self.assertTrue(state.update(2,False,recorded(next_sequence,2)))
                self.assertEqual(state.safe_since,2)
                self.assertEqual(state.evidence_error,'gap')

    def test_complete_history_does_not_turn_repeated_frame_into_safe_duration(self):
        state=ProtectionState()
        packet=recorded(1,0)
        state.update(0,False,packet)
        self.assertTrue(state.update(1.2,False,packet))
        self.assertTrue(state.update(1.6,False,packet))
        self.assertEqual(state.evidence_error,'stale')

    def test_invalid_missing_or_regressed_complete_history_fails_closed(self):
        invalid=(recorded(3,1.1,True,None),recorded(3,1.1,4,1),
                 recorded(3,1.1,0,1),recorded(3,1.1,1,None),
                 recorded(3,1.1,1,float('nan')),recorded(3,1.1,1,2),
                 {'sequence':3,'observed_at':1.1,'last_risk_sequence':0},
                 observation(3,1.1),recorded(3,1.1,0,None),recorded(3,1.1,1,.2))
        for packet in invalid:
            with self.subTest(packet=packet):
                state=ProtectionState()
                state.update(0,True,recorded(1,0,1,0))
                state.update(.9,False,recorded(2,.9,1,0))
                self.assertTrue(state.update(1.1,False,packet))
                self.assertIsNone(state.safe_since)
                self.assertEqual(state.last_observation,(None,2,.9))

    def test_new_session_with_complete_history_starts_its_own_safe_interval(self):
        state=ProtectionState()
        state.update(0,False,recorded(20,0,session='first'))
        self.assertTrue(state.update(.9,False,recorded(1,.9,session='second')))
        self.assertEqual(state.evidence_error,'session_changed')
        self.assertTrue(state.update(1.2,False,recorded(4,1.2,session='second')))
        self.assertFalse(state.update(2,False,recorded(8,2,session='second')))

    def test_session_switch_cannot_borrow_previous_safe_duration(self):
        state=ProtectionState()
        state.update(0,False,observation(20,0,'first',received=True))
        self.assertTrue(state.update(.8,False,observation(1,.8,'second',received=True)))
        self.assertEqual(state.evidence_error,'session_changed')
        self.assertTrue(state.update(1.6,False,observation(2,1.6,'second',received=True)))
        self.assertFalse(state.update(1.9,False,observation(3,1.9,'second',received=True)))

    def test_duplicate_fresh_observation_does_not_make_recovered_screen_flicker(self):
        state=ProtectionState(restore_delay=0)
        packet=observation(1,3)
        self.assertFalse(state.update(3,False,packet))
        self.assertFalse(state.update(3.8,False,packet))
        self.assertTrue(state.update(4.6,False,packet))

    def test_stale_observation_cannot_preserve_or_create_recovery(self):
        state=ProtectionState(restore_delay=0)
        self.assertFalse(state.update(0,False,observation(1,0)))
        self.assertTrue(state.update(2,False,observation(2,.3)))
        self.assertIsNone(state.safe_since)

    def test_out_of_order_sequence_or_timestamp_resets_recovery_without_lowering_watermark(self):
        for packet in (observation(1,1.2),observation(3,.8),observation(2,1.2)):
            with self.subTest(packet=packet):
                state=ProtectionState()
                state.update(0,False,observation(1,0))
                state.update(.9,False,observation(2,.9))
                self.assertTrue(state.update(1.2,False,packet))
                self.assertIsNone(state.safe_since)
                self.assertEqual(state.evidence_error,'out_of_order')
                self.assertEqual(state.last_observation,(None,2,.9))
                self.assertTrue(state.update(1.3,False,observation(3,1.3)))
                self.assertFalse(state.update(2.4,False,observation(4,2.4)))

    def test_missing_future_nonfinite_and_invalid_fields_cannot_restore_even_with_zero_delay(self):
        invalid=(None,{},observation(1,4),observation(1,float('nan')),
                 observation(1,float('inf')),observation(True,3),
                 observation(-1,3),observation(1,3,session=''),
                 observation(1,3,session=42),{'sequence':1,'observed_at':True})
        for packet in invalid:
            with self.subTest(packet=packet):
                self.assertTrue(ProtectionState(restore_delay=0).update(3,False,packet))

    def test_explicit_missing_observation_cannot_use_legacy_time_fallback(self):
        state=ProtectionState()
        self.assertTrue(state.update(0,False,None))
        self.assertEqual(state.evidence_error,'missing')
        self.assertTrue(state.update(2,False,None))

    def test_zero_delay_accepts_first_legitimate_new_safe_observation(self):
        self.assertFalse(ProtectionState(restore_delay=0).update(4,False,observation(20,3.9)))

    def test_legacy_non_sensor_state_calls_keep_existing_behavior(self):
        state=ProtectionState()
        self.assertTrue(state.update(0,False))
        self.assertFalse(state.update(1,False))
        self.assertTrue(state.update(2,True))


if __name__=='__main__':unittest.main()
