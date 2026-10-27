"""
Seeds a handful of varied sample Events, Venues and Attendee registrations
so the Events page (card grid, Attendees tab, Venues tab and Analytics
charts) has enough different data to see real variety.

Safe to re-run: every object is created with get_or_create on a unique
title/name, so running it twice won't create duplicates.

Usage:
    python manage.py seed_demo_events
"""
import itertools
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from feed.models import Attendee, Event, Venue

User = get_user_model()


class Command(BaseCommand):
    help = "Seed sample events, venues and attendee registrations for the Events page."

    def handle(self, *args, **options):
        users = list(User.objects.order_by("id")[:10])
        if not users:
            self.stderr.write(self.style.ERROR(
                "No users found. Create at least one account (e.g. sign up or "
                "createsuperuser) before running this command."
            ))
            return

        # Cycle through whichever users exist so events/venues have varied
        # organizers when there's more than one account, and still work
        # fine with just a single account.
        user_cycle = itertools.cycle(users)
        today = timezone.now().date()

        events_data = [
            dict(
                title="AI & Machine Learning Summit",
                category="conference",
                location="Main Auditorium",
                days_from_now=5, time="09:00",
                capacity=150, price=2500,
                description="A day of talks on applied AI, machine learning research, and industry case studies from guest speakers.",
            ),
            dict(
                title="Intro to Web Development Workshop",
                category="workshop",
                location="CS Lab 2",
                days_from_now=2, time="14:00",
                capacity=40, price=0,
                description="Hands-on workshop covering HTML, CSS and JavaScript basics — bring your laptop.",
            ),
            dict(
                title="Campus Live: End of Semester Concert",
                category="concert",
                location="Open Field",
                days_from_now=14, time="18:00",
                capacity=500, price=1000,
                description="Live performances from student bands and guest artists to close out the semester.",
            ),
            dict(
                title="Inter-Faculty Football Championship",
                category="sports",
                location="Sports Complex",
                days_from_now=9, time="16:00",
                capacity=None, price=0,
                description="Faculties compete for the inter-faculty football trophy. Come support your team!",
            ),
            dict(
                title="Final Year Projects Exhibition",
                category="exhibition",
                location="Engineering Hall",
                days_from_now=21, time="10:00",
                capacity=300, price=0,
                description="Final year students across departments showcase their projects to faculty and visitors.",
            ),
            dict(
                title="Tech Careers Networking Night",
                category="networking",
                location="Student Center",
                days_from_now=7, time="17:30",
                capacity=100, price=500,
                description="Meet recruiters and alumni working in tech, and get tips on internships and job hunting.",
            ),
            dict(
                title="Cultural Day Festival",
                category="festival",
                location="Main Quad",
                days_from_now=30, time="11:00",
                capacity=None, price=0,
                description="A celebration of the different cultures on campus, with food, music and performances.",
            ),
            dict(
                title="Chess & Board Games Night",
                category="other",
                location="Common Room, Block B",
                days_from_now=3, time="19:00",
                capacity=30, price=0,
                description="Casual chess and board games night — all skill levels welcome.",
            ),
        ]

        created_events = []
        for data in events_data:
            organizer = next(user_cycle)
            event, created = Event.objects.get_or_create(
                title=data["title"],
                defaults=dict(
                    category=data["category"],
                    location=data["location"],
                    date=today + timedelta(days=data["days_from_now"]),
                    time=data["time"],
                    capacity=data["capacity"],
                    price=data["price"],
                    description=data["description"],
                    organizer=organizer,
                ),
            )
            created_events.append(event)
            self.stdout.write(
                (self.style.SUCCESS("  + created") if created else self.style.WARNING("  = exists"))
                + f"  {event.title}"
            )

        venues_data = [
            dict(name="Main Auditorium", address="Senate Building, Ground Floor", venue_type="indoor", capacity=600),
            dict(name="Open Field", address="Behind the Sports Complex", venue_type="outdoor", capacity=1000),
            dict(name="Student Center Hall", address="Student Center, 2nd Floor", venue_type="indoor", capacity=250),
            dict(name="Virtual Meeting Room", address="Online — link shared after registration", venue_type="virtual", capacity=None),
        ]
        for data in venues_data:
            creator = next(user_cycle)
            venue, created = Venue.objects.get_or_create(
                name=data["name"],
                defaults=dict(
                    address=data["address"],
                    venue_type=data["venue_type"],
                    capacity=data["capacity"],
                    created_by=creator,
                ),
            )
            self.stdout.write(
                (self.style.SUCCESS("  + created") if created else self.style.WARNING("  = exists"))
                + f"  {venue.name}"
            )

        # A few attendee registrations, spread across users and roles, so
        # the Attendees tab and the Analytics charts show real variety.
        attendee_types = ["attendee", "speaker", "vip"]
        reg_count = 0
        for event, attendee_type in zip(created_events, itertools.cycle(attendee_types)):
            for user in itertools.islice(itertools.cycle(users), len(users) if len(users) <= 3 else 3):
                if event.capacity is not None and event.attendees.count() >= event.capacity:
                    break
                _, created = Attendee.objects.get_or_create(
                    event=event, user=user,
                    defaults={"attendee_type": attendee_type},
                )
                if created:
                    reg_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. {len(created_events)} events and {len(venues_data)} venues ready, "
            f"{reg_count} new attendee registrations added."
        ))
