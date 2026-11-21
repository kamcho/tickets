from django.urls import path

from billing import views
from billing import views_network

urlpatterns = [
    path('billing/payments/', views.payment_list_view, name='billing_payment_list'),
    path('billing/payments/stk/', views.stk_push_view, name='billing_stk_push'),
    path(
        'billing/payments/pull/',
        views.pull_transaction_view,
        name='billing_pull_transaction',
    ),
    path(
        'billing/payments/manual/',
        views.manual_payment_view,
        name='billing_manual_payment',
    ),
    path(
        'billing/payments/<str:payment_id>/',
        views.payment_detail_view,
        name='billing_payment_detail',
    ),
    path('billing/expenses/', views.expenditure_list_view, name='billing_expenditure_list'),
    path('billing/expenses/new/', views.expenditure_create_view, name='billing_expenditure_create'),
    path('billing/plans/', views.plan_list_view, name='billing_plan_list'),
    path('billing/plans/new/', views.plan_create_view, name='billing_plan_create'),
    path('billing/plans/<int:pk>/edit/', views.plan_edit_view, name='billing_plan_edit'),
    path('billing/invoices/', views.invoice_list_view, name='billing_invoice_list'),
    path(
        'billing/invoices/<str:invoice_id>/',
        views.invoice_detail_view,
        name='billing_invoice_detail',
    ),
    path(
        'billing/customers/<int:customer_id>/subscribe/',
        views.customer_subscribe_view,
        name='billing_customer_subscribe',
    ),
    # Public Safaricom callbacks (no auth / CSRF)
    path(
        'api/mpesa/stk/callback/',
        views.mpesa_stk_callback,
        name='billing_mpesa_stk_callback',
    ),
    path(
        'api/mpesa/transaction/result/',
        views.mpesa_transaction_result,
        name='billing_mpesa_transaction_result',
    ),
    path(
        'api/mpesa/transaction/timeout/',
        views.mpesa_transaction_timeout,
        name='billing_mpesa_transaction_timeout',
    ),
    # Phase 4 network / MikroTik (staff session)
    path(
        'api/network/health/',
        views_network.network_health,
        name='billing_network_health',
    ),
    path(
        'api/network/routers/',
        views_network.network_router_list,
        name='billing_network_router_list',
    ),
    path(
        'api/network/accounts/',
        views_network.network_account_create,
        name='billing_network_account_create',
    ),
    path(
        'api/network/accounts/<int:pk>/suspend/',
        views_network.network_account_suspend,
        name='billing_network_account_suspend',
    ),
    path(
        'api/network/accounts/<int:pk>/restore/',
        views_network.network_account_restore,
        name='billing_network_account_restore',
    ),
    path(
        'api/network/accounts/<int:pk>/kick/',
        views_network.network_account_kick,
        name='billing_network_account_kick',
    ),
    path(
        'api/network/accounts/<int:pk>/status/',
        views_network.network_account_status,
        name='billing_network_account_status',
    ),
    path(
        'api/network/customers/<int:customer_id>/account/',
        views_network.network_account_ensure_for_customer,
        name='billing_network_customer_account',
    ),
]
