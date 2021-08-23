from django.shortcuts import render
from django.views import View
from django import http
from django.core.cache import cache

from .models import Area
from meiduo_mall.utils.response_code import RETCODE


class AreasView(View):
    """省市区数据查询"""

    def get(self, request):

        # 获取查询参数area_id
        area_id = request.GET.get('area_id')
        # 判断是否有area_id
        # 如果前端没有传area_id,说明它想查所有省
        if area_id is None:
            # 查询所有省数据
            # 先尝试的去从缓存中读写所有省数据
            province_list = cache.get('province_list')
            if province_list is None:  # 说明缓存中没有获取到所有省数据
                province_qs = Area.objects.filter(parent=None)
                province_list = []  # 此列表用来装每一个省的字典
                # 遍历查询集,将查询集中的模型转成字典并添加到列表中
                for province_model in province_qs:
                    province_list.append({
                        'id': province_model.id,
                        'name': province_model.name
                    })
                # 设置缓存数据
                cache.set('province_list', province_list, 3600)

            return http.JsonResponse({'code': RETCODE.OK, 'errmsg': 'Ok', 'province_list': province_list})


        else:
            # 如果前端传了area_id,说明它想查指定区域的下级所有行政区
            # 先尝试去从缓存中读写数据
            sub_data = cache.get('sub_%s' % area_id)
            if sub_data is None:
                try:

                    # 查询出指定id的行政区
                    parent_model = Area.objects.get(id=area_id)
                    # 获取指定行政区的下级所有行政区
                    sub_qs = parent_model.subs.all()

                    # 将sub_qs查询集中的模型转换成字典
                    sub_list = []  # 包装指定area_id的所有下级行政区字典
                    for sub in sub_qs:
                        sub_list.append({
                            'id': sub.id,
                            'name': sub.name
                        })
                    # 包装响应给前端的数据
                    sub_data = {
                        'id': parent_model.id,
                        'name': parent_model.name,
                        'subs': sub_list
                    }
                    # 缓存数据
                    cache.set('sub_%s' % area_id, sub_data, 3600)

                except Area.DoesNotExist:
                    return http.HttpResponseForbidden('area_id不存在')
            # 响应数据
            return http.JsonResponse({'code': RETCODE.OK, 'errmsg': 'OK', 'sub_data': sub_data})
