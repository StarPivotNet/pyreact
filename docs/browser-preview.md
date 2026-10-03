# 浏览器验收

浏览器入口为 `python -m pyreact.browser`。它直接运行 Python 组件，复用框架现有 Hooks、树构建、Diff 和布局算法，通过本机 HTTP 接口把布局树送给 DOM 渲染器。游戏入口 `render_app(...)` 和 `PyreactRuntimeScript` 不依赖此后端。

## 常用命令

```bash
# 默认示例，会打开浏览器
python -m pyreact.browser

# 使用现有计数器组件，不自动开窗口
python -m pyreact.browser --app PyreactExampleScript.examples.CounterDemo:CounterDemo --no-open

# 验收自己的行为包组件和纹理
python -m pyreact.browser --project "D:/YourAddon/behavior_pack" --app YourMod.ui:YourApp --resource-root "D:/YourAddon/resource_pack"

# Python 回归测试，不需要游戏或浏览器
python -m unittest discover -s tests -v
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
| useState / useEffect / useMemo / useCallback / useRef | 复用现有核心语义；原生控件 ref 不绑定游戏对象 |
| 文字 | 按游戏字号比例估算测量，与游戏字体和换行可能不同 |
| 纹理 | 从指定资源包加载；缺失图片显示占位，不内置游戏资源 |
| Item / PaperDoll | 显式占位，不能验收游戏物品、实体和模型渲染 |
| Animated / onTouch / 原生控件 ref | 提示未支持，不作为动画、触摸或 Slider 拖动验收结果 |
| 游戏事件 / RPC / 服务端 / 引擎 API | 仍由游戏环境验证 |

对于普通 UI 布局、状态和交互，浏览器可作为独立验收入口。引擎专属效果仍保留游戏验收，不把浏览器显示结果视为游戏像素级一致性证明。

## HTTP 调试接口

服务器只监听回环地址，拒绝外部 Host 和跨站 Origin。POST 必须使用 `Content-Type: application/json`。接口只调用当前已渲染节点的回调，不接受远程组件导入或代码执行请求。

| 请求 | 请求体 / 响应 |
| --- | --- |
| `GET /api/tree` | 当前 `{app, tree, width, height, revision, warnings}` |
| `GET /api/export` | 下载当前 JSON 布局树快照 |
| `POST /api/event` | `{"id":"从树读取节点 id","event":"click"}` 或 `{"id":"输入节点 id","event":"input","value":"hello"}` |
| `POST /api/resize` | `{"width":960,"height":640}`，保留组件状态 |
| `POST /api/reset` | `{}`，清理 effects 并重新挂载 |
| `GET /assets/textures/...` | 读取配置资源包内的图片，省略扩展名时尝试 `.png` |

树包含 `type`、`props`、`style`、`layout`、`children`，`layout.x/y` 是画布绝对坐标。事件寻址使用完整节点路径 `id`；回调在 JSON 中仅标记可用，不序列化 Python 函数。按钮三态包含在 `states` 中。错误通过非 2xx 响应和页面错误提示报告，服务终端保留异常堆栈。

一个进程内的浏览器标签页共用组件状态和视口，不是多用户部署服务。验收时可用不同端口隔离实例。
