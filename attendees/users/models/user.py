from django.contrib.auth.models import AbstractUser
from django.contrib.contenttypes.fields import GenericRelation
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import CharField
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from schedule.models import CalendarRelation

from attendees.persons.models import Utility
from attendees.whereabouts.models import Organization
from attendees.history import track
from attendees.history.querysets import TrackedUserManager


def allow_coworker(private_file):
    """
    Current bug: it gives across organizational access, but private_file.parent_object is None without
    PrivateStorageDetailView https://github.com/edoburu/django-private-storage#retrieving-files-by-object-id
    Todo 20230121: give scheduler/families access too
    """
    request = private_file.request
    current_user = request.user

    if current_user.is_authenticated:
        return current_user.is_superuser or current_user.belongs_to_groups_of(
                        current_user.organization.infos["groups_see_all_meets_attendees"]
                    )  # and current_user.attendee.under_same_org_with(other_attendee_id)
    return False


@track(exclude=("password",))
class User(AbstractUser):
    objects = TrackedUserManager()
    # Unique in the database since the first migration; AbstractUser's own field is not.
    email = models.EmailField(_("email address"), blank=True, unique=True)

    calendar_relations = GenericRelation(CalendarRelation)
    # First Name and Last Name do not cover name patterns around the globe.
    name = CharField(_("Name of User"), blank=True, max_length=255)
    first_name = None  # type: ignore
    last_name = None  # type: ignore
    organization = models.ForeignKey(
        Organization,
        null=True,
        blank=True,
        default=None,
        on_delete=models.SET_NULL,
        help_text="Primary organization of the user",
    )
    infos = models.JSONField(
        default=Utility.user_infos,
        null=True,
        blank=True,
        help_text="please keep {} here even there's no data",
    )

    def save(self, *args, **kwargs):
        self.email = self.email.strip()
        if self.email and User.objects.filter(email__iexact=self.email).exclude(username=self.username).exists():
            raise ValidationError("Identical email exists!")
        super(User, self).save(*args, **kwargs)

    def organization_pk(self):
        return self.organization.pk if self.organization else None

    def get_absolute_url(self):
        """Get url for user's detail view.

        Returns:
            str: URL for user detail.

        """
        return reverse("users:detail", kwargs={"username": self.username})

    def belongs_to_groups_of(
        self, auth_group_names
    ):  # .in_bulk() might take more memory
        return self.groups.filter(name__in=auth_group_names).exists()

    def belongs_to_organization_of(self, organization_slug):
        if self.is_superuser:
            return True
        else:
            return self.organization and self.organization.slug == organization_slug

    def can_see_all_organizational_meets_attendees(self):
        if self.organization:
            return self.belongs_to_groups_of(
                self.organization.infos["groups_see_all_meets_attendees"]
            )
        else:
            return False

    def privileged(self):
        """
        check if user's in correct groups to see other's data without relationships, currently are data_admins or counselor group
        Does NOT check if current user and targeting user are in the same organization!!
        :return: boolean
        """
        if self.organization:
            privileged_groups = self.organization.infos.get(
                "data_admins", []
            ) + self.organization.infos.get("counselor", [])
            return self.belongs_to_groups_of(privileged_groups)
        return False

    def privileged_to_edit(self, other_attendee_id):
        """
        check if user's in correct groups to see other attendee data (under same organization) without relationships, currently are data_admins or counselor group
        :return: boolean
        """
        if other_attendee_id and self.organization:
            if self.attendee_uuid_str() == other_attendee_id:
                return True

            return self.belongs_to_groups_of(
                self.organization.infos["groups_see_all_meets_attendees"]
            ) and self.attendee.under_same_org_with(other_attendee_id)
        return False

    def is_data_admin(self):
        organization_data_admin_group = (
            self.organization.infos.get("data_admins", []) if self.organization else []
        )
        return self.belongs_to_groups_of(organization_data_admin_group)

    def is_counselor(self):
        organization_counselor_groups = (
            self.organization.infos.get("counselor", []) if self.organization else []
        )
        return self.belongs_to_groups_of(organization_counselor_groups)

    def is_a(self, category=None):
        organization_categorized_groups = (
            self.organization.infos.get(category, []) if self.organization else []
        )
        return self.belongs_to_groups_of(organization_categorized_groups)

    def attendee_uuid_str(self):
        return str(self.attendee.id) if hasattr(self, "attendee") else ""

    def attend_divisions_of(self, division_slugs):
        return (
            self.attendee
            and self.attendee.attending_set.filter(
                divisions__slug__in=division_slugs
            ).exists()
        )

    def belongs_to_divisions_of(self, division_slugs):
        # if self.is_superuser:
        #     return True
        # else:
        return (
            self.organization
            and self.organization.division_set.filter(slug__in=division_slugs).exists()
        )

    def belongs_to_organization_and_division(self, organization_slug, division_slug):
        if self.is_superuser:
            return True
        else:
            return (
                self.organization
                and self.organization.slug == organization_slug
                and self.organization.division_set.filter(slug=division_slug).exists()
            )

    def attended_divisions_slugs(self):
        if self.attendee:
            return self.attendee.attending_set.values_list("division__slug", flat=True)
        else:
            return []

    def allowed_url_names(self, menu_category="API"):
        return (
            self.groups.filter(
                menuauthgroup__menu__organization=self.organization,
                menuauthgroup__menu__category=menu_category,
            )
            .values_list("menuauthgroup__menu__url_name", flat=True)
            .distinct()
        )
