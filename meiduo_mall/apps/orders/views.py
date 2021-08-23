from django.shortcuts import render
from django_redis import get_redis_connection
from decimal import Decimal
import json
from django import http
from django.utils import timezone
from django.db import transaction

from meiduo_mall.utils.views import LoginRequiredView
from users.models import Address
from goods.models import SKU
from .models import OrderInfo, OrderGoods
from meiduo_mall.utils.response_code import RETCODE
import logging

logger = logging.getLogger('django')


class OrderSettlementView(LoginRequiredView):
    """去结算界面"""

    def get(self, request):

        user = request.user
        # 获取当前登录用户的所有收货地址
        address_qs = Address.objects.filter(user=user, is_deleted=False)

        # 创建redis连接对象
        redis_conn = get_redis_connection('carts')
        # 获取hash和set
        redis_carts = redis_conn.hgetall('cart_%s' % user.id)
        selected_ids = redis_conn.smembers('selected_%s' % user.id)
        # 定义一个新字典用来包装要勾选商品的id和count
        cart_dict = {}
        # 遍历set集合只留下勾选商品的id和count
        for sku_id_bytes in selected_ids:
            cart_dict[int(sku_id_bytes)] = int(redis_carts[sku_id_bytes])

        # 将勾选的商品对应的sku模型全部查出来
        sku_qs = SKU.objects.filter(id__in=cart_dict.keys())
        total_count = 0  # 商品总数量
        total_amount = Decimal('0.00')
        for sku in sku_qs:
            sku.count = cart_dict[sku.id]
            sku.amount = sku.price * sku.count
            total_count += sku.count  # 累加商品总数量
            total_amount += sku.amount  # 累加商品总金额

        freight = Decimal('10.00')  # 运费
        context = {
            "addresses": address_qs,  # 当前登录用户的所有收货地址
            'skus': sku_qs,  # 购物车中勾选的所有商品数据
            'total_count': total_count,  # 要购买的商品总数量
            'total_amount': total_amount,  # 商品总金额
            'freight': freight,  # 运费
            'payment_amount': total_amount + freight,  # 实付款
        }
        return render(request, 'place_order.html', context)


