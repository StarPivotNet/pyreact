# 浏览器验收

浏览器入口为 `python -m pyreact.browser`。它直接运行 Python 组件，复用框架现有 Hooks、树构建、Diff 和布局算法，通过本机 HTTP 接口把布局树送给 DOM 渲染器。游戏入口 `render_app(...)` 和 `PyreactRuntimeScript` 不依赖此后端。

## 常用命令

```bash
# 默认示例，会打开浏览器
python -m pyreact.browser

# 使用现有计数器组件，不自动开窗口
python -m pyreact.browser --app PyreactExampleScript.examples.CounterDemo:CounterDemo --no-open

# 纯色 Slider：受控/非受控、步长、禁用、拖动计数与滚动坐标
python -m pyreact.browser --app pyreact.browser.interaction_demo:InteractionDemo

# 现有动画示例：进入/退出、连续过渡、列表、缓动与延迟
python -m pyreact.browser --app PyreactExampleScript.examples.AnimationDemo:AnimationDemo

# 确定性离线事件与 RPC 场景
python -m pyreact.browser --app pyreact.browser.scenario_demo:ScenarioDemo

# 验收自己的行为包组件和纹理
python -m pyreact.browser --project "D:/YourAddon/behavior_pack" --app YourMod.ui:YourApp --resource-root "D:/YourAddon/resource_pack"

# Python 回归测试，不需要游戏或浏览器
python -m unittest discover -s tests -v

# 前端动画与指针回归测试，需要 Node.js
node --test tests/test_browser_frontend.cjs
```

需要 Python 3.9+，服务和 Python 测试均仅依赖标准库。原有游戏模块继续保持 Python 2 兼容；`pyreact/browser/` 是独立的本地开发工具，不必分发进 AddOn。入口模块如果依赖游戏 SDK，应提取纯 UI 组件或增加自己的预览入口，显式提供测试数据；本工具不伪造 SDK。

被预览的业务代码也需兼容 Python 3。例如 Python 2 的 `data.keys()[0]` 需要改为 `list(data.keys())[0]`；工具不会自动转换业务源码。

## 推荐验收步骤

1. 启动需要验收的组件，检查错误面板和能力提示。
2. 操作按钮、输入框和滚动区域，检查文本、计数、筛选结果等实际变化。
3. 切换画布尺寸，检查布局；工具栏改变的是 Pyreact 的布局视口，不只是浏览器缩放。
4. 导出树快照，保留节点属性、布局坐标和当前状态；也可以用截图记录视觉结果。
5. 修改 Python 后停止并重启服务。重置按钮只重建组件状态，刷新页面会保留当前服务状态。

## 能力边界

| 功能 | 浏览器行为 |
| --- | --- |
| Panel / Label / Image | 显示原布局引擎输出的坐标；Color 转换成 CSS rgba |
| Button / FilledButton / ImageButton | Python 点击回调和三态背景 |
| Input | Python onChange 和受控值；保留焦点、光标及输入过程 |
| Scroll | 浏览器滚动容器；重渲染保留滚动位置 |
| useState / useEffect / useMemo / useCallback / useRef | 复用核心 Hooks；浏览器提交布局并绑定 ref 后执行 effects |
| 控件 ref | 浏览器代理支持 GetGlobalPosition / GetPosition / GetSize / SetPosition / SetSize；卸载时解绑 |
| onTouch / Slider | Pointer Events 映射现有触摸协议；支持捕获、取消、拖出轨道、画布缩放和滚动坐标 |
| Animated | 浏览器本地逐帧播放进入、退出和 animate；退出期间保留不可交互副本，按动画运行标识去重完成回调 |
| 文字 | 按游戏字号比例估算测量，与游戏字体和换行可能不同 |
| 纹理 | 从指定资源包加载；缺失图片显示占位，不内置游戏资源 |
| Item / PaperDoll | 显式占位，不能验收游戏物品、实体和模型渲染 |
| 业务事件 / RPC 场景 | 显式注入 OfflineSession，模拟成功、拒绝、延迟、超时，记录并回放 JSONL；见[离线场景](offline-scenarios.md) |
| 真实游戏事件 / 网络协议 / 服务端 / 引擎 API | 仍由游戏环境验证；离线会话不会自动替换 SDK |

