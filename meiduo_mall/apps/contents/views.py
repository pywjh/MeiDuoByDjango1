from django.shortcuts import render
from django.views import View

from goods.models import GoodsCategory, GoodsChannel
from .utils import get_categories
from .models import Content, ContentCategory


class IndexView(View):
    """首页"""

    def get(self, request):

        # # 定义一个字典变量用来保存所有商品类别数据
        # categories = {}
        #
        # # 查询所有频道数据
        # goods_channel_qs = GoodsChannel.objects.order_by('group_id', 'sequence')
        #
        # # for循环来包装商品类别数据
        # for channel_model in goods_channel_qs:
        #
        #     # 获取当前组的组号
        #     group_id = channel_model.group_id
        #     # 让每一组的初始数据结构代码只执行一次
        #     if group_id not in categories:
        #         # 包装每组的初始数据结构
        #         categories[group_id] = {
        #                                     'channels': [],
        #                                     'sub_cats': []
        #                                 }
        #     # 查询出当前频道对应的一级类别
        #     cat1 = channel_model.category
        #     # 给每个一级多定义一个url属性保存它自己的链接
        #     cat1.url = channel_model.url
        #
        #     # 将每一个一级添加到对应组中的channels列表中
        #     categories[group_id]['channels'].append(cat1)
        #
        #     # cat2 = '根据每一个一级类别查询出它对应的所有二级'
        #     # 将当前一级下面的所有二级查询出来
        #     cat2_qs = cat1.subs.all()
        #     # 遍历二级类别查询集,为每一个二级保存它自己的所有三级
        #     for cat2 in cat2_qs:
        #         # 查询出指定二级下的所有三级
        #         cat3_qs = cat2.subs.all()
        #         # 将指定二级下的所有三级保存到二级的sub_cats的临时属性上
        #         cat2.sub_cats = cat3_qs
        #         # 将每一个二级再添加到sub_cats对应的列表中
        #         categories[group_id]['sub_cats'].append(cat2)
        # 包装模板需要渲染的广告数据
        # 定义一个字典用来包装所有广告数据
        contents = {}
        # 查询所有广告类别数据
        content_cat_qs = ContentCategory.objects.all()
        # 遍历广告类别查询集
        for content_cat in content_cat_qs:
            contents[content_cat.key] = content_cat.content_set.filter(status=True).order_by('sequence')


        context = {
            # 商品分类数据
            'categories': get_categories(),
            # 广告数据
            'contents': contents
        }
        return render(request, 'index.html', context)

