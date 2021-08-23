from django.shortcuts import render, redirect
from django.views import View
from django import http
import re
from django.contrib.auth import login, authenticate, logout
from django_redis import get_redis_connection
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
import json
from django.core.mail import send_mail
from django.db import DatabaseError

from .models import User, Address
from meiduo_mall.utils.response_code import RETCODE
from meiduo_mall.utils.views import LoginRequiredView
from celery_tasks.email.tasks import send_verify_email
from .utils import generate_verify_email_url, get_user_check_token
from goods.models import SKU
from carts.utils import merge_cart_cookie_to_redis
import logging

logger = logging.getLogger('django')


class RegisterView(View):
    """注册"""

    def get(self, request):
        return render(request, 'register.html')

    def post(self, request):

        # 1.接收请求体表单数据  POST
        query_dict = request.POST
        username = query_dict.get('username')
        password = query_dict.get('password')
        password2 = query_dict.get('password2')
        mobile = query_dict.get('mobile')
        sms_code = query_dict.get('sms_code')
        allow = query_dict.get('allow')  # 如果表单中的复选框没有指定value时勾选 传入的是'on' 反之 None

        # 2.校验数据  '' {} [] False None
        # all( [] )  返回True , False
        if all([username, password, password2, mobile, sms_code, allow]) is False:
            return http.HttpResponseForbidden('缺少必传参数')

        if not re.match(r'^[a-zA-Z0-9_-]{5,20}$', username):
            return http.HttpResponseForbidden('请输入5-20个字符的用户名')
        if not re.match(r'^[0-9A-Za-z]{8,20}$', password):
            return http.HttpResponseForbidden('请输入8-20位的密码')
        if password != password2:
            return http.HttpResponseForbidden('输入两次密码不一致')
        if not re.match(r'^1[3-9]\d{9}$', mobile):
            return http.HttpResponseForbidden('请输入正确的手机号码')

        # 创建redis连接对象
        redis_conn = get_redis_connection('verify_codes')
        # 获取redis数据库中当前用户短信验证码
        sms_code_server_bytes = redis_conn.get('sms_%s' % mobile)

        # 删除已经取出的短信验证码,让它只能被用一次
        redis_conn.delete('sms_%s' % mobile)

        # 判断redis中短信验证码过期
        if sms_code_server_bytes is None:
            return http.JsonResponse({'code': RETCODE.SMSCODERR, 'errmsg': '短信验证码已过期'})
        # 将bytes类型转换为字符串类型
        sms_code_server = sms_code_server_bytes.decode()
        # 用户填写的和redis中的短信验证码是否一致
        if sms_code != sms_code_server:
            return http.JsonResponse({'code': RETCODE.SMSCODERR, 'errmsg': '短信验证码填写错误'})

        # 创建user并且存储到表中
        # user = User.objects.create(
        #     username = username,
        #     password =password
        #     mobile = mobile
        # )
        # user.set_password(password)
        # user.save()
        # 创建并保存用户
        user = User.objects.create_user(username=username, password=password, mobile=mobile)
        # 用户注册成功即代表登录成功(状态保持)
        # request.session['id'] = user.id
        #
        # user_id = request.session['id']
        login(request, user)
        response = redirect('/')
        response.set_cookie('username', user.username, max_age=settings.SESSION_COOKIE_AGE)
        # 响应()
        # return http.HttpResponse('注册成功,应该去到首页')
        return response


class UsernameCountView(View):
    """判断用户名是否重复"""

    def get(self, request, username):
        # 查询user表, 查询username的数量
        count = User.objects.filter(username=username).count()

        # 包装响应数据
        data = {
            'count': count,
            'code': RETCODE.OK,  # 自定义状态码
            'errmsg': 'OK'
        }
        # 响应
        return http.JsonResponse(data)


class MobileCountView(View):
    """判断手机号是否重复"""

    def get(self, request, mobile):
        # 查询user表, 查询mobile的数量
        count = User.objects.filter(mobile=mobile).count()

        # 包装响应数据
        data = {
            'count': count,
            'code': RETCODE.OK,  # 自定义状态码
            'errmsg': 'OK'
        }
        # 响应
        return http.JsonResponse(data)


