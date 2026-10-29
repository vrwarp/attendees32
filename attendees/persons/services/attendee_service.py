from datetime import datetime, timezone
from collections import defaultdict
from pathlib import Path
from partial_date import PartialDate
from django.contrib.contenttypes.models import ContentType
from django.db.models import Case, Exists, Min, OuterRef, Q, When
from django.utils.timezone import localdate
from rest_framework.utils import json

from attendees.occasions.models import Meet
from attendees.persons.models import (  # , Relationship
    Attendee,
    AttendeeEmergencyContact,
    AttendeeScheduler,
    Attending,
    AttendingMeet,
    Category,
    Folk,
    FolkAttendee,
    Registration,
    Relation,
    Utility, Past)
from attendees.persons.services import AttendingService, FolkService
from attendees.whereabouts.models import Place
from attendees.whereabouts.services import PlaceService


class AttendeeService:
    @staticmethod
    def by_assembly_meets(assembly_slug, meet_slugs):
        return Attendee.objects.filter(
            attendings__meets__slug__in=meet_slugs,
            attendings__meets__assembly__slug=assembly_slug,
        ).order_by("last_name", "last_name2", "first_name", "first_name2")

    @staticmethod
    def details(current_user, attendee_id):

        return []

    @staticmethod
    def find_related_ones(
        current_user, target_attendee, querying_attendee_id, filters_list
    ):
        """
        return target_attendee's related ones, including dead ones, according to current_user permissions
        :param current_user:
        :param target_attendee:
        :param querying_attendee_id:
        :param filters_list:
        # :param priority: indicate what return result should sort by
        :return: related attendees of targeting attendee, or matched attendee depends on filter conditions and
                 current user permissions
        """

        if current_user and target_attendee:
            qs = (
                Attendee.objects
                if current_user.privileged
                else target_attendee.related_ones
            )
            if querying_attendee_id:
                return qs.filter(
                    pk=querying_attendee_id,
                    division__organization=current_user.organization,
                    is_removed=False,
                )
            else:
                if current_user.privileged:
                    init_query = Q(
                        division__organization=current_user.organization
                    ).add(  # preventing browser hacks since
                        Q(is_removed=False), Q.AND
                    )
                    final_query = init_query.add(
                        AttendeeService.filter_parser(filters_list, None, current_user),
                        Q.AND,
                    )
                    return qs.filter(final_query).order_by(
                        Case(
                            When(
                                id__in=target_attendee.related_ones.values_list(
                                    "id", flat=True
                                ),
                                then=0,
                            ),
                            default=1,
                        )
                    )  # https://stackoverflow.com/a/52047221/4257237
                else:
                    return qs
        else:
            return []

    @staticmethod
    def by_datagrid_params(
        current_user, meets, orderby_string, filters_list, include_dead
    ):
        """
        :param current_user:
        :param meets: attendee participated assembly ids. Exception: if assembly is in organization's
                      all_access_assemblies, all attendee of the same org will be return
        :param orderby_string:
        :param filters_list:
        :param include_dead:
        :return: the attendees the grid asked for, filtered and sorted. The page's attendingmeets,
                 folkcities and visitor_since columns are filled afterwards by attach_grid_columns().
        """
        if not hasattr(current_user, 'attendee'):
            return []
        visitor_meet_id = current_user.organization.infos.get("settings", {}).get("default_visitor_meet")
        now = datetime.now(timezone.utc)
        orderby_list, sorters = AttendeeService.orderby_parser(
            orderby_string, meets, current_user, visitor_meet_id=visitor_meet_id, now=now
        )
        init_query_q = {
            "division__organization": current_user.organization,
            "is_removed": False,
            "folks__category": Attendee.FAMILY_CATEGORY,
        }
        if not include_dead:
            init_query_q["deathday__isnull"] = True

        init_query = Q(
            **init_query_q
        )  # Todo: need filter on attending_meet finish_date

        final_query = init_query.add(
            AttendeeService.filter_parser(filters_list, meets, current_user), Q.AND
        )
        qs = (
            Attendee.objects
            if current_user.can_see_all_organizational_meets_attendees()
            else current_user.attendee.scheduling_attendees()
        )
        return qs.annotate(**sorters).filter(final_query).distinct().order_by(*orderby_list)

    @staticmethod
    def orderby_parser(orderby_string, meets, current_user, visitor_meet_id=None, now=None):
        """
        generates sorters based on user's choice
        :param orderby_string: JSON fetched from search params, will convert attendee.division to attendee__division
        :param meets: meet ids
        :param current_user:
        :param visitor_meet_id: the organization's visitor meet, which visitor_since sorts by
        :param now: when an enrollment counts as live
        :return: a list of sorters for order_by(), and the annotations they sort by: whether the
                 attendee is enrolled in a meet (the grid's dynamic meet columns), the first visit and
                 the first family city. Each is a portable subquery or aggregate; the columns the grid
                 shows for them are built in Python by attach_grid_columns().
        """
        now = now or datetime.now(timezone.utc)
        meet_slugs = set(
            Meet.objects.filter(
                id__in=meets, assembly__division__organization=current_user.organization
            ).values_list("slug", flat=True)
        )
        orderby_list = []
        sorters = {}
        for position, orderby_dict in enumerate(json.loads(orderby_string)):
            field = orderby_dict.get("selector", "id").replace(".", "__")
            direction = "-" if orderby_dict.get("desc", False) else ""
            if field in meet_slugs:
                sorter = f"in_meet_{position}"
                sorters[sorter] = Exists(
                    AttendingMeet.objects.filter(
                        attending__attendee=OuterRef("pk"),
                        meet__slug=field,
                        finish__gte=now,
                        is_removed=False,
                    )
                )
            elif field == "visitor_since":
                sorter = "visitor_since_at"
                sorters[sorter] = Min(
                    "attendings__attendingmeet__start",
                    filter=Q(
                        attendings__attendingmeet__meet=visitor_meet_id,
                        attendings__attendingmeet__is_removed=False,
                    ),
                )
            elif field == "folkcities":
                sorter = "folkcity"
                sorters[sorter] = Min(
                    "folks__places__address__locality__name",
                    filter=(Q(folks__places__finish__isnull=True) | Q(folks__places__finish__gte=now))
                    & Q(folks__places__is_removed=False),
                )
            else:
                sorter = field
            orderby_list.append(direction + sorter)
        return orderby_list, sorters

    @staticmethod
    def attach_grid_columns(attendees, current_user, now=None):
        """Fill the three columns the attendees grid shows beside an attendee's own, on each row of
        a page: ``attendingmeets``, the live enrollments; ``folkcities``, the cities of the folks'
        current addresses; ``visitor_since``, the dates of the first visits. Three queries for the
        page, whatever its size, in place of the Postgres aggregates that used to build them in SQL.
        """
        now = now or datetime.now(timezone.utc)
        visitor_meet_id = current_user.organization.infos.get("settings", {}).get("default_visitor_meet")
        visitor_meet_key = None if visitor_meet_id is None else str(visitor_meet_id)  # a meet's id may be 0
        attendees = list(attendees)
        ids = [attendee.pk for attendee in attendees]

        enrollments, visits = defaultdict(list), defaultdict(set)
        rows = (
            AttendingMeet.objects.filter(attending__attendee_id__in=ids, is_removed=False)
            .order_by("id")
            .values_list(
                "attending__attendee_id", "id", "meet__slug", "infos__note", "category_id", "finish", "start", "meet_id"
            )
        )
        for attendee_id, enrollment_id, slug, note, category_id, finish, start, meet_id in rows:
            if finish >= now:
                enrollments[attendee_id].append(
                    {
                        "attendingmeet_id": enrollment_id,
                        "meet_slug": slug,
                        "attendingmeet_note": note,
                        "attendingmeet_category": category_id,
                    }
                )
            if str(meet_id) == visitor_meet_key:
                visits[attendee_id].add(start.astimezone(timezone.utc).date().isoformat())

        # Every folk the attendee is or was a member of, as the join used to count them.
        folks_of = defaultdict(set)
        for attendee_id, folk_id in FolkAttendee.all_objects.filter(attendee_id__in=ids).values_list(
            "attendee_id", "folk_id"
        ):
            folks_of[attendee_id].add(folk_id)
        places = (
            Place.objects.filter(
                folk_id__in={folk_id for folk_ids in folks_of.values() for folk_id in folk_ids},
                is_removed=False,
            )
            .filter(Q(finish__isnull=True) | Q(finish__gte=localdate(now)))
            .select_related("address__locality")
        )
        cities = defaultdict(list)
        for place in places:
            address = place.address
            cities[place.folk_id].append(
                {
                    "locality__name": address.locality.name if address and address.locality_id else None,
                    "address__raw": address.raw if address else None,
                    "places__id": str(place.pk),
                }
            )

        for attendee in attendees:
            attendee.attendingmeets = enrollments[attendee.pk]
            attendee.folkcities = sorted(
                {row["places__id"]: row for folk_id in folks_of[attendee.pk] for row in cities[folk_id]}.values(),
                key=lambda row: (row["locality__name"] or "", row["address__raw"] or "", row["places__id"]),
            )
            attendee.visitor_since = ", ".join(sorted(visits[attendee.pk])) or None
        return attendees

    @staticmethod
    def attach_attendings(attendee):
        """Fill ``attendingmeets`` on one attendee for the attendee page: every attending of theirs,
        removed ones flagged, with the assembly it registered for and who registered."""
        attendings = (
            Attending.all_objects.filter(attendee=attendee)
            .select_related("registration__assembly", "registration__registrant")
            .order_by("id")
        )
        attendee.attendingmeets = [
            {
                "attending_id": attending.id,
                "attending_is_removed": attending.is_removed,
                "registration_assembly": (
                    attending.registration.assembly.display_name
                    if attending.registration_id and attending.registration.assembly_id
                    else None
                ),
                "registrant": (
                    attending.registration.registrant.full_name
                    if attending.registration_id and attending.registration.registrant_id
                    else ""
                ),
            }
            for attending in attendings
        ]
        return attendee

    @staticmethod
    def filter_parser(filters_list, meets, current_user):
        """
        A recursive method return Q function based on multi-level filter conditions. When filtering
        for attendingmeet, it adds extra filters on attendingmeet__finish gte conditions.
        :param filters_list: a string of multi-level list of filter conditions
        :param meets: optional meet ids
        :param current_user:
        :return: Q function, could be an empty Q()
        """
        and_string = Q.AND.lower()
        or_string = Q.OR.lower()

        if filters_list:
            if and_string in filters_list and or_string in filters_list:
                raise Exception(
                    "Can't process both 'or'/'and' at the same level! please wrap them in separated lists."
                )
            elif ('!' in filters_list and and_string in filters_list) or ('!' in filters_list and or_string in filters_list):
                raise Exception(
                    "Can't process 'or'/'and' with Unary filter(!) at the same level, please wrap them in separated lists."
                )
            elif '!' == filters_list[0]:   # currently only support one element for unary filter
                return ~AttendeeService.filter_parser(filters_list[1], meets, current_user)
            elif filters_list[1] == and_string:
                and_list = [
                    element for element in filters_list if element != and_string
                ]
                and_query = AttendeeService.filter_parser(
                    and_list[0], meets, current_user
                )
                for and_element in and_list[1:]:
                    and_query.add(
                        AttendeeService.filter_parser(and_element, meets, current_user),
                        Q.AND,
                    )
                return and_query
            elif filters_list[1] == or_string:
                or_list = [element for element in filters_list if element != or_string]
                or_query = AttendeeService.filter_parser(
                    or_list[0], meets, current_user
                )
                for or_element in or_list[1:]:
                    or_query.add(
                        AttendeeService.filter_parser(or_element, meets, current_user),
                        Q.OR,
                    )
                return or_query
            elif filters_list[0] == "visitor_since":
                return AttendeeService.visitor_since_filter(filters_list[2], current_user)
            elif filters_list[0] == "folkcities":
                return AttendeeService.folkcities_filter(filters_list[2])
            elif filters_list[1] == "=":
                condition = {
                    AttendeeService.field_convert(
                        filters_list[0], meets, current_user
                    ): filters_list[2],
                }
                if filters_list[0] == 'attendings__meets__slug' or (meets and Meet.objects.filter(id__in=meets, slug=filters_list[0], assembly__division__organization=current_user.organization).exists()):
                    condition['attendings__attendingmeet__finish__gte'] = datetime.now(timezone.utc)
                    condition['attendings__attendingmeet__is_removed'] = False

                return Q(**condition)
            elif filters_list[1] == "startswith":
                condition = {
                    AttendeeService.field_convert(
                        filters_list[0], meets, current_user
                    )
                    + "__istartswith": filters_list[2]
                }
                if meets and Meet.objects.filter(id__in=meets, slug=filters_list[0], assembly__division__organization=current_user.organization).exists():
                    condition['attendings__attendingmeet__finish__gte'] = datetime.now(timezone.utc)
                return Q(**condition)
            elif filters_list[1] == "endswith":
                condition = {
                    AttendeeService.field_convert(
                        filters_list[0], meets, current_user
                    )
                    + "__iendswith": filters_list[2]
                }
                if meets and Meet.objects.filter(id__in=meets, slug=filters_list[0], assembly__division__organization=current_user.organization).exists():
                    condition['attendings__attendingmeet__finish__gte'] = datetime.now(timezone.utc)
                return Q(**condition)
            elif filters_list[1] == "contains":
                condition = {
                    AttendeeService.field_convert(
                        filters_list[0], meets, current_user
                    )
                    + "__icontains": filters_list[2]
                }
                if meets and Meet.objects.filter(id__in=meets, slug=filters_list[0], assembly__division__organization=current_user.organization).exists():
                    condition['attendings__attendingmeet__finish__gte'] = datetime.now(timezone.utc)
                return Q(**condition)
            elif filters_list[1] == "notcontains":
                return ~Q(
                    **{
                        AttendeeService.field_convert(
                            filters_list[0], meets, current_user
                        )
                        + "__icontains": filters_list[2]
                    }
                )
            elif filters_list[1] == "<>":
                return ~Q(
                    **{
                        AttendeeService.field_convert(
                            filters_list[0], meets, current_user
                        ): filters_list[2]
                    }
                )
        return Q()

    @staticmethod
    def visitor_since_filter(term, current_user):
        """The grid's visitor_since column, searched: a date or the start of one (2025, 2025-03,
        2025-03-02) matched against the dates of the visits. The column is built in Python, so the
        search box's term for it is answered by the enrollments it is built from. Anything that is
        not a date matches nobody, as a date column should."""
        parts = str(term).strip().split("-")
        try:
            numbers = [int(part) for part in parts]
        except ValueError:
            return Q(pk__in=[])
        if not 1 <= len(numbers) <= 3:
            return Q(pk__in=[])
        condition = {
            "attendings__attendingmeet__meet": current_user.organization.infos.get("settings", {}).get("default_visitor_meet"),
            "attendings__attendingmeet__is_removed": False,
        }
        for name, value in zip(("year", "month", "day"), numbers):
            condition[f"attendings__attendingmeet__start__{name}"] = value
        return Q(**condition)

    @staticmethod
    def folkcities_filter(term):
        """The grid's folkcities column, searched: the attendees whose folks have a current address
        in a city containing the term."""
        term = str(term).strip()
        if not term:
            return Q()
        today = localdate(datetime.now(timezone.utc))
        return Q(
            folks__places__address__locality__name__icontains=term,
            folks__places__is_removed=False,
        ) & (Q(folks__places__finish__isnull=True) | Q(folks__places__finish__gte=today))

    @staticmethod
    def field_convert(query_field, meets, current_user):
        """
        some of the values are calculated cell values, and need to convert back to db field for search
        :return: string of fields in database
        """
        # The name and contact columns show what the search column is built from, so a search or a
        # sort on them goes to search_text: one lowercased text column that every backend compares
        # the same way, where a match inside the JSON would miss Han names stored with ASCII escapes.
        field_converter = {
            "infos.names": "search_text",
            "infos.contacts": "search_text",
            "self_phone_numbers": "search_text",
            "self_email_addresses": "search_text",
        }
        if meets:
            for meet in Meet.objects.filter(
                id__in=meets, assembly__division__organization=current_user.organization,
            ):
                field_converter[meet.slug] = "attendings__meets__display_name"

        return field_converter.get(query_field, query_field).replace(".", "__")

    @staticmethod
    def add_past(attendee, past_category_id, user_time_zone):
        category = Category.objects.get(pk=past_category_id)
        Past.objects.update_or_create(  # past does not have uniq key by natural
            organization=attendee.division.organization,
            content_type=ContentType.objects.get_for_model(attendee),
            object_id=attendee.id,
            category=category,
            when=PartialDate(datetime.now(user_time_zone).strftime('%Y-%m-%d')),
            display_name=f'become {category.display_name}',
            infos=Utility.relationship_infos(),
        )

    @staticmethod
    def end_all_activities(attendee, updating_attendee_uuid_str):
        """FamilyAttendee is not deleted since many people still memorise their passed away families"""
        for attending in attendee.attendings.all():
            AttendingService.end_all_activities(attending)

        now = datetime.now(timezone.utc)
        attendee.pasts.filter(Q(finish__isnull=True) | Q(finish__gte=now)).update(
            finish=now
        )
        attendee.places.filter(Q(finish__isnull=True) | Q(finish__gte=now)).update(
            finish=now
        )

        for family in attendee.families.filter(is_removed=False):
            if (
                family.folkattendee_set.filter(
                    (Q(finish__isnull=True) | Q(finish__gte=now)),
                    attendee__deathday__isnull=True,
                    is_removed=False,
                    attendee__is_removed=False,
                ).count()
                < 1
            ):  # single household family (after attendee's deathday updated)
                family.places.filter(
                    Q(finish__isnull=True) | Q(finish__gte=now)
                ).update(finish=now)

        # The dead schedule for nobody and are called about nobody: the links
        # that name them go, and the people they were linked to are marked updated.
        for links in (
            AttendeeScheduler.objects.filter(scheduler=attendee),
            AttendeeEmergencyContact.objects.filter(contact=attendee),
        ):
            for linked in Attendee.objects.filter(pk__in=links.values("attendee_id")):
                linked.infos['updating_attendees'][updating_attendee_uuid_str] = Utility.now_with_timezone().isoformat(timespec='minutes')
                linked.save()
            links.delete()

        attendee_user = attendee.user
        if attendee_user:
            attendee_user.is_active = False
            attendee_user.save()

    @staticmethod
    def destroy_with_associations(attendee):
        for attending in attendee.attendings.filter(is_removed=False):
            AttendingService.destroy_with_associations(attending)

        attendee.pasts.filter(is_removed=False).delete()

        # Relationship.objects.filter(
        #     (Q(from_attendee=attendee)
        #      |
        #      Q(to_attendee=attendee)),
        #     is_removed=False,
        # ).delete()

        for place in attendee.places.filter(is_removed=False):
            PlaceService.destroy_with_associations(place)

        for family in attendee.folks.filter(is_removed=False):
            FolkService.destroy_with_associations(family, attendee)

        for registration in Registration.objects.filter(
            registrant=attendee, is_removed=False
        ):
            registration.registrant = None
            if not registration.attending_set.filter(is_removed=False):
                registration.delete()
            else:
                registration.save()

        old_photo = attendee.photo
        if (
            old_photo
        ):  # Todo 20211102: may need to search photos of attendee name due to repeating import
            old_file = Path(old_photo.path)
            old_file.unlink(missing_ok=True)

        attendee_user = attendee.user
        if attendee_user:
            attendee.delete()
            attendee_user.delete()
        else:
            attendee.delete()
        # Todo 20211102: CCPA deletion requires history removal too

    @staticmethod
    def create_or_update_first_folk(attendee, folk_name, category_id, role_id, print_directory=False):
        potential_non_family_folk = attendee.folks.filter(category=category_id).first()
        folk, folk_created = Folk.objects.update_or_create(
            id=potential_non_family_folk.id if potential_non_family_folk else None,
            defaults={
                "division": attendee.division,
                "category": Category.objects.get(pk=category_id),
                "display_name": folk_name,
                "infos": {"print_directory": print_directory},
            },
        )
        FolkAttendee.objects.update_or_create(
            folk=folk,
            attendee=attendee,
            defaults={
                "folk": folk,
                "attendee": attendee,
                "role": Relation.objects.get(pk=role_id),
            },
        )
        return folk
