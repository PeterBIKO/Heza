from django.shortcuts import render


def error_403(request, exception=None):
    return render(request, "errors/403.html", {"message": str(exception) if exception else ""}, status=403)


def error_404(request, exception=None):
    return render(request, "errors/404.html", status=404)


def error_500(request):
    from django.http import HttpResponseServerError
    from django.template import loader

    return HttpResponseServerError(loader.get_template("errors/500.html").render())
