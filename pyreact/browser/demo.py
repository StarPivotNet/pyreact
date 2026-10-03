# -*- coding: utf-8 -*-
"""Small real component used to verify browser input, state and scrolling."""
from pyreact import (Component, Panel, Image, Label, Input, Scroll, FilledButton,
                     Style, Color, Colors, useState, FlexDirection, AlignItems,
                     JustifyContent, Position)


@Component
def BrowserDemo():
    count, set_count = useState(0)
    query, set_query = useState("")
    selected, set_selected = useState(u"尚未选择")
    items = [u"组件与 Hooks", u"原生 Flex 布局", u"按钮三态", u"受控输入",
             u"列表筛选", u"滚动容器", u"视口尺寸", u"状态重置", u"树快照导出"]
    visible = [item for item in items if query.lower() in item.lower()]
    return Panel(style=Style(width="100%", height="100%", padding=24), children=[
        Image(style=Style(position=Position.absolute, left=0, top=0,
                          width="100%", height="100%"), color=Color(0xFF111B2B)),
        Label(content=u"Python 组件 · 浏览器验收", color=Colors.white,
              fontSize=15, style=Style(width="100%", height=36)),
        Label(content=u"点击、输入和滚动，运行真实组件逻辑。",
              color=Color(0xFF94A8C6), style=Style(width="100%", height=28, marginBottom=16)),
        Panel(style=Style(flexDirection=FlexDirection.row, height=44,
                          alignItems=AlignItems.center, marginBottom=16), children=[
            FilledButton(key="increment", default=Color(0xFF2879EB),
                         hover=Color(0xFF418CFA), pressed=Color(0xFF1C60C0),
                         style=Style(width=128, height=40, alignItems=AlignItems.center,
                                     justifyContent=JustifyContent.center),
                         onClick=lambda: set_count(lambda value: value + 1),
                         children=Label(content=u"点击 +1", color=Colors.white)),
            Label(key="count", content=u"计数：%s" % count, color=Colors.white,
                  style=Style(marginLeft=18)),
        ]),
        Input(key="search", value=query, onChange=set_query, placeholder=u"输入关键词筛选列表",
              style=Style(width="100%", height=38, marginBottom=12)),
        Label(content=u"%s 项 · 已选：%s" % (len(visible), selected),
              color=Color(0xFF8AC7FF), style=Style(height=28)),
        Scroll(key="list", style=Style(width="100%", flex=1), children=[
            FilledButton(key=item, default=Color(0xFF1D2E46), hover=Color(0xFF294362),
                         pressed=Color(0xFF34597E), onClick=lambda value=item: set_selected(value),
                         style=Style(width="100%", height=48, marginBottom=8, padding=12),
                         children=Label(content=item, color=Colors.white)) for item in visible
        ]),
    ])
