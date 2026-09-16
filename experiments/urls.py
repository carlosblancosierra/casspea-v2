from django.urls import path

from .views import AssignVariantView, ExperimentResultsView, RecordEventView

urlpatterns = [
    path('assign/', AssignVariantView.as_view(), name='experiment-assign'),
    path('event/', RecordEventView.as_view(), name='experiment-event'),
    path('<slug:key>/results/', ExperimentResultsView.as_view(), name='experiment-results'),
]
