# -*- coding: utf-8 -*-
"""Interactive Item gallery backed by locally installed game resources."""
from pyreact import (Component, Panel, Image, Label, Item, Scroll, FilledButton,
                     Style, Color, Colors, useState, FlexDirection, FlexWrap,
                     AlignItems, JustifyContent, Position)


@Component
def ItemDemo():
    enchanted, set_enchanted = useState(False)
    selected, set_selected = useState('minecraft:diamond_sword')
    entries = [('diamond_sword', u'钻石剑'), ('apple', u'苹果'), ('diamond', u'钻石'),
               ('bow', u'弓'), ('iron_pickaxe', u'铁镐'), ('golden_apple', u'金苹果'),
               ('stone', u'石头'), ('dirt', u'泥土'), ('cobblestone', u'圆石'),
               ('oak_log', u'橡木原木'), ('glass', u'玻璃'), ('bookshelf', u'书架')]
    return Panel(style=Style(width='100%', height='100%', padding=20), children=[
        Image(style=Style(position=Position.absolute, left=0, top=0,
                          width='100%', height='100%'), color=Color(0xFF152134)),
        Label(content=u'游戏物品 · 本机资源预览', color=Colors.white,
              fontSize=15, style=Style(height=34)),
        Label(content=u'点击物品切换选中预览', color=Color(0xFF9FB5D4),
              style=Style(height=28)),
        Panel(style=Style(flexDirection=FlexDirection.row, height=76,
                          alignItems=AlignItems.center, marginBottom=12), children=[
            Item(key='selected', identifier=selected, enchant=enchanted,
                 style=Style(width=64, height=64, marginRight=12)),
            FilledButton(default=Color(0xFF315888), hover=Color(0xFF4270A6),
                         pressed=Color(0xFF26466E), onClick=lambda: set_enchanted(not enchanted),
                         style=Style(width=150, height=36, alignItems=AlignItems.center,
                                     justifyContent=JustifyContent.center),
                         children=Label(content=u'附魔预览：%s' % (u'开' if enchanted else u'关'),
                                        color=Colors.white)),
        ]),
        Scroll(style=Style(width='100%', flex=1), children=Panel(
            style=Style(width='100%', flexDirection=FlexDirection.row, flexWrap=FlexWrap.wrap),
            children=[FilledButton(
                key=identifier, default=Color(0xFF20344F), hover=Color(0xFF304F74),
                pressed=Color(0xFF42658B),
                onClick=lambda name=identifier: set_selected('minecraft:' + name),
                style=Style(width=120, height=122, marginRight=10, marginBottom=10,
                            padding=10, alignItems=AlignItems.center),
                children=[Item(identifier='minecraft:' + identifier,
                               style=Style(width=72, height=72, marginBottom=8)),
                          Label(content=title, color=Colors.white)]
            ) for identifier, title in entries])),
    ])
