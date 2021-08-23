from django.shortcuts import render
from django.views import View
from django import http
from random import randint

from meiduo_mall.libs.captcha.captcha import captcha
from django_redis import get_redis_connection
from meiduo_mall.utils.response_code import RETCODE
# from meiduo_mall.libs.yuntongxun.sms import CCP
from . import constants
from celery_tasks.sms.tasks import send_sms_code

import logging

logger = logging.getLogger('django')


class ImageCodeView(View):
    """图形验证码"""

    def get(self, request, uuid):
        # 调用SDK生成图形验证码
        name, text, image_bytes = captcha.generate_captcha()

        # 创建redis连接
        redis_conn = get_redis_connection('verify_codes')
        # 将图形验证码字符串内容存储到redis
        redis_conn.setex(uuid, constants.IMAGE_CODE_EXPIRE, text)
        # 将图形bytes数据响应给前端  # MIME
        return http.HttpResponse(image_bytes, content_type='image/png')


class SMSCodeView(View):
    """短信验证码"""

    def get(self, request, mobile):

        # 创建redis连接对象
        redis_conn = get_redis_connection('verify_codes')
        # 来发短信之前先尝试性的去redis中获取此手机号60s内是否发送过短信
        send_flag = redis_conn.get('send_flag_%s' % mobile)
        # 判断是否有发送过的标记
        if send_flag:
            return http.JsonResponse({'code': RETCODE.THROTTLINGERR, 'errmsg': '频繁发送短信'})

        # 接收查询参数
        query_dict = request.GET
        image_code_client = query_dict.get('image_code')
        uuid = query_dict.get('uuid')

        # 校验
        if all([image_code_client, uuid]) is False:
            return http.HttpResponseForbidden('缺少必传参数')


        # 获取redis数据库中当前用户图形验证码
        image_code_server_bytes = redis_conn.get(uuid)

        # 删除已经取出的图形验证码,让它只能被用一次
        redis_conn.delete(uuid)

        # 判断redis中图形验证码过期
        if image_code_server_bytes is None:
            return http.JsonResponse({'code': RETCODE.IMAGECODEERR, 'errmsg': '图形验证码已过期'})
        # 将bytes类型转换为字符串类型
        image_code_server = image_code_server_bytes.decode()
        # 用户填写的和redis中的图形验证码是否一致(注意大小问题)
        if image_code_client.lower() != image_code_server.lower():
            return http.JsonResponse({'code': RETCODE.IMAGECODEERR, 'errmsg': '图形验证码填写错误'})

        # 随机生成一个6位数字作为短信验证码
        sms_code = '%06d' % randint(0, 999999)
        logger.info(sms_code)
        # 管道技术
        # 创建管道
        pl = redis_conn.pipeline()
        # 将短信验证码存储到redis 以备后期注册时进行验证
        # redis_conn.setex('sms_%s' % mobile, constants.SMS_CODE_EXPIRE, sms_code)  # 魔法数字
        pl.setex('sms_%s' % mobile, constants.SMS_CODE_EXPIRE, sms_code)  # 魔法数字

        # 向redis存储一个标识,标记此手机号60s内已经发过短信
        # redis_conn.setex('send_flag_%s' % mobile, 60, '1')
        pl.setex('send_flag_%s' % mobile, 60, '1')
        # 执行管道
        pl.execute()

        # 利用容联云平台发短信
        # CCP().send_template_sms('接收短信手机号', ['短信验证码', '提示用户短信验证码多久过期单位分钟'], '模板id')
        # CCP().send_template_sms(mobile, [sms_code, constants.SMS_CODE_EXPIRE // 60], 1)
        send_sms_code.delay(mobile, sms_code)
        # import time
        # time.sleep(5)
        # 响应
        return http.JsonResponse({'code': RETCODE.OK, 'errmsg': 'OK'})
