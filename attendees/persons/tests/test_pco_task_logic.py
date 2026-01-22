from unittest import TestCase
from unittest.mock import patch, MagicMock
from attendees.persons.tasks import pco_sync_task


class PCOTaskTest(TestCase):
    @patch('attendees.persons.tasks.PCOService')
    @patch('attendees.persons.tasks.Attendee')
    def test_pco_sync_task_calls_service(self, mock_attendee_model, mock_service_cls):
        # Setup mocks
        mock_service_instance = mock_service_cls.return_value

        mock_attendee = MagicMock()
        mock_attendee.id = '123'

        mock_queryset = MagicMock()
        mock_queryset.__iter__.return_value = [mock_attendee]
        mock_queryset.filter.return_value = mock_queryset

        mock_attendee_model.objects.filter.return_value = mock_queryset

        # Run task
        # We call the function directly (not as a celery task async)
        result = pco_sync_task(limit=10)

        # Verify
        mock_service_cls.assert_called_once()
        mock_service_instance.sync_attendee.assert_called_with(mock_attendee)
        self.assertEqual(result, "Synced 1 attendees")
