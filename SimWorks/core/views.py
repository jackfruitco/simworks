from django.shortcuts import render
from django.views.generic import TemplateView


def index(request):
    # Number of visits to this view, as counted in the session variable.
    num_visits = request.session.get("num_visits", 0)
    num_visits += 1
    request.session["num_visits"] = num_visits

    return render(
        request,
        "core/index.html",
        # {"products": products},
    )


class RobotsView(TemplateView):
    template_name = "robots.txt"
