from django.shortcuts import render
from django.views import View
import json, pickle, base64
from django import http
from goods.models import SKU
from django_redis import get_redis_connection

from meiduo_mall.utils.response_code import RETCODE

import logging

logger = logging.getLogger('django')  # 创建自定义日志输出器对象


class CartsView(View):
    """购物车"""

    def post(self, request):

        # 接收
        json_dict = json.loads(request.body.decode())
        sku_id = json_dict.get('sku_id')
        count = json_dict.get('count')
        selected = json_dict.get('selected', True)

        # 校验
        if all([sku_id, count]) is False:
            return http.HttpResponseForbidden('缺少必传参数')
        try:
            sku = SKU.objects.get(id=sku_id, is_launched=True)
        except SKU.DoesNotExist:
            return http.HttpResponseForbidden('sku_id不存在')

        try:
            count = int(count)
        except Exception as e:
            logger.error(e)
            return http.HttpResponseForbidden('参数类型有误')

        if isinstance(selected, bool) is False:
            return http.HttpResponseForbidden('参数类型有误')

        user = request.user
        # 判断用户是否登录
        if user.is_authenticated:
            # 如果是登录用户存储购物车数据到redis
            """
            hash: {sku_id_1: 1, sku_id_16: count}
            set: {sku_id_1, sku_id_16}
            """
            # 创建redis连接对象
            redis_conn = get_redis_connection('carts')
            # 创建管道
            pl = redis_conn.pipeline()
            # hincrby() 操作hash如果要添加的已存在,会自动做增量,不存在就是新增
            pl.hincrby('cart_%s' % user.id, sku_id, count)

            # 判断当前商品是否勾选
            if selected:
                # 如果勾选就将商品的sku_id 存储到set集合中
                pl.sadd('selected_%s' % user.id, sku_id)
                # sadd()
            pl.execute()  # 执行管道
            # 响应
            return http.JsonResponse({'code': RETCODE.OK, 'errmsg': '添加购物车数据成功'})

        else:
            # 如果是未登录用户存储购物车数据到cookie
            """
                {
                    sku_id_1: {'count': 1, 'selected': True},
                    sku_id_12: {'count': 1, 'selected': False}
                    
                }
            """
            # 先尝试去获取cookie购物车数据
            cart_str = request.COOKIES.get('carts')
            # 判断用户是否已经有cookie购物车数据
            if cart_str:
                # 如果用户已经有cookie购物车数据,将字符串转换成字典
                bytes_str = cart_str.encode()
                bytes_un = base64.b64decode(bytes_str)
                cart_dict = pickle.loads(bytes_un)
                # 判断本次要添加的商品是否已存在
                if sku_id in cart_dict:
                    # 获取已存在商品原有的count
                    origin_count = cart_dict[sku_id]['count']
                    # 用原有count和本次count累加
                    count += origin_count
                    # count = count + origin_count

                # cart_dict = pickle.loads(base64.b64decode(cart_str.encode()))
            else:
                # 如果用户没有cookie购物车数据,定义一个新的空字典
                cart_dict = {}

            # 向cookie大字典中添加新的购物车商品数据
            cart_dict[sku_id] = {'count': count, 'selected': selected}
            # 将cookie大字典再转换回字符串
            bytes_un = pickle.dumps(cart_dict)
            bytes_str = base64.b64encode(bytes_un)
            cart_str = bytes_str.decode()
            # 创建响应对象
            response = http.JsonResponse({'code': RETCODE.OK, 'errmsg': '添加购物车成功'})
            # 将购物车数据字符串设置到cookie
            response.set_cookie('carts', cart_str)

            # 响应
            return response

    def get(self, request):
        """购物车展示"""

        # 判断用户是否登录
        user = request.user
        if user.is_authenticated:
            # 如果是登录用户获取redis中购物车数据
            # 创建redis连接对象
            redis_conn = get_redis_connection('carts')
            # 获取hash数据  {sku_id_1: count, sku_id_2: count}
            redis_carts = redis_conn.hgetall('cart_%s' % user.id)
            # 获取set数据 {sku_id_1}
            selected_ids = redis_conn.smembers('selected_%s' % user.id)
            """
                {
                    sku_id_1: {'count': 1, 'selected': True},
                    sku_id_12: {'count': 1, 'selected': False}

                }
            """
            # 将redis购物车数据转换成cookie购物车大字典格式
            cart_dict = {}  # 用来包装redis购物车的所有数据
            for sku_id_bytes in redis_carts:
                cart_dict[int(sku_id_bytes)] = {
                    'count': int(redis_carts[sku_id_bytes]),
                    'selected': sku_id_bytes in selected_ids
                }

        else:
            # 如果是未登录用户获取cookie中购物车数据
            # 获取cookie购物车数据
            cart_str = request.COOKIES.get('carts')
            # 判断是否有cookie购物车数据
            if cart_str:
                # 如果获取到cookie购物车数据将str车换成字典
                cart_dict = pickle.loads(base64.b64decode(cart_str.encode()))
            else:
                # 如果没有获取到cookie购物车数据,直接渲染空白的购物车界面
                return render(request, 'cart.html')


        # 查询sku模型
        sku_qs = SKU.objects.filter(id__in=cart_dict.keys())
        sku_list = []  # 用来包装模板渲染时的所有sku字典数据
        # 包装模板渲染时的数据
        for sku_model in sku_qs:
            count = cart_dict[sku_model.id]['count']
            sku_list.append(
                {
                    'id': sku_model.id,
                    'name': sku_model.name,
                    'default_image_url': sku_model.default_image.url,
                    'price': str(sku_model.price),
                    'count': count,
                    'selected': str(cart_dict[sku_model.id]['selected']),
                    'amount': str(sku_model.price * count)
                }
            )

        return render(request, 'cart.html', {'cart_skus': sku_list})

    def put(self, request):
        """购物车修改"""
        # 接收请求体数据
        json_dict = json.loads(request.body.decode())
        sku_id = json_dict.get('sku_id')
        count = json_dict.get('count')
        selected = json_dict.get('selected')

        # 校验
        if all([sku_id, count]) is False:
            return http.HttpResponseForbidden('缺少必传参数')

        try:
            sku = SKU.objects.get(id=sku_id, is_launched=True)
        except SKU.DoesNotExist:
            return http.HttpResponseForbidden('sku_id不存在')

        try:
            count = int(count)
        except Exception as e:
            logger.error(e)
            return http.HttpResponseForbidden('参数类型有误')

        if isinstance(selected, bool) is False:
            return http.HttpResponseForbidden('参数类型有误')

        # 包装一个修改后的购物车商品大字典数据
        sku_dict = {
            'id': sku.id,
            'name': sku.name,
            'default_image_url': sku.default_image.url,
            'price': str(sku.price),
            'count': count,
            'selected': selected,  # 注意修改时selected就不要转字符串
            'amount': sku.price * count
        }
        # 创建响应对象
        response = http.JsonResponse({'code': RETCODE.OK, 'errmsg': '修改购物车数据成功', 'cart_sku': sku_dict})


        # 判断用户是否登录
        user = request.user
        if user.is_authenticated:
            # 登录用户修改redis购物车数据
            # 创建redis连接对象
            redis_conn = get_redis_connection('carts')
            # 修改hash数据
            redis_conn.hset('cart_%s' % user.id, sku_id, count)
            # 修改set数据
            if selected:
                redis_conn.sadd('selected_%s' % user.id, sku_id)
            else:
                redis_conn.srem('selected_%s' % user.id, sku_id)

        else:
            # 未登录用户修改cookie购物车数据
            # 获取cookie中购物车数据
            cart_str = request.COOKIES.get('carts')
            # 判断用户是否有cookie购物车数据
            if cart_str:
                # 如果有cookie购物车数据将str 转换成字典
                cart_dict = pickle.loads(base64.b64decode(cart_str.encode()))
            else:
                # 如果没有cookie购物车数据直接响应
                return http.HttpResponseForbidden('没有cookie数据,何来修改')

            # 直接修改cookie大字典数据
            cart_dict[sku_id] = {
                'count': count,
                'selected': selected
            }
            # 将字典转换回字符串
            cart_str = base64.b64encode(pickle.dumps(cart_dict)).decode()
            # 设置cookie
            response.set_cookie('carts', cart_str)


        # 响应
        return response

    def delete(self, request):
        """购物车数据删除"""

        # 接收
        json_dict = json.loads(request.body.decode())
        sku_id = json_dict.get('sku_id')

        # 校验
        try:
            sku = SKU.objects.get(id=sku_id, is_launched=True)
        except SKU.DoesNotExist:
            return http.HttpResponseForbidden('sku_id无效')

        # 判断用户是否登录
        user = request.user
        if user.is_authenticated:
            # 登录用户删除redis中相应购物车数据
            # 创建redis连接对象
            redis_conn = get_redis_connection('carts')
            # 创建管道对象
            pl = redis_conn.pipeline()
            # 删除hash中指定sku_id
            pl.hdel('cart_%s' % user.id, sku_id)
            # 删除set中指定的sKu_id
            pl.srem('selected_%s' % user.id, sku_id)
            # 执行管道
            pl.execute()
            # 响应
            return http.JsonResponse({'code': RETCODE.OK, 'errmsg': '删除购物车成功'})
        else:
            # 未登录用户删除cookie中相应购物车数据
            # 获取cookie购物车数据
            cart_str = request.COOKIES.get('carts')
            # 判断是否获取到cookie购物车数据
            if cart_str:
                # 将cookie购物车字符串转换回字典
                cart_dict = pickle.loads(base64.b64decode(cart_str.encode()))
            else:
                # 如果没有获取到cookie购物车数据,提前响应
                return http.HttpResponseForbidden('没有cookie,删除什么?')

            # 删除cookie大字典中的指定sku_id
            if sku_id in cart_dict:  # 判断sku_id在字典中是否存在
                del cart_dict[sku_id]

            # 判断用户cookie大字典中是否还有数据
            # ''  []  {} 0, False None
            # 创建响应对象
            response = http.JsonResponse({'code': RETCODE.OK, 'errmsg': '删除购物车成功'})
            if not cart_dict:
                # 如果cookie购物车字典已是空字典,直接将cookie购物车删除
                response.delete_cookie('carts')
                return response
            # 如果还有数据,就将字典转回字符串,再设置cookie
            cart_str = base64.b64encode(pickle.dumps(cart_dict)).decode()
            response.set_cookie('carts', cart_str)
            return response


