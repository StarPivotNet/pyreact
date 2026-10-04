# 离线事件与 RPC 场景

`pyreact.browser.scenarios` 是 Python 3.9+ 开发工具。界面显式接收业务端口，端口提供本地事件和 RPC 测试实现；它不导入、替代或伪造网易 SDK，也不会连接真实服务器。

## 运行交互示例

在仓库根目录运行：

```powershell
python -m pyreact.browser --app pyreact.browser.scenario_demo:ScenarioDemo
```

`ScenarioDemo` 使用真实 `@Component`、`useState`、`useEffect`。按钮可以注入库存事件、模拟 RPC 成功/拒绝/500 ms 延迟/1000 ms 超时、推进时间和回放已录制消息。等待不会自动计时，点击“推进时间 +500 ms”才会触发到期响应。关闭组件会注销事件，根示例还会关闭自己的会话。

`ScenarioPanel(port=...)` 演示依赖注入方式。业务组件依赖它实际需要的 `subscribe` / `request` 接口；开发入口注入 `OfflineSession`，游戏入口由项目自己的适配器连接实际事件和 RPC。不要在业务 UI 中直接创建开发会话或全局替换游戏模块。

## 事件和本地 RPC

```python
from pyreact.browser.scenarios import OfflineSession

port = OfflineSession()
unsubscribe = port.subscribe('inventory.changed', print)
port.emit('inventory.changed', {'stock': 8})
unsubscribe()
unsubscribe()  # 注销可重复调用。

port.register_rpc('order.quote', lambda data: {'price': data['quantity'] * 3})
request_id = port.request('order.quote', {'quantity': 2}, print, timeout_ms=1000)
port.advance(0)  # 立即响应也在显式推进时交付。
port.close()
```

同一事件名与同一回调只注册一次；重复注册返回的任一注销函数会移除该注册。旧注销函数不会误删注销后重新建立的注册。每个监听器收到独立的 JSON 数据副本。监听器异常和本地 RPC handler 异常直接暴露，不吞异常。

`register_rpc(method, handler)` 为方法提供同步本地实现。处理器在 `request` 调用时运行，响应回调在 `advance` 时运行。未知方法且没有排队响应时抛出 `LookupError`。处理器应是本地纯逻辑，不能将它当成异步或真实网络传输。

`request(method, payload, callback, timeout_ms=1000)` 返回本会话内递增的请求 ID。回调接收字典：

```python
{
    'id': 1,
    'method': 'order.quote',
    'status': 'ok',  # ok / error / timeout
    'value': {'price': 6},
    'error': None,
}
```

错误和超时响应的 `value` 为 `None`，`error` 为字符串。`cancel(request_id)` 取消挂起请求并返回是否取消成功，不调用结果回调，适合组件卸载清理。取消会写入 `cancelled` 记录。`close()` 注销所有事件、取消所有请求、清理队列；关闭可重复调用，关闭后不能再注入事件或推进时间。

## 可控响应与时间

```python
port.queue_response('order.submit', value={'accepted': True})
port.queue_response('order.submit', error='库存不足')
port.queue_response('order.submit', value={'accepted': True}, delay_ms=500)
port.queue_response('order.submit', drop=True)
```

每次 `request('order.submit', ...)` 消耗一条该方法的排队响应；队列耗尽后回退到已注册 handler。`drop=True` 表示不产生服务器响应，只等待请求超时。可用 `delay_ms` 大于 `timeout_ms` 模拟迟到响应，超时后的响应会被丢弃，不会再次回调。

- `advance(500)` 推进虚拟时钟 500 ms；同一时间点按排队顺序执行。
- 响应与超时恰好同一时间时，响应优先。
- 延迟、超时和推进量只接受非负整数毫秒。
- 没有后台线程、真实等待或自动时钟。所有操作应串行执行，浏览器按钮在现有运行时锁内执行。
- 回调可发起后续请求；不允许回调递归调用 `advance`。单次推进最多处理 10000 个定时项，防止无限即时请求循环。
- 负载只接受 JSON 值，拒绝非有限数、元组、对象和非字符串字典键。

## JSONL 录制、校验和回放

每个会话自动记录 `event`、`request`、`result`、`clock`，包含 `version: 1` 与虚拟 `time_ms`。这里只记录本业务边界收到或生成的数据，没有游戏引擎抓包或真实 RPC 录制功能。

```python
from pathlib import Path
from pyreact.browser.scenario_trace import loads_trace, replay_trace

Path('scenario.jsonl').write_text(port.to_jsonl(), encoding='utf-8')
records = loads_trace(Path('scenario.jsonl').read_text(encoding='utf-8'))

def event_record(row):
    print(row['time_ms'], row['name'], row['payload'])

def result_record(row):
    print(row['time_ms'], row['method'], row['status'], row['value'])

last_time = replay_trace(records, event_record, result_record)
```

`replay_trace` 先完整校验，再按记录顺序同步调用两个回调，回调接收包含时间戳的完整记录。可以把事件回调接到业务状态更新函数，把结果回调接到原有 RPC 结果处理函数。它不等待时间、不执行记录里的请求、不调用 handler、不重建游戏服务端，也不把记录中的字符串当代码执行。请求、时钟和取消记录只参与校验；已取消的请求与原运行一致，不触发结果回调。

这种回放用于复现消息驱动的状态更新。只有副作用确定、初始状态一致且使用相同业务处理逻辑时，才能比较最终状态；依赖随机数、实际时钟或外部 IO 的逻辑需要自行注入确定性实现。存在未完成请求的录制允许导出，但回放不会自动补出结果。

读取限制为 UTF-8 文本 4 MiB、10000 条记录和 32 层 JSON 嵌套。校验会拒绝未知字段/类型/版本、时间倒退、重复请求 ID、结果和请求不匹配及重复完成。`records` 返回副本。长时间测试可为每个场景创建独立会话，避免内存记录无限积累。录制保存了业务负载，分享前应自行移除账户令牌和用户数据。

## 验证范围

可以离线验证消息处理、组件状态、成功/拒绝/超时提示、重试时序和订阅生命周期。真实 RPC 编解码、客户端与服务端权限、多人并发、网络断线重连、引擎 API 及物品/实体渲染仍需游戏环境集成测试。

```powershell
python -m unittest discover -s tests -p "test_browser_scenarios.py"
```
