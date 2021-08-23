from django.shortcuts import render
from django import http
from alipay import AliPay
import os
from django.conf import settings

from meiduo_mall.utils.views import LoginRequiredView
from orders.models import OrderInfo
from meiduo_mall.utils.response_code import RETCODE
from .models import Payment

# 支付宝
# ALIPAY_APPID = '2016091900551154'
# ALIPAY_DEBUG = True  # 表示是沙箱环境还是真实支付环境
# ALIPAY_URL = 'https://openapi.alipaydev.com/gateway.do'
# ALIPAY_RETURN_URL = 'http://www.meiduo.site:8000/payment/status/'



class PaymentURLView(LoginRequiredView):
    """生成支付宝支付url"""
    def get(self, request, order_id):

        user = request.user
        # 校验
        try:
            order = OrderInfo.objects.get(order_id=order_id,
                                          user=user,
                                          status=OrderInfo.ORDER_STATUS_ENUM['UNPAID'])
        except OrderInfo.DoesNotExist:
            return http.HttpResponseForbidden('订单有误')

        # 创建支付宝SDK对象
        alipay = AliPay(
            appid=settings.ALIPAY_APPID,
            app_notify_url=None,  # 默认回调url
            # /Users/chao/Desktop/meiduo_30/meiduo_mall/meiduo_mall/apps/payment/views.py
            # /Users/chao/Desktop/meiduo_30/meiduo_mall/meiduo_mall/apps/payment/keys/app_private_key.pem
            app_private_key_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'keys/app_private_key.pem'),
            # 支付宝的公钥，验证支付宝回传消息使用，不是你自己的公钥,
            alipay_public_key_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'keys/alipay_public_key.pem'),
            sign_type="RSA2",  # RSA 或者 RSA2
            debug=settings.ALIPAY_DEBUG  # 默认False
        )

        # # 电脑网站支付，需要跳转到https://openapi.alipay.com/gateway.do? + order_string
        order_string = alipay.api_alipay_trade_page_pay(
            out_trade_no=order_id,  # 美多订单编号
            total_amount=str(order.total_amount),   # 支付总金额:注意将Decimal转成字符串
            subject='美多商城:%s' % order_id,  # 标题
            return_url=settings.ALIPAY_RETURN_URL,  # 支付成功后重定向的url
        )

        # 拼接支付宝支付url
        # 真实支付环境: https://openapi.alipay.com/gateway.do? + order_string
        # 沙箱支付环境: https://openapi.alipaydev.com/gateway.do? + order_string
        alipay_url = settings.ALIPAY_URL + '?' + order_string
        # 响应
        return http.JsonResponse({'code': RETCODE.OK, 'errmsg': 'OK', 'alipay_url': alipay_url})


class PaymentStatusView(LoginRequiredView):
    """校验及保存支付结果"""

    def get(self, request):

        # 接收
        query_dict = request.GET
        # 将QueryDict类型转换成dict
        data = query_dict.dict()

        # 提取出sign加密数据
        sign = data.pop('sign')

        # 创建alipay SDK对象
        alipay = AliPay(
            appid=settings.ALIPAY_APPID,  # 开放平台应用id
            app_notify_url=None,  # 默认回调url
            app_private_key_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'keys/app_private_key.pem'),
            # 支付宝的公钥，验证支付宝回传消息使用，不是你自己的公钥,
            alipay_public_key_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'keys/alipay_public_key.pem'),
            sign_type="RSA2",  # RSA 或者 RSA2
            debug=settings.ALIPAY_DEBUG  # 默认False
        )
        # 调用它的verify方法进行校验支付结果
        if alipay.verify(data, sign):
            # 获取美多订单编号
            order_id = data.get('out_trade_no')
            # 获取支付宝交易号
            trade_id = data.get('trade_no')
            try:
                # 来保存支付结果前,先查询是否保存过,没保存过再去保存及修改订单状态
                Payment.objects.get(order_id=order_id, trade_id=trade_id)
            except Payment.DoesNotExist:
                # 保存支付结果
                payment = Payment.objects.create(
                    order_id=order_id,  # 美多订单编号
                    trade_id=trade_id  # 支付宝交易号
                )
                # 修改订单状态
                OrderInfo.objects.filter(order_id=order_id,
                                         user=request.user,
                                         status=OrderInfo.ORDER_STATUS_ENUM['UNPAID']).update(status=OrderInfo.ORDER_STATUS_ENUM['UNCOMMENT'])

        else:
            return http.HttpResponseBadRequest('支付失败')
        # 响应
        return render(request, 'pay_success.html', {'trade_id': trade_id})