class LoginView(View):
    """登录"""

    def get(self, request):
        return render(request, 'login.html')

    def post(self, request):
        # 接收请求表单数据
        query_dict = request.POST
        # print(query_dict.dict().keys())
        username = query_dict.get('username')
        password = query_dict.get('password')
        remembered = query_dict.get('remembered')

        # 校验
        if all([username, password]) is False:
            return http.HttpResponseForbidden('缺少必传参数')

        # 用户登录认证验证
        user = authenticate(request, username=username, password=password)
        # if 如果是手机号登录:
        #     user = User.objects.get(mobile=username)
        # elif 如果是邮箱登录:
        #     user = User.objects.get(email=username)
        # else:
        #     user = User.objects.get(username=username)
        # user = User.objects.get(email=username)
        # user.check_password(password)
        # 判断用户是否通过身份认证
        if user is None:
            return render(request, 'login.html', {'account_errmsg': '用户名或密码错误'})

        # 状态操持
        login(request, user)
        # 如果用户没有勾选记住登录,设置session过期时间为会话结束
        # if remembered is None:
        #     request.session.set_expiry(0)
        # else:
        #     request.session.set_expiry(3600 * 24 * 7)

        # request.session.set_expiry(0 if remembered is None else (3600 * 24 * 7))
        request.session.set_expiry(None if remembered else 0)

        # 获取用户界面来源
        next = request.GET.get('next')
        # 创建响应对象
        response = redirect(next or '/')
        # 用户登录成功后向cookie中存储username
        # response.set_cookie('username', user.username, max_age=None if remembered is None else settings.SESSION_COOKIE_AGE)
        response.set_cookie('username', user.username, max_age=remembered and settings.SESSION_COOKIE_AGE)
        # 重定向到首页
        # return http.HttpResponse('登录成功,跳转到首页界面')
        # 登录成功合并购物车
        merge_cart_cookie_to_redis(request, response)

        return response


class LogoutView(View):
    """退出登录"""

    def get(self, request):
        # 1.清除状态操持
        logout(request)

        # 创建响应对象
        response = redirect('users:login')
        # 2.清除cookie中的username
        response.delete_cookie('username')

        # 3.重定向到login
        return response


# class InfoView(View):
#     """用户中心"""
#     def get(self, request):
#         user = request.user
#          # 如果用户没有登录就跳转到登录界面
#         if not user.is_authenticated:
#             # return redirect('users:login')
#             return redirect('/login/?next=/info/')
#         else:
#              # 如果用户登录了,就展示用户中心界面
#             return render(request, 'user_center_info.html')


# @method_decorator(login_required, name='get')
# class InfoView(View):
#     """用户中心"""
#     def get(self, request):
#         return render(request, 'user_center_info.html')

class InfoView(LoginRequiredMixin, View):
    """用户中心"""

    def get(self, request):
        return render(request, 'user_center_info.html')


class EmailView(LoginRequiredView):
    """设置用户邮箱,并发送激活邮箱url"""

    def put(self, request):
        # 1.接收请求体非表单数据 body
        json_dict = json.loads(request.body.decode())
        email = json_dict.get('email')

        # 2.校验
        if not re.match(r'^[a-z0-9][\w\.\-]*@[a-z0-9\-]+(\.[a-z]{2,5}){1,2}$', email):
            return http.HttpResponseForbidden('邮箱格式有误')

        # 3.修改user模型的email字段

        user = request.user
        # 如果用户还没有设置邮箱再去设置,如果设置过了就不要再设置了
        if user.email != email:
            user.email = email
            user.save()

        # 给当前设置的邮箱发一封激活url
        # send_mail(subject='邮件的标题/主题', message='普通字符串邮件正文', from_email='发件人', recipient_list=['收件人邮箱'],
        # html_message='超文本邮件正文')
        # html_message = '<p>这是一个激活邮件 <a href="http://www.baidu.com">点我一下</a></p>'
        # send_mail(subject='激活邮箱', message='普通字符串邮件正文', from_email='美多商城<itcast99@163.com>', recipient_list=[email],
        #       html_message=html_message)
        # verify_url = 'http://www.baidu.com'
        # http://www.meiduo.site:8000/verify_email/?token=kfl
        verify_url = generate_verify_email_url(user)
        send_verify_email.delay(email, verify_url)

        # 响应
        return http.JsonResponse({'code': RETCODE.OK, 'errmsg': '添加邮箱成功'})