class CartsSelectedAllView(View):
    """购物车全选"""
    def put(self, request):

        # 接收
        json_dict = json.loads(request.body.decode())
        selected = json_dict.get('selected')

        # 校验
        if isinstance(selected, bool) is False:
            return http.HttpResponseForbidden('参数类型有误')

        # 判断用户是否登录
        user = request.user
        if user.is_authenticated:
            # 登录用户修改redis购物车数据
            # 创建redis连接对象
            redis_conn = get_redis_connection('carts')
            # 判断本次是全选还是取消全选
            if selected:
                # 如果是全选获取hash中的数据
                redis_carts = redis_conn.hgetall('cart_%s' % user.id)
                # 将所有sku_id添加到set集合  *[1, 16]   redis_carts.keys()   1, 16
                redis_conn.sadd('selected_%s' % user.id, *redis_carts.keys())
            else:
                # 如果是取消全选,将set直接移除
                redis_conn.delete('selected_%s' % user.id)
                # redis_conn.srem('selected_%s' % user.id, *redis_carts.keys())

            return http.JsonResponse({'code': RETCODE.OK, 'errmsg': '购物车全选成功'})
        else:
            # 未登录用户修改cookie购物车数据
            # 获取cookie购物车数据
            cart_str = request.COOKIES.get('carts')
            # 判断是否获取到cookie购物车数据
            if cart_str:
                # 将cookie购物车字符串转换成字典
                cart_dict = pickle.loads(base64.b64decode(cart_str.encode()))
            else:
                # 如果没有cookie购物车数据,提前响应
                return http.HttpResponseForbidden('cookie购物车都没有,全选什么?')

            # 遍历cookie购物车大字典将里面的每一个selected改为True或 False
            for sku_id in cart_dict:
                cart_dict[sku_id]['selected'] = selected
            # 将cart_dict 转换成 cart_str
            cart_str = base64.b64encode(pickle.dumps(cart_dict)).decode()
            # 创建响应对象
            response = http.JsonResponse({'code': RETCODE.OK, 'errmsg': '购物车全选成功'})
            # 设置cookie
            response.set_cookie('carts', cart_str)
            return response

