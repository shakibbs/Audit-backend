from django.urls import path

from .api import PeriodReportView, ReportFileView, ReportsView

urlpatterns = [path('reports', ReportsView.as_view()), path('reports/period', PeriodReportView.as_view()),
               path('reports/<str:ref>/file', ReportFileView.as_view())]