class EmailVerifyView(View):
    """激活邮箱"""

    def get(self, request):
        # 1.接收查询参数中的token
        token = request.GET.get('token')

        # 2.对token解密 并根据用户信息查询到指定user
        user = get_user_check_token(token)
        if user is None:
            return http.HttpResponseForbidden('邮箱激活失败')

        # 3. 修改指定user的email_active字段
        user.email_active = True
        user.save()

        # 4.响应
        return render(request, 'user_center_info.html')


class AddressesView(LoginRequiredView):
    """用户收货地址"""

    def get(self, request):
        user = request.user
        # 将当前登录用户的所有未被逻辑删除的收货地址全部查询出来
        address_qs = Address.objects.filter(user=user, is_deleted=False)
        # user.addresses.filter(is_deleted=False)
        # 对查询集中的每个address模型对象转换成字典并包装到列表中
        address_list = []  # 用来装收货地址字典
        for address in address_qs:
            address_list.append({
                'id': address.id,
                'title': address.title,
                'receiver': address.receiver,
                'province_id': address.province_id,
                'province': address.province.name,
                'city_id': address.city_id,
                'city': address.city.name,
                'district_id': address.district_id,
                'district': address.district.name,
                'place': address.place,
                'mobile': address.mobile,
                'tel': address.tel,
                'email': address.email
            })

        context = {
            'addresses': address_list,
            'default_address_id': user.default_address_id
        }
        return render(request, 'user_center_site.html', context)


class AddressCreateView(LoginRequiredView):
    """新增收货地址"""

    def post(self, request):

        # 1.接收请求体非表单数据 body
        json_dict = json.loads(request.body.decode())
        title = json_dict.get('title')
        receiver = json_dict.get('receiver')
        province_id = json_dict.get('province_id')
        city_id = json_dict.get('city_id')
        district_id = json_dict.get('district_id')
        place = json_dict.get('place')
        mobile = json_dict.get('mobile')
        tel = json_dict.get('tel')
        email = json_dict.get('email')

        # 2. 校验
        if all([title, receiver, province_id, city_id, district_id, place, mobile]) is False:
            return http.HttpResponseForbidden('缺少必传参数')

        if not re.match(r'^1[3-9]\d{9}$', mobile):
            return http.HttpResponseForbidden('手机号格式有误')

        if tel:
            if not re.match(r'^(0[0-9]{2,3}-)?([2-9][0-9]{6,7})+(-[0-9]{1,4})?$', tel):
                return http.HttpResponseForbidden('参数tel有误')
        if email:
            if not re.match(r'^[a-z0-9][\w\.\-]*@[a-z0-9\-]+(\.[a-z]{2,5}){1,2}$', email):
                return http.HttpResponseForbidden('参数email有误')

        user = request.user
        try:
            # 3.创建Address模型对象并保存数据
            address = Address.objects.create(
                user=user,
                title=title,
                receiver=receiver,
                province_id=province_id,
                city_id=city_id,
                district_id=district_id,
                place=place,
                mobile=mobile,
                tel=tel,
                email=email
            )
        except DatabaseError as e:
            logger.error(e)
            return http.HttpResponseForbidden('新增收货地址错误')

        # 判断当前用户是否有默认地址,如果还没有就把当前新增的收货地址设置为用户的默认收货地址
        if user.default_address is None:
            # 给用户设置一个默认地址
            user.default_address = address
            user.save()
        # 4.将新增好的address模型对象转换成字典
        address_dict = {
            'id': address.id,
            'title': address.title,
            'receiver': address.receiver,
            'province_id': address.province_id,
            'province': address.province.name,
            'city_id': address.city_id,
            'city': address.city.name,
            'district_id': address.district_id,
            'district': address.district.name,
            'place': address.place,
            'mobile': address.mobile,
            'tel': address.tel,
            'email': address.email
        }
        # 响应
        return http.JsonResponse({'code': RETCODE.OK, 'errmsg': '新增收货地址成功', 'address': address_dict})


