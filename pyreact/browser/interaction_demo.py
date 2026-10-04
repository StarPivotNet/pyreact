# -*- coding: utf-8 -*-
"""Texture-free Slider acceptance fixture using the public component API."""
from pyreact import (AlignItems, Color, Colors, Component, FilledButton, Image,
                     JustifyContent, Label, Panel, Position, Scroll, Slider,
                     Style, useState)


def _skin(color):
    return lambda state: Image(color=Color(color))


def _slider(**props):
    return Slider(
        style=Style(width="100%", height=40, marginBottom=14),
        trackBuilder=_skin(0xFF344760),
        progressBuilder=_skin(0xFF4BA8FF),
        thumbBuilder=_skin(0xFFFFFFFF),
        borderBuilder=_skin(0x00000000),
        **props
    )


def _label(text, muted=False):
    return Label(content=text, color=Color(0xFF9DB5D4) if muted else Colors.white,
                 style=Style(width="100%", height=32))


@Component
def InteractionDemo():
    value, set_value = useState(30)
    free_value, set_free_value = useState(0)
    starts, set_starts = useState(0)
    ends, set_ends = useState(0)
    disabled, set_disabled = useState(True)
    # Keep all Slider instances mounted: nested components share the root fiber.
    return Panel(style=Style(width="100%", height="100%", padding=24), children=[
        Image(color=Color(0xFF111B2B), style=Style(
            position=Position.absolute, left=0, top=0, width="100%", height="100%")),
        _label(u"离线交互 · 真实 Slider"),
        _label(u"拖出轨道、缩放画布、滚动后继续操作。", True),
        Scroll(key="sliders", style=Style(width="100%", flex=1), children=[
            _label(u"受控值：%s · 步长 10" % value),
            _slider(value=value, step=10, onChange=set_value,
                    onDragStart=lambda _: set_starts(lambda old: old + 1),
                    onDragEnd=lambda _: set_ends(lambda old: old + 1)),
            _label(u"拖动开始：%s · 结束：%s" % (starts, ends), True),
            _label(u"非受控值：%s · 范围 -50 至 50" % free_value),
            _slider(defaultValue=0, min=-50, max=50, step=5, onChange=set_free_value),
            _label(u"第三条：%s" % (u"已禁用" if disabled else u"可拖动")),
            _slider(defaultValue=60, disabled=disabled),
            FilledButton(default=Color(0xFF2879EB), hover=Color(0xFF418CFA),
                         pressed=Color(0xFF1C60C0), onClick=lambda: set_disabled(not disabled),
                         style=Style(width=160, height=40, alignItems=AlignItems.center,
                                     justifyContent=JustifyContent.center),
                         children=Label(content=u"切换禁用状态", color=Colors.white)),
            Panel(style=Style(height=160)),
            _label(u"滚动后的滑条 · 用于检查坐标换算", True),
            _slider(defaultValue=25, step=5),
        ]),
    ])