class OrderCommitView(LoginRequiredView):
    """提交订单"""

    def post(self, request):

        # 1.接收请求体数据
        json_dict = json.loads(request.body.decode())
        address_id = json_dict.get('address_id')
        pay_method = json_dict.get('pay_method')

        # 2. 校验
        if all([address_id, pay_method]) is False:
            return http.HttpResponseForbidden('缺少必传参数')
        user = request.user
        try:
            address = Address.objects.get(id=address_id, user=user, is_deleted=False)
        except Address.DoesNotExist:
            return http.HttpResponseForbidden('address_id有误')
        # if not (pay_method == '1' or pay_method =='2'):
        try:
            pay_method = int(pay_method)
            if pay_method not in [OrderInfo.PAY_METHODS_ENUM['CASH'], OrderInfo.PAY_METHODS_ENUM['ALIPAY']]:
                return http.HttpResponseForbidden('支付方式有误')
        except Exception as e:
            logger.error(e)
            return http.HttpResponseForbidden('支付方式有误')

        # 生成订单编号  201909151033130000000000001
        order_id = timezone.now().strftime('%Y%m%d%H%M%S') + '%09d' % user.id

        # 订单状态  如果中货到付款订单状态为 待发货, 如果是支付宝支付就是待支付
        status = (OrderInfo.ORDER_STATUS_ENUM['UNPAID']
                  if pay_method == OrderInfo.PAY_METHODS_ENUM['ALIPAY']
                  else OrderInfo.ORDER_STATUS_ENUM['UNSEND'])

        # 手动开启一个事务
        with transaction.atomic():

            # 创建事务保存点
            save_point = transaction.savepoint()
            try:

                # 3.新增订单基本信息记录
                order = OrderInfo.objects.create(
                    order_id=order_id,
                    user=user,
                    address=address,
                    total_count=0,
                    total_amount=Decimal('0.00'),
                    freight=Decimal('10.00'),
                    pay_method=pay_method,
                    status=status
                )

                # 获取redis中购物车数据
                # 创建redis连接对象
                redis_conn = get_redis_connection('carts')
                # 获取hash和set数据
                redis_carts = redis_conn.hgetall('cart_%s' % user.id)
                selected_ids = redis_conn.smembers('selected_%s' % user.id)
                # 只留下要购物的商品id和count
                cart_dict = {}
                for sku_id_bytes in selected_ids:
                    cart_dict[int(sku_id_bytes)] = int(redis_carts[sku_id_bytes])

                # sku_qs = SKU.objects.filter(id__in=cart_dict.keys())  # 不要这样一下全查出来,会有缓存问题
                # zs: 1  9,  1    ls: 1  9, 0
                # 遍历cart_dict 大字典,进行一个一个商品下单
                for sku_id in cart_dict:

                    while True:
                        # 查询sku_id对应的sku模型
                        sku = SKU.objects.get(id=sku_id)
                        # 获取当前商品要购买的数量
                        buy_count = cart_dict[sku_id]
                        # 获取当前商品的原库存
                        origin_stock = sku.stock
                        # 获取当前商品的原销量
                        origin_sales = sku.sales

                        # import time
                        # time.sleep(5)

                        # 判断库存是否充足
                        if buy_count > origin_stock:
                            # 库存不足回滚
                            transaction.savepoint_rollback(save_point)
                            # 如果库存不足,直接提前响应
                            return http.JsonResponse({'code': RETCODE.STOCKERR, 'errmsg': '库存不足'})

                        # 修改sku库存和销量
                        new_stock = origin_stock - buy_count
                        new_sales = origin_sales + buy_count
                        # sku.stock = new_stock
                        # sku.sales = new_sales
                        # sku.save()
                        result = SKU.objects.filter(id=sku_id, stock=origin_stock).update(stock=new_stock,
                                                                                          sales=new_sales)
                        # 如果下单失败,给用户无限次下单机会,只到成功或库存不足
                        if result == 0:
                            continue

                        # 修改spu的销量
                        spu = sku.spu
                        spu.sales += buy_count
                        spu.save()

                        # 新增N个订单中商品记录
                        OrderGoods.objects.create(
                            order=order,
                            sku=sku,
                            count=buy_count,
                            price=sku.price
                        )

                        # 修改订单中商品总数量
                        order.total_count += buy_count
                        # 修改订单中支付金额
                        order.total_amount += (sku.price * buy_count)
                        # 代码能执行到这里说明当前商品下单成功
                        break

                # 订单实付金额累加运费
                order.total_amount += order.freight
                order.save()
            except Exception as e:
                logger.error(e)
                # 暴力回滚
                transaction.savepoint_rollback(save_point)
                return http.JsonResponse({'code': RETCODE.STOCKERR, 'errmsg': '下单失败'})
            else:
                # 提交事务
                transaction.savepoint_commit(save_point)

        # 删除购物车中已被购买的商品
        pl = redis_conn.pipeline()
        pl.hdel('cart_%s' % user.id, *selected_ids)
        pl.delete('selected_%s' % user.id)
        pl.execute()

        # 响应
        return http.JsonResponse({'code': RETCODE.OK, 'errmsg': '提交订单成功', 'order_id': order_id})


class OrderSuccessView(LoginRequiredView):
    """订单成功界面"""

    def get(self, request):

        # 接收
        query_dict = request.GET
        payment_amount = query_dict.get('payment_amount')
        order_id = query_dict.get('order_id')
        pay_method = query_dict.get('pay_method')

        # 校验
        try:
            OrderInfo.objects.get(order_id=order_id, total_amount=payment_amount, pay_method=pay_method,
                                  user=request.user)
        except OrderInfo.DoesNotExist:
            return http.HttpResponseForbidden('订单信息有误')

        context = {
            'payment_amount': payment_amount,
            'order_id': order_id,
            'pay_method': pay_method
        }

        return render(request, 'order_success.html', context)
