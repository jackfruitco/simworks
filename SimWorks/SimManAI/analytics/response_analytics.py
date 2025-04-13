from django.db.models import Sum, F
from django.db.models.functions import TruncMonth, TruncDay
from django.utils.dateparse import parse_datetime, parse_date
import csv
from io import StringIO

class ResponseAnalytics:
    def __init__(self, queryset):
        self.queryset = queryset
        self.grouping = []

    def _parse_date(self, value):
        if isinstance(value, str):
            return parse_datetime(value) or parse_date(value)
        return value

    def from_date(self, dt):
        parsed = self._parse_date(dt)
        if parsed:
            self.queryset = self.queryset.filter(created__gte=parsed)
        return self

    def to_date(self, dt):
        parsed = self._parse_date(dt)
        if parsed:
            self.queryset = self.queryset.filter(created__lte=parsed)
        return self

    def range(self, start, end):
        return self.from_date(start).to_date(end)

    def by_month(self):
        self.queryset = self.queryset.annotate(month=TruncMonth("created"))
        if "month" not in self.grouping:
            self.grouping.append("month")
        return self

    def by_day(self):
        self.queryset = self.queryset.annotate(day=TruncDay("created"))
        if "day" not in self.grouping:
            self.grouping.append("day")
        return self

    def by_user(self):
        if "user" not in self.grouping:
            self.grouping.append("user")
        return self

    def by_simulation(self):
        if "simulation" not in self.grouping:
            self.grouping.append("simulation")
        return self

    def tally(self):
        return (
            self.queryset
            .values(*self.grouping)
            .annotate(
                input=Sum("input_tokens"),
                output=Sum("output_tokens"),
                reasoning=Sum("reasoning_tokens"),
            )
            .annotate(
                total=F("input") + F("output") + F("reasoning")
            )
            .order_by(*self.grouping)
        )

    def summary(self):
        return self.queryset.aggregate(
            input=Sum("input_tokens"),
            output=Sum("output_tokens"),
            reasoning=Sum("reasoning_tokens"),
            total=Sum(F("input_tokens") + F("output_tokens") + F("reasoning_tokens"))
        )

    def as_list(self):
        return list(self.tally())

    def as_csv(self):
        rows = self.as_list()
        if not rows:
            return ""

        headers = rows[0].keys()
        buffer = StringIO()
        writer = csv.DictWriter(buffer, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        return buffer.getvalue()