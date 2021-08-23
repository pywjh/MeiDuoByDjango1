from django.shortcuts import render, redirect
from QQLoginTool.QQtool import OAuthQQ
from django.views import View
from django.conf import settings
from django.http import JsonResponse, HttpResponseForbidden, HttpResponseServerError
from django.contrib.auth import login
import re
from django_redis import get_redis_connection

from meiduo_mall.utils.response_code import RETCODE
from .models import OAuthQQUser
from .utils import generate_openid_signature, check_openid
from users.models import User
# from meiduo_mall.apps.users.models import User
from carts.utils import merge_cart_cookie_to_redis


# 导入应用模块时,导包依赖路径必须和注册应用时所用的导包依赖要一致

import logging
logger = logging.getLogger('django')


class QQAuthURLView(View):
    """提供QQ登录url"""
    def get(self, request):

        # 1.获取查询参数
        next = request.GET.get('next') or '/'

        # 2.创建OAuthQQ 工具对象
        # auth_qq = OAuthQQ(client_id='appid', client_secret='appkey', redirect_uri='QQ登录成功后的回调地址', state='登录成功重定向时会原样带回')
        # auth_qq = OAuthQQ(client_id='101518219',
        #                   client_secret='418d84ebdc7241efb79536886ae95224',
        #                   redirect_uri='http://www.meiduo.site:8000/oauth_callback',
        #                   state=next)

        auth_qq = OAuthQQ(client_id=settings.QQ_CLIENT_ID,
                          client_secret=settings.QQ_CLIENT_SECRET,
                          redirect_uri=settings.QQ_REDIRECT_URI,
                          state=next)

        # 3.调用它里面的get_qq_url方法 得到拼接好的qq登录url
        login_url = auth_qq.get_qq_url()

        # 4.响应
        return JsonResponse({'login_url': login_url, 'code': RETCODE.OK, 'errmsg': 'OK'})


class QQAuthView(View):
    """QQ扫码登录成功后的回调处理"""

    def get(self, request):

        # 1.获取查询字符串code
        code = request.GET.get('code')

        # 2.校验是否获取到code
        if code is None:
            return HttpResponseForbidden('缺少code')

        # 3.创建QQ 登录辅助工具对象
        auth_qq = OAuthQQ(client_id=settings.QQ_CLIENT_ID,
                          client_secret=settings.QQ_CLIENT_SECRET,
                          redirect_uri=settings.QQ_REDIRECT_URI)

        try:
            # 4.调用 get_access_token(code) 得到access_token
            access_token = auth_qq.get_access_token(code)
            # 5. 调用 get_open_id(access_token)  得到openid
            openid = auth_qq.get_open_id(access_token)
        except Exception as e:
            logger.error(e)
            return HttpResponseServerError('OAuth2.0认证失败')


        # 6. 查询openid
        try:
            oAuth_model = OAuthQQUser.objects.get(openid=openid)
            # 如果能执行到这里说明上面那行代码查询到了openid
            # 查询到openid说明此QQ用户已绑定过美多用户,直接代表登录成功
            user = oAuth_model.user
            # 状态保持
            login(request, user)
            # 获取查询参数中的state
            next = request.GET.get('state') or '/'
            # 创建响应对象
            response = redirect(next)
            # 向浏览器的cookie中存储username
            response.set_cookie('username', user.username, max_age=settings.SESSION_COOKIE_AGE)

            # 登录成功合并购物车
            merge_cart_cookie_to_redis(request, response)
            # 重定向到来源界面
            return response

        except OAuthQQUser.DoesNotExist:
            # 说明openid还没有绑定美多用户,渲染一个绑定界面
            # 对openid进行加密
            openid = generate_openid_signature(openid)

            return render(request, 'oauth_callback.html', {'openid': openid})

    def post(self, request):
        """openid 绑定用户逻辑"""

        # 1.接收表单数据
        query_dict = request.POST
        mobile = query_dict.get('mobile')
        password = query_dict.get('password')
        sms_code = query_dict.get('sms_code')
        openid_sign = query_dict.get('openid')


        # 2.校验
        # if all(query_dict.dict().values()) is False:
        if all([mobile, password, sms_code, openid_sign]) is False:
            return HttpResponseForbidden('缺少必传参数')

        if not re.match(r'^[0-9A-Za-z]{8,20}$', password):
            return HttpResponseForbidden('请输入8-20位的密码')

        if not re.match(r'^1[3-9]\d{9}$', mobile):
            return HttpResponseForbidden('请输入正确的手机号码')

        # 创建redis连接对象
        redis_conn = get_redis_connection('verify_codes')
        # 获取redis数据库中当前用户短信验证码
        sms_code_server_bytes = redis_conn.get('sms_%s' % mobile)

        # 删除已经取出的短信验证码,让它只能被用一次
        redis_conn.delete('sms_%s' % mobile)

        # 判断redis中短信验证码过期
        if sms_code_server_bytes is None:
            return JsonResponse({'code': RETCODE.SMSCODERR, 'errmsg': '短信验证码已过期'})
        # 将bytes类型转换为字符串类型
        sms_code_server = sms_code_server_bytes.decode()
        # 用户填写的和redis中的短信验证码是否一致
        if sms_code != sms_code_server:
            return JsonResponse({'code': RETCODE.SMSCODERR, 'errmsg': '短信验证码填写错误'})

        # 对openid进行解密
        openid = check_openid(openid_sign)
        if openid is None:
            return HttpResponseForbidden('openid无效')


        # 3. 根据手机号字段查询user表
        try:
            # 3.1 如果通过mobile字段查询到用户 说明此用户是已有账号的美多老用户
            user = User.objects.get(mobile=mobile)
            # 3.1.1 如果是老用户还要校验用户密码是否正确
            if user.check_password(password) is False:
                return HttpResponseForbidden('老用户信息添写不正确')
        except User.DoesNotExist:

            # 3.2 如果没有查询到用户,说明它是一个美多新用户,
            # 3.3 如果是新用户,就创建一个新的user 用户名就用mobile
            user = User.objects.create_user(username=mobile, password=password, mobile=mobile)


        # 4.创建OAuthQQUser 新的记录保存openid 及user  openid绑定美多用户

        OAuthQQUser.objects.create(
            openid=openid,
            user=user
            # user_id=user.id
        )


        # 5. 状态保持, username
        login(request, user)
        # 获取state 界面来源
        next = request.GET.get('state') or '/'
        # 创建响应对象
        response = redirect(next)
        response.set_cookie('username', user.username, max_age=settings.SESSION_COOKIE_AGE)

        # 登录成功合并购物车
        merge_cart_cookie_to_redis(request, response)

        # 重定向到指定来源界面
        return response


