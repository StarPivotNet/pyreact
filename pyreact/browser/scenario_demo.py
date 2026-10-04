# -*- coding: utf-8 -*-
"""An actual component showing explicitly injected offline application ports."""

from pyreact import (Component, Panel, Label, Image, Scroll, FilledButton, Style, Color,
                     Colors, Position, useState, useMemo, useEffect)
from .scenarios import OfflineSession
from .scenario_trace import loads_trace, replay_trace


def _button(key, title, callback):
    return FilledButton(
        key=key, default=Color(0xFF244266), hover=Color(0xFF315886),
        pressed=Color(0xFF18334F), onClick=callback,
        style=Style(width='100%', height=36, marginBottom=6, padding=8),
        children=Label(content=title, color=Colors.white))


@Component
def ScenarioPanel(port):
    stock, set_stock = useState(0)
    status, set_status = useState(u'就绪')
    clock, set_clock = useState(0)
    replay_status, set_replay_status = useState(u'尚未回放')
    pending = useMemo(set, [])

    def receive_event(payload):
        set_stock(payload['stock'])

    def receive_result(result):
        pending.discard(result['id'])
        if result['status'] == 'ok':
            set_status(u'成功：%s' % result['value']['message'])
        else:
            set_status(u'%s：%s' % (result['status'], result['error']))

    def listen():
        unsubscribe = port.subscribe('inventory.changed', receive_event)

        def cleanup():
            unsubscribe()
            for request_id in list(pending):
                port.cancel(request_id)
            pending.clear()
        return cleanup
    useEffect(listen, [port])

    def request(mode):
        settings = {
            'ok': {'value': {'message': u'订单已接受'}},
            'reject': {'error': u'库存不足'},
            'delay': {'value': {'message': u'延迟订单已接受'}, 'delay_ms': 500},
            'timeout': {'drop': True},
        }
        port.queue_response('order.submit', **settings[mode])
        set_status(u'等待响应（%s）' % mode)
        request_id = port.request('order.submit', {'quantity': 1}, receive_result,
                                  timeout_ms=1000)
        pending.add(request_id)
        port.advance(0)
        set_clock(port.now_ms)

    def advance():
        port.advance(500)
        set_clock(port.now_ms)

    def replay():
        records = loads_trace(port.to_jsonl())
        replay_trace(records, lambda row: receive_event(row['payload']), receive_result)
        set_replay_status(u'已回放 %s 条记录；没有执行真实 RPC' % len(records))

    controls = [
        Label(content=u'虚拟时间：%s ms · 库存：%s' % (clock, stock),
              color=Color(0xFF8AC7FF), style=Style(height=30)),
        Label(content=status, color=Colors.white, style=Style(height=34)),
        _button('event', u'注入库存事件 +1',
                lambda: port.emit('inventory.changed', {'stock': stock + 1})),
        _button('success', u'RPC 成功', lambda: request('ok')),
        _button('reject', u'RPC 拒绝', lambda: request('reject')),
        _button('delay', u'RPC 延迟 500 ms', lambda: request('delay')),
        _button('timeout', u'RPC 超时 1000 ms', lambda: request('timeout')),
        _button('advance', u'推进时间 +500 ms', advance),
        _button('replay', u'回放已录制消息', replay),
        Label(content=replay_status, color=Color(0xFF94A8C6), style=Style(height=32)),
        Label(content=u'业务边界模拟；真实协议、权限和引擎行为需在游戏中验证。',
              color=Color(0xFF94A8C6), style=Style(width='100%', height=40)),
    ]
    return Panel(style=Style(width='100%', height='100%', padding=20), children=[
        Image(style=Style(position=Position.absolute, left=0, top=0,
                          width='100%', height='100%'), color=Color(0xFF111B2B)),
        Label(content=u'离线事件 / RPC 场景', color=Colors.white, fontSize=16,
              style=Style(height=34)),
        Scroll(style=Style(width='100%', flex=1), children=controls),
    ])


@Component
def ScenarioDemo():
    port = useMemo(OfflineSession, [])
    useEffect(lambda: port.close, [port])
    return ScenarioPanel(port=port)
