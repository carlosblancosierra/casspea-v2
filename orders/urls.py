from django.urls import path
from . import views
from mails import views as mails_views

app_name = 'orders'

urlpatterns = [
    path('', views.OrderListView.as_view(), name='order-list'),
    path('send-tracking-code-mail/', mails_views.OrderShippingEmailView.as_view(), name='send-tracking-code-mail'),
    path('csv/', views.export_product_sales_csv, name='export-product-sales-csv'),
    path('flavours-sold/', views.FlavoursSoldView.as_view(), name='flavours-sold'),
    path('flavours-sold/csv/', views.FlavoursSoldCSVView.as_view(), name='flavours-sold-csv'),
    path('chocolates-sold/', views.MonthlyChocolateCountView.as_view(), name='monthly-chocolate-count'),
    path('customer/lookup/', views.CustomerOrderRetrieveView.as_view(), name='customer-order-lookup'),
    path('customer/update-shipping-date/', views.CustomerOrderShippingDateUpdateView.as_view(),
         name='customer-update-shipping-date'),
    path('total-units-sold/', views.TotalUnitsSoldView.as_view(), name='total-units-sold'),
    path('daily-units-sold/', views.DailyUnitsSoldView.as_view(), name='daily-units-sold'),
    path('<str:order_id>/', views.OrderDetailView.as_view(), name='order-detail'),
]
