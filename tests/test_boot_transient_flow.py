import unittest

from core.app import App
from core.io_protocol import EventType, SourceKind, TargetKind, make_source


class BootTransientFlowTests(unittest.TestCase):
    def test_build_boot_event_marks_boot_turn_as_transient(self):
        event = App._build_boot_event(
            "start prompt",
            make_source(SourceKind.SYSTEM.value, "boot"),
        )

        self.assertEqual(event.session_id, "system:boot")
        self.assertEqual(event.type, EventType.MESSAGE.value)
        self.assertEqual(event.role, "user")
        self.assertEqual(event.target.kind, TargetKind.BROADCAST.value)
        self.assertTrue(event.metadata["transient"])
        self.assertTrue(event.metadata["boot_event"])


if __name__ == "__main__":
    unittest.main()