对于普通 UI 布局、状态和交互，浏览器可作为独立验收入口。引擎专属效果仍保留游戏验收，不把浏览器显示结果视为游戏像素级一致性证明。

### 动画与 ref 的具体语义

- 支持 `opacity`、`alpha`、`translateX/Y`、`width/height`、duration、delay 和完成回调。`opacity` 影响整棵子树，`alpha` 作用于当前节点及直属子节点的视觉；Label 跳过尺寸动画。尺寸动画不重新计算 Flex 布局，也不提供列表重排动画。
- 首次只有 `animate` 时直接应用目标；后续目标改变才播放过渡。目标不变、仅修改 duration/delay/easing 不会重播。同次设置 `enter` 与 `animate` 时，animate 中断 enter，被中断的回调不执行。
- 相同 key 的移动保留动画身份；卸载后重挂是新实例。过渡中断从当前视觉值接续，退出副本不可交互，完成后清理。浏览器会执行一次 `exit.onComplete`；当前游戏运行时使用内部清理回调覆盖用户退出回调，二者在这一点上存在差异。
- 内置缓动在浏览器逐帧求值；自定义 Python easing 通过 101 个样点插值近似，不能保证任意曲线的精确一致性。
- ref 是有限的控件代理，支持对象 ref 与 callback ref，以及替换、卸载时解绑。测量返回布局或命令更新后的值，不回传浏览器每帧动画插值，不实现全部原生控件 API。

## HTTP 调试接口

服务器只监听回环地址，拒绝外部 Host 和跨站 Origin。POST 必须使用 `Content-Type: application/json`。接口只调用当前已渲染节点的回调，不接受远程组件导入或代码执行请求。

| 请求 | 请求体 / 响应 |
| --- | --- |
| `GET /api/tree` | 当前 `{app, tree, exits, width, height, revision, warnings}` |
| `GET /api/export` | 下载当前 JSON 布局树快照 |
| `POST /api/event` | `{"id":"从树读取节点 id","event":"click"}` 或 `{"id":"输入节点 id","event":"input","value":"hello"}` |
| `POST /api/resize` | `{"width":960,"height":640}`，保留组件状态 |
| `POST /api/reset` | `{}`，清理 effects 并重新挂载 |
| `GET /assets/textures/...` | 读取配置资源包内的图片，省略扩展名时尝试 `.png` |

树包含 `type`、`props`、`style`、`layout`、`children`，`layout.x/y` 是画布绝对坐标。事件寻址使用稳定实例 `id`；同父级、同类型、同 `key` 的节点移动时保留身份，卸载后重新挂载获得新身份。列表应提供稳定的业务 `key`。回调在 JSON 中仅标记可用，不序列化 Python 函数。按钮三态包含在 `states` 中。错误通过非 2xx 响应和页面错误提示报告，服务终端保留异常堆栈。

触摸请求为 `{"id":"节点 id","event":"touch","value":{"TouchEvent":1,"TouchPosX":100,"TouchPosY":80,"pointerId":1,"sequence":1}}`。事件值与现有组件一致：down=1、move=4、up=0、cancel=3；坐标与布局/ref 在同一空间。网页负责坐标换算、指针捕获以及有序请求。

动画节点的 `animation` 包含 `{runId, phase, from, to, duration, delay, easing}`。网页播放完成后发送 `event="animation_complete"`、`value={"runId":"当前运行 id"}`；已完成或过期标识不会重复执行回调。`exits` 是尚未完成退出动画的子树。动画播放不依赖树轮询的频率。

一个进程内的浏览器标签页共用组件状态和视口，不是多用户部署服务。验收时可用不同端口隔离实例。
