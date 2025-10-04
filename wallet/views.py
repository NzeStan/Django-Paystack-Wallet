from django.views.generic import TemplateView

class SuccessPageView(TemplateView):

    template_name = "success.html"