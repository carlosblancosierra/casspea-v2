from django.urls import path

from .admin_views import ClientSetupAdminView
from .views import ClientPageDetailView, ClientPageUnlockView

urlpatterns = [
    # Before <slug>/ so 'admin' is never read as a page slug.
    path('admin/setups/', ClientSetupAdminView.as_view(), name='client-setup-admin'),
    path('<slug:slug>/', ClientPageDetailView.as_view(), name='client-page-detail'),
    path('<slug:slug>/unlock/', ClientPageUnlockView.as_view(), name='client-page-unlock'),
]
