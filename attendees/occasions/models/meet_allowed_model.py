from django.db import models


class MeetAllowedModel(models.Model):
    """The pages a meet is listed on.

    Every page that offers a choice of meets (gatherings, enrollments, attendances, the calendar)
    asks for the meets allowed for its model, so a meet that only records a status, such as
    "believed" or "baptized", stays off the attendance pages. This used to be the list in
    ``Meet.infos["allowed_models"]``, filtered with a regular expression over the JSON text.
    """

    GATHERING = "gathering"
    ATTENDINGMEET = "attendingmeet"
    ATTENDANCE = "attendance"
    EVENTRELATION = "eventrelation"
    MODELS = [
        (GATHERING, "gatherings"),
        (ATTENDINGMEET, "enrollments (attending meets)"),
        (ATTENDANCE, "attendances"),
        (EVENTRELATION, "calendar events"),
    ]
    #: What a new meet is listed on unless told otherwise.
    DEFAULT = (GATHERING, ATTENDINGMEET, ATTENDANCE, EVENTRELATION)

    meet = models.ForeignKey("occasions.Meet", on_delete=models.CASCADE, related_name="allowed_models")
    model = models.CharField(max_length=20, choices=MODELS)

    class Meta:
        db_table = "occasions_meet_allowed_models"
        constraints = [
            models.UniqueConstraint(fields=["meet", "model"], name="meet_allowed_model"),
        ]

    def __str__(self):
        return f"{self.meet} is listed on {self.get_model_display()}"
