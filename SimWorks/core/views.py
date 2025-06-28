from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import TemplateView
from graphene_django.views import GraphQLView


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


class PrivateGraphQLView(GraphQLView):
    @method_decorator(csrf_exempt)
    def dispatch(self, request, *args, **kwargs):
        user = request.user

        if not user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login

            return redirect_to_login(request.get_full_path())

        if not (user.is_staff or user.has_perm("core.read_api")):
            raise PermissionDenied(
                "You do not have permission to access the GraphQL API."
            )

        return super().dispatch(request, *args, **kwargs)


class RobotsView(TemplateView):
    template_name = "robots.txt"
