from django.conf.urls import url
from . import views

urlpatterns = [
    # 去结算
    url(r'^orders/settlement/$', views.OrderSettlementView.as_view()),
    # 提交订单
    url(r'^orders/commit/$', views.OrderCommitView.as_view()),
    # 订单成功
    url(r'^orders/success/$', views.OrderSuccessView.as_view()),

    url('^orders/info/(?P<page_num>\d+)/$', views.InfoView.as_view()),

    url('^orders/comment/$', views.CommentView.as_view()),
    # 查看商品评论
    url('^comment/(?P<sku_id>\d+)/$', views.CommentSKUView.as_view()),

]