"""
    {
        sku_id_1: {'count': 1, 'selected': True},
        sku_id_12: {'count': 1, 'selected': False}

    }
"""


class CartsSimpleView(View):
    """mini版购物车展示"""
    def get(self, request):
        # 判断用户是否登录
        user = request.user
        if user.is_authenticated:
            # 如果是登录用户获取redis中购物车数据
            # 创建redis连接对象
            redis_conn = get_redis_connection('carts')
            # 获取hash数据  {sku_id_1: count, sku_id_2: count}
            redis_carts = redis_conn.hgetall('cart_%s' % user.id)
            # 获取set数据 {sku_id_1}
            selected_ids = redis_conn.smembers('selected_%s' % user.id)
            """
                {
                    sku_id_1: {'count': 1, 'selected': True},
                    sku_id_12: {'count': 1, 'selected': False}

                }
            """
            # 将redis购物车数据转换成cookie购物车大字典格式
            cart_dict = {}  # 用来包装redis购物车的所有数据
            for sku_id_bytes in redis_carts:
                cart_dict[int(sku_id_bytes)] = {
                    'count': int(redis_carts[sku_id_bytes]),
                    'selected': sku_id_bytes in selected_ids
                }

        else:
            # 如果是未登录用户获取cookie中购物车数据
            # 获取cookie购物车数据
            cart_str = request.COOKIES.get('carts')
            # 判断是否有cookie购物车数据
            if cart_str:
                # 如果获取到cookie购物车数据将str车换成字典
                cart_dict = pickle.loads(base64.b64decode(cart_str.encode()))
            else:
                # 如果没有获取到cookie购物车数据,直接渲染空白的购物车界面
                return render(request, 'cart.html')

        # 查询sku模型
        sku_qs = SKU.objects.filter(id__in=cart_dict.keys())
        sku_list = []  # 用来包装模板渲染时的所有sku字典数据
        # 包装模板渲染时的数据
        for sku_model in sku_qs:
            count = cart_dict[sku_model.id]['count']
            sku_list.append(
                {
                    'id': sku_model.id,
                    'name': sku_model.name,
                    'default_image_url': sku_model.default_image.url,
                    'count': count,

                }
            )

        return http.JsonResponse({'code': RETCODE.OK, 'errmsg': 'OK', 'cart_skus': sku_list})



