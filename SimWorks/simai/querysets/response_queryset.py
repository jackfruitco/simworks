from django.db import models
from django.utils.timezone import now
from simai.analytics.response_analytics import ResponseAnalytics


class ResponseQuerySet(models.QuerySet):
    def analytics(self):
        return ResponseAnalytics(self)

    def this_month(self):
        today = now()
        return self.filter(created__year=today.year, created__month=today.month)

    def this_year(self):
        today = now()
        return self.filter(created__year=today.year)

    def today(self):
        today = now().date()
        return self.filter(created__date=today)

    def monthly(self):
        return self.analytics().by_month().by_user().tally()

    def yearly(self):
        return self.analytics().by_month().by_user().tally()

    def all_time(self):
        return self.analytics().by_user().tally()