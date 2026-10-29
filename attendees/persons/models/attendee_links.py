"""Who may act for whom, as rows with foreign keys.

``Attendee.schedulers`` and ``Attendee.emergency_contacts`` are many-to-many fields through these
two tables. They used to be maps of attendee id to true or false inside ``Attendee.infos``, which
only Postgres could query and which kept the ids of people since merged or removed.
"""
from django.db import models
from attendees.history import track
from attendees.history.querysets import Tracked


@track
class AttendeeScheduler(Tracked, models.Model):
    """``scheduler`` may see and change ``attendee``'s activities: a parent for a child, a guardian
    for a ward, a caregiver for the person in their care."""

    attendee = models.ForeignKey("persons.Attendee", on_delete=models.CASCADE, related_name="+")
    scheduler = models.ForeignKey("persons.Attendee", on_delete=models.CASCADE, related_name="+")

    class Meta:
        db_table = "persons_attendee_schedulers"
        constraints = [
            models.UniqueConstraint(fields=["attendee", "scheduler"], name="attendee_scheduler"),
        ]

    def __str__(self):
        return f"{self.scheduler} schedules {self.attendee}"


@track
class AttendeeEmergencyContact(Tracked, models.Model):
    """``contact`` is who to call about ``attendee`` in an emergency, and who the organization
    writes to about them: a parent about a child, a spouse about a spouse."""

    attendee = models.ForeignKey("persons.Attendee", on_delete=models.CASCADE, related_name="+")
    contact = models.ForeignKey("persons.Attendee", on_delete=models.CASCADE, related_name="+")

    class Meta:
        db_table = "persons_attendee_emergency_contacts"
        constraints = [
            models.UniqueConstraint(fields=["attendee", "contact"], name="attendee_emergency_contact"),
        ]

    def __str__(self):
        return f"{self.contact} is an emergency contact of {self.attendee}"
