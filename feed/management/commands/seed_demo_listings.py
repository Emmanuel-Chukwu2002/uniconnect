"""
Seeds a handful of varied sample Marketplace listings, spread across
whichever users exist, so the Browse grid has enough variety to actually
look like a marketplace instead of one or two test items.

Safe to re-run: every listing is created with get_or_create on a unique
title, so running it twice won't create duplicates.

Usage:
    python manage.py seed_demo_listings
"""
import itertools

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from feed.models import Listing

User = get_user_model()


class Command(BaseCommand):
    help = "Seed sample marketplace listings for the Marketplace page."

    def handle(self, *args, **options):
        users = list(User.objects.order_by("id")[:10])
        if not users:
            self.stderr.write(self.style.ERROR(
                "No users found. Create at least one account (e.g. sign up or "
                "createsuperuser) before running this command."
            ))
            return

        user_cycle = itertools.cycle(users)

        listings_data = [
            dict(
                title="Calculus: Early Transcendentals (8th Ed.)",
                category="textbooks", condition="good", price=4500, quantity_available=1,
                location="Hostel Block C, Room 12",
                description="Standard 200-level calculus textbook. Some highlighting in chapters 1-3, otherwise clean. No missing pages.",
            ),
            dict(
                title="HP EliteBook Laptop (Core i5, 8GB RAM)",
                category="electronics", condition="good", price=185000, quantity_available=1,
                location="Faculty of Engineering",
                description="Reliable laptop for coding and coursework. Battery holds about 3 hours. Comes with charger, no bag.",
            ),
            dict(
                title="Reading Lamp with USB Port",
                category="furniture", condition="like_new", price=6500, quantity_available=3,
                location="Hostel Block A",
                description="Used for one semester. Adjustable neck, built-in USB charging port, warm and cool light modes.",
            ),
            dict(
                title="Department Hoodie (Computer Science, Size L)",
                category="clothing", condition="new", price=8000, quantity_available=5,
                location="Student Center",
                description="Brand new, still in the pack. Ordered an extra size by mistake.",
            ),
            dict(
                title="Electric Kettle (1.5L)",
                category="appliances", condition="good", price=7000, quantity_available=2,
                location="Hostel Block C",
                description="Boils water fast, auto shut-off works fine. Slight scuff on the base, doesn't affect use.",
            ),
            dict(
                title="Badminton Racket Set (2 rackets + shuttlecocks)",
                category="sports", condition="like_new", price=9500, quantity_available=1,
                location="Sports Complex",
                description="Used a handful of times. Both rackets included, strings still tight.",
            ),
            dict(
                title="End of Semester Concert Ticket (VIP)",
                category="tickets", condition="new", price=3000, quantity_available=2,
                location="Meet at Main Gate",
                description="Can't attend anymore — selling at face value. VIP section, transferable.",
            ),
            dict(
                title="Scientific Calculator (Casio fx-991ES)",
                category="electronics", condition="fair", price=3500, quantity_available=1,
                location="Faculty of Science",
                description="Works perfectly, all functions tested. Casing is a bit worn from daily use over two sessions.",
            ),
            dict(
                title="Mini Fridge (Table-top, 45L)",
                category="appliances", condition="good", price=45000, quantity_available=1,
                location="Hostel Block B",
                description="Keeps drinks and snacks cold, quiet motor. Selling because I'm moving off-campus.",
            ),
            dict(
                title="Data Structures & Algorithms Notes (Printed)",
                category="textbooks", condition="good", price=1500, quantity_available=4,
                location="CS Department",
                description="Printed and spiral-bound lecture notes covering the full 300-level DSA syllabus. Clear diagrams.",
            ),
            dict(
                title="Desk Organizer Set",
                category="other", condition="new", price=4000, quantity_available=6,
                location="Student Center",
                description="3-piece desk organizer — pen holder, tray, and sticky note dispenser. Unused, bought extra.",
            ),
            dict(
                title="Wireless Earbuds (Bluetooth 5.0)",
                category="electronics", condition="like_new", price=12000, quantity_available=2,
                location="Hostel Block A",
                description="Barely used, comes with charging case and extra ear tips. Great sound, no issues.",
            ),
        ]

        created_count = 0
        for data in listings_data:
            seller = next(user_cycle)
            listing, created = Listing.objects.get_or_create(
                title=data["title"],
                defaults=dict(
                    seller=seller,
                    category=data["category"],
                    condition=data["condition"],
                    price=data["price"],
                    quantity_available=data["quantity_available"],
                    location=data["location"],
                    description=data["description"],
                ),
            )
            if created:
                created_count += 1
            self.stdout.write(
                (self.style.SUCCESS("  + created") if created else self.style.WARNING("  = exists"))
                + f"  {listing.title}"
            )

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. {created_count} new listings created ({len(listings_data)} total in the seed set)."
        ))
