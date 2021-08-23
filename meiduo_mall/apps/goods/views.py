from django.shortcuts import render
from django.utils import timezone
from django.views import View
from django import http
from django.core.paginator import Paginator, EmptyPage

from contents.utils import get_categories
from .models import GoodsCategory, SKU, GoodsVisitCount
from .utils import get_breadcrumb
from meiduo_mall.utils.response_code import RETCODE

class ListView(View):
    """商品列表界面"""

    def get(self, request, category_id, page_num):

        # 校验category_id是否真实有效
        try:
            cat3 = GoodsCategory.objects.get(id=category_id)
        except GoodsCategory.DoesNotExist:
            return http.HttpResponseForbidden('category_id不存在')

        # 包装面包屑数据

        # cat1 = cat3.parent.parent
        # cat1.url = cat1.goodschannel_set.all()[0].url
        # breadcrumb = {
        #     'cat1': cat1,
        #     'cat2': cat3.parent,
        #     'cat3': cat3
        # }
        # 获取sort查询参数的值
        sort = request.GET.get('sort', 'default')
        if sort == 'price':  # 以价格排序
            sort_field = '-price'
        elif sort == 'hot':
            sort_field = '-sales'
        else:
            sort = 'default'
            sort_field = '-create_time'


        # 查询出指定三级类型下的所有要展示的sku商品
        sku_qs = cat3.sku_set.filter(is_launched=True).order_by(sort_field)
        # total_count = sku_qs.count()
        # page = 5  # 每页显示5条
        # page_num = int(page_num)
        # total_page = total_count // page + ((total_count % page) and 1)
        # page_skus = sku_qs[(page_num - 1) * page: page_num * page]
        # 创建分页器 (要分页的所有数据, 每页显示多少条数据)
        paginator = Paginator(sku_qs, 5)
        total_page = paginator.num_pages  # 获取总页数
        try:
            page_skus = paginator.page(page_num)  # 获取指定页的数据
        except EmptyPage:
            return http.HttpResponseForbidden('没有指定页')


        context = {

            'categories': get_categories(),  # 商品分类数据
            'breadcrumb': get_breadcrumb(cat3),   # 面包屑导航数据
            'category': cat3,  # 三级类别
            'page_skus': page_skus,   # 指定页中所有sku商品数据
            'page_num': page_num,  # 当前显示第几页
            'total_page': total_page,  # 总页数
            'sort': sort,  # 当前是按照什么规则排序
        }
        return render(request, 'list.html', context)


class HotGoodsView(View):
    """热销排行"""
    def get(self, request, category_id):

        # 校验
        try:
            cat3 = GoodsCategory.objects.get(id=category_id)
        except GoodsCategory.DoesNotExist:
            return http.HttpResponseForbidden('category_id不存在')

        # 查询当前三级类型下的所有商品并以销量进行降序排序,再截取前两个
        sku_qs = cat3.sku_set.order_by('-sales')[:2]

        sku_list = []  # 用来将每一个sku字典
        # 模型转字典
        for sku in sku_qs:
            sku_list.append(
                {
                    'id': sku.id,
                    'name': sku.name,
                    'price': sku.price,
                    'default_image_url': sku.default_image.url
                }
            )

        # 响应
        return http.JsonResponse({'code': RETCODE.OK, 'errmsg': 'OK', 'hot_skus': sku_list})




class DetailView(View):
    """商品详情界面"""

    def get(self, request, sku_id):

        try:
            sku = SKU.objects.get(id=sku_id)
        except SKU.DoesNotExist:
            return render(request, '404.html')

        category = sku.category  # 获取当前sku所对应的三级分类

        # 查询当前sku所对应的spu
        spu = sku.spu

        """1.准备当前商品的规格选项列表 [8, 11]"""
        # 获取出当前正显示的sku商品的规格选项id列表
        current_sku_spec_qs = sku.specs.order_by('spec_id')
        current_sku_option_ids = []  # [8, 11]
        for current_sku_spec in current_sku_spec_qs:
            current_sku_option_ids.append(current_sku_spec.option_id)

        """2.构造规格选择仓库
        {(8, 11): 3, (8, 12): 4, (9, 11): 5, (9, 12): 6, (10, 11): 7, (10, 12): 8}
        """
        # 构造规格选择仓库
        temp_sku_qs = spu.sku_set.all()  # 获取当前spu下的所有sku
        # 选项仓库大字典
        spec_sku_map = {}  # {(8, 11): 3, (8, 12): 4, (9, 11): 5, (9, 12): 6, (10, 11): 7, (10, 12): 8}
        for temp_sku in temp_sku_qs:
            # 查询每一个sku的规格数据
            temp_spec_qs = temp_sku.specs.order_by('spec_id')
            temp_sku_option_ids = []  # 用来包装每个sku的选项值
            for temp_spec in temp_spec_qs:
                temp_sku_option_ids.append(temp_spec.option_id)
            spec_sku_map[tuple(temp_sku_option_ids)] = temp_sku.id

        """3.组合 并找到sku_id 绑定"""
        spu_spec_qs = spu.specs.order_by('id')  # 获取当前spu中的所有规格

        for index, spec in enumerate(spu_spec_qs):  # 遍历当前所有的规格
            spec_option_qs = spec.options.all()  # 获取当前规格中的所有选项
            temp_option_ids = current_sku_option_ids[:]  # 复制一个新的当前显示商品的规格选项列表
            for option in spec_option_qs:  # 遍历当前规格下的所有选项
                temp_option_ids[index] = option.id  # [8, 12]
                option.sku_id = spec_sku_map.get(tuple(temp_option_ids))  # 给每个选项对象绑定下他sku_id属性

            spec.spec_options = spec_option_qs  # 把规格下的所有选项绑定到规格对象的spec_options属性上

        context = {
            'categories': get_categories(),  # 商品分类
            'breadcrumb': get_breadcrumb(category),  # 面包屑导航
            'sku': sku,  # 当前要显示的sku模型对象
            'category': category,  # 当前的显示sku所属的三级类别
            'spu': spu,  # sku所属的spu
            'spec_qs': spu_spec_qs,  # 当前商品的所有规格数据
        }
        return render(request, 'detail.html', context)


class VisitCountView(View):
    """统计商品类别每日访问量"""

    def post(self, request, category_id):

        # 校验
        try:
            category = GoodsCategory.objects.get(id=category_id)
        except GoodsCategory.DoesNotExist:
            return http.HttpResponseForbidden('category_id不存在')

        date = timezone.now()  # 获取当前的时期时间对象
        try:
            # 查询当前类别今日是否访问过
            # 如果今日已经访问过就累加它的count
            visit_model = GoodsVisitCount.objects.get(category=category, date=date)
        except GoodsVisitCount.DoesNotExist:
            # 如果今日没有访问过就新增一条访问记录
            visit_model = GoodsVisitCount(
                category=category
            )
        # 无论是新创建的记录还是之前已存在都要为count 累加
        visit_model.count += 1
        visit_model.save()

        # 响应
        return http.JsonResponse({'code': RETCODE.OK, 'errmsg': 'OK'})

