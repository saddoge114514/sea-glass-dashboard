/* 大屏配置 —— 改这里就够了，不用动 dash.html
 *
 * 都是可选项：删掉某个键就用 dash.html 里的默认值。
 * 改完刷新页面即可，health.json 和采集器不受影响。
 */
window.DASH_CONFIG = {
  // 浏览器页签标题 + 页面大标题
  title: "服务器状态大屏",

  // 自动刷新间隔（毫秒）。采集器每 2 分钟跑一次，这里 30 秒是「读文件」的频率
  refreshMs: 30000,

  // 页脚：footer 后面会自动拼上「页面每 N 秒自动刷新」，再拼 links
  footer: "数据来自同目录的 <code>health.json</code>，由服务器上的采集器定时生成。",
  links: [
    { label: "立即刷新", href: "javascript:location.reload()" },
    { label: "管理后台", href: "/" },
    { label: "退出登录", href: "/logout" }
  ],

  // 立绘三件套：主立绘 / 小头像 / 背景那只。
  // 默认是 assets/ 里的鲸鱼娘（第三方同人图，CC BY-NC-SA 4.0，见 assets/LICENSE-art.md）。
  // 不想带第三方图：三个值都改成 assets/mascot.svg 与 assets/mascot-head.svg。
  assets: {
    mascot: "assets/mascot.webp",
    head: "assets/mascot-head.webp",
    deep: "assets/mascot.webp"
  },

  // 底部署名 / 素材授权说明。留空则不显示这一块。
  // 用了别人的立绘就必须在这里写清作者与协议（默认这颗就是 CC BY-NC-SA 4.0）。
  credit: '吉祥物为 DeepSeek「鲸鱼娘」同人形象 · 角色原案 上善无形（OC「溟月」）·' +
          ' DeepSeek 元素二创 ZipZipPipe · 修复 QYQCAMIAO · 素材仓库 ' +
          '<a href="https://github.com/fornarwhal/deepseek-whale-girl-icon" target="_blank" rel="noopener">' +
          'fornarwhal/deepseek-whale-girl-icon</a> · 授权 CC BY-NC-SA 4.0',

  // 卡片标题与右上角小标签
  labels: {
    containers: "容器",
    containersTag: "docker",
    watchdog: "看门狗",
    watchdogTag: "watchdog",
    host: "主机",
    hostTag: "/proc",
    backup: "自动备份",
    mcp: "联网服务",
    mcpTag: "MCP",
    probes: "探活",
    probesTag: "probes",
    data: "数据",
    dataTag: "data/",
    events: "最近事件",
    eventsTag: "events.log"
  },

  // 看板娘说的话。warn / bad 后面会自动接上具体原因。
  mood: {
    ok: "一切正常～",
    warn: "有点小情况",
    bad: "出事了"
  }
};