class UpdateDestroyAddressView(LoginRequiredView):
    """修改和删除用户收货地址"""

    def put(self, request, address_id):
        user = request.user
        try:
            address = Address.objects.get(id=address_id, user=user, is_deleted=False)
        except Address.DoesNotExist:
            return http.HttpResponseForbidden('address_id有误')

        # 1.接收请求体非表单数据 body
        json_dict = json.loads(request.body.decode())
        title = json_dict.get('title')
        receiver = json_dict.get('receiver')
        province_id = json_dict.get('province_id')
        city_id = json_dict.get('city_id')
        district_id = json_dict.get('district_id')
        place = json_dict.get('place')
        mobile = json_dict.get('mobile')
        tel = json_dict.get('tel')
        email = json_dict.get('email')

        # 2. 校验
        if all([title, receiver, province_id, city_id, district_id, place, mobile]) is False:
            return http.HttpResponseForbidden('缺少必传参数')

        if not re.match(r'^1[3-9]\d{9}$', mobile):
            return http.HttpResponseForbidden('手机号格式有误')

        if tel:
            if not re.match(r'^(0[0-9]{2,3}-)?([2-9][0-9]{6,7})+(-[0-9]{1,4})?$', tel):
                return http.HttpResponseForbidden('参数tel有误')
        if email:
            if not re.match(r'^[a-z0-9][\w\.\-]*@[a-z0-9\-]+(\.[a-z]{2,5}){1,2}$', email):
                return http.HttpResponseForbidden('参数email有误')
        """
        try:
            # 3.创建Address模型对象并保存数据
            address = Address.objects.create(
                user=user,
                title=title,
                receiver=receiver,
                province_id=province_id,
                city_id=city_id,
                district_id=district_id,
                place=place,
                mobile=mobile,
                tel=tel,
                email=email
            )
        except DatabaseError as e:
            logger.error(e)
            return http.HttpResponseForbidden('新增收货地址错误')
        """

        # 3.修改用户收货地址

        address.title = title
        address.receiver = receiver
        address.province_id = province_id
        address.city_id = city_id
        address.district_id = district_id
        address.place = place
        address.mobile = mobile
        address.tel = tel
        address.email = email
        address.save()

        # Address.objects.filter(id=address_id).update()
        # address = address.objects.get(id=address_id)

        # 4.将新增好的address模型对象转换成字典
        address_dict = {
            'id': address.id,
            'title': address.title,
            'receiver': address.receiver,
            'province_id': address.province_id,
            'province': address.province.name,
            'city_id': address.city_id,
            'city': address.city.name,
            'district_id': address.district_id,
            'district': address.district.name,
            'place': address.place,
            'mobile': address.mobile,
            'tel': address.tel,
            'email': address.email
        }
        # 响应
        return http.JsonResponse({'code': RETCODE.OK, 'errmsg': '修改收货地址成功', 'address': address_dict})

    def delete(self, request, address_id):
        user = request.user
        try:
            # 校验address_id
            address = Address.objects.get(id=address_id, user=user, is_deleted=False)
        except Address.DoesNotExist:
            return http.HttpResponseForbidden('address_id有误')

        # 将address的is_delete字段设置为True 做逻辑删除
        address.is_deleted = True
        address.save()

        # 响应
        return http.JsonResponse({'code': RETCODE.OK, 'errmsg': '删除收货地址成功'})


class UpdateAddressTitleView(LoginRequiredView):
    """修改收货地址标题"""
    def put(self, request, address_id):
        user = request.user
        try:
            # 校验address_id
            address = Address.objects.get(id=address_id, user=user, is_deleted=False)
        except Address.DoesNotExist:
            return http.HttpResponseForbidden('address_id有误')

        # 接收请求体数据
        json_dict = json.loads(request.body.decode())
        title = json_dict.get('title')

        # 校验
        if title is None:
            return http.HttpResponseForbidden('缺少title')

        # 修改当前address.title
        address.title = title
        address.save()

        return http.JsonResponse({'code': RETCODE.OK, 'errmsg': '修改地址标题成功'})


class UserDefaultAddressView(LoginRequiredView):
    """设置用户默认收货地址"""
    def put(self, request, address_id):
        user = request.user
        try:
            # 校验address_id
            address = Address.objects.get(id=address_id, user=user, is_deleted=False)
        except Address.DoesNotExist:
            return http.HttpResponseForbidden('address_id有误')
        # 修改用户默认收货地址
        user.default_address = address
        user.save()

        return http.JsonResponse({'code': RETCODE.OK, 'errmsg': '设置默认地址成功'})



class ChangeUserPasswordView(LoginRequiredView):
    """修改用户密码"""
    def get(self, request):
        return render(request, 'user_center_pass.html')

    def post(self, request):
        # 接收请求体表单数据
        query_dict = request.POST
        old_pwd = query_dict.get('old_pwd')
        new_pwd = query_dict.get('new_pwd')
        new_cpwd = query_dict.get('new_cpwd')

        # 校验
        if all([old_pwd, new_pwd, new_cpwd]) is False:
            return http.HttpResponseForbidden('缺少必传参数')

        user = request.user
        if user.check_password(old_pwd) is False:
            return render(request, 'user_center_pass.html', {'origin_pwd_errmsg': '原始密码有误'})

        if not re.match(r'^[0-9A-Za-z]{8,20}$', new_pwd):
            return http.HttpResponseForbidden('密码最少8位，最长20位')
        if new_pwd != new_cpwd:
            return http.HttpResponseForbidden('两次输入的密码不一致')

        # 修改用户的password值: 对密码加密后再存储
        user.set_password(new_pwd)
        user.save()

        # return redirect('/logout/')

        # 清除状态保持
        logout(request)
        response = redirect('/login/')
        # 将cookie中的username清除
        response.delete_cookie('username')
        # 重定向到login界面
        return response


class UserBrowseHistory(View):
    """用户商品浏览记录"""

    def post(self, request):
        """保存商品浏览记录"""
        user = request.user
        # 如果用户没有登录直接提前响应
        if not user.is_authenticated:
            return http.JsonResponse({'code': RETCODE.SESSIONERR, 'errmsg': '未登录用户不能添加浏览记录'})
        # 接收
        json_dict = json.loads(request.body.decode())
        sku_id = json_dict.get('sku_id')

        # 校验
        try:
            sku_model = SKU.objects.get(id=sku_id, is_launched=True)
        except SKU.DoesNotExist:
            return http.HttpResponseForbidden('sku_id不存在')

        # 创建redis连接对象
        redis_conn = get_redis_connection('history')


        # 接收用户redis中列表的key
        key = 'history_%s' % user.id
        # 创建管道
        pl = redis_conn.pipeline()
        # 先去重
        pl.lrem(key, 0, sku_id)
        # 添加到列表中开头
        pl.lpush(key, sku_id)
        # 截取列表中前5个元素
        pl.ltrim(key, 0, 4)
        # 执行管道
        pl.execute()

        # 响应
        return http.JsonResponse({'code': RETCODE.OK, 'errmsg': 'OK'})

    def get(self, request):
        """获取商品浏览记录"""
        user = request.user
        if not user.is_authenticated:
            return http.JsonResponse({'code': RETCODE.SESSIONERR, 'errmsg': '未登录用户没有商品浏览记录'})

        # 创建redis连接对象
        redis_conn = get_redis_connection('history')

        # lrange指令获取当前用户浏览记录列表
        sku_ids = redis_conn.lrange('history_%s' % user.id, 0, -1)
        # 获取指定sku_id对应的sku模型
        # sku_qs = SKU.objects.filter(id__in=[1, 2])  # 此种写法浏览记录顺序就乱了
        sku_list = []  # 用来装每一个sku字典
        for sku_id in sku_ids:
            # 查询sku模型
            sku_model = SKU.objects.get(id=sku_id)
            # sku模型转换成字典
            sku_list.append(
                {
                    'id': sku_model.id,
                    'default_image_url': sku_model.default_image.url,
                    'name': sku_model.name,
                    'price': sku_model.price
                }
            )

        # 响应
        return http.JsonResponse({'code': RETCODE.OK, 'errmsg': 'OK', 'skus': sku_list})

