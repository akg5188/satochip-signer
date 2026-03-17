# Satochip 多链观察钱包 (Android)

这是一个配合树莓派离线签名器使用的多链观察钱包 Android App。

当前定位是：
- 观察地址，单地址覆盖多条 EVM 链
- 支持 Arbitrum / Base / Optimism / Polygon / BNB Chain
- 查询多链资产余额
- 构造转账请求并生成树莓派静态中转二维码
- 扫描树莓派签名结果并广播交易
- 展示本地活动记录和最近链上代币转账
- 内置 `Hyperliquid` 交易面板
- WalletConnect 连接中心
- 转账联系人管理
- 展示签名结果，供复制使用

## 现在已经支持的链路

### 1. 多链观察钱包转账

1. 添加观察地址
2. 切换目标链并查询余额
3. 构造主币或 ERC20 转账请求
4. App 生成 `tpr1` 静态二维码
5. 树莓派扫描并签名
6. App 扫描树莓派结果二维码
7. 自动广播到对应链

### 2. Hyperliquid / WalletConnect / 离线签名

1. 在内置 `Hyperliquid` 面板中先批准 agent，再直接在 App 内下单和撤单
2. 或扫描外部 WalletConnect 配对码 / 原始请求
3. 请求会自动转成适合树莓派扫描的离线请求
4. App 生成 `tpr1` 静态二维码
5. 树莓派扫描并签名
6. App 扫描树莓派结果二维码
7. 交易自动广播，签名结果自动回传或展示

### 3. 联系人与活动记录

- 常用转账对象可保存为联系人，便于快速填入
- 最近广播记录、WalletConnect 操作、签名结果都会进入活动页
- 当前也会尝试同步最近链上 ERC20 转账活动

### 4. 扫描外部请求二维码

支持：
- 单张请求二维码
- `tp:multiFragment-...` 动态分片二维码

App 会自动拼片、解析请求、展示摘要，然后转成适合树莓派扫描的静态 `tpr1` 二维码。

## 还没做的部分

### WalletConnect

这版已经接入 **WalletConnect v2**，但仍然是围绕“观察钱包 + 树莓派离线签名”来设计的。

这意味着：
- DApp 可以直接把这个 App 当成钱包连接
- 交易 / 消息 / TypedData 会在手机侧转换为适合树莓派扫描的离线请求
- 当前仍以二维码中转和人工确认链路为主，而不是完整热钱包模型

后续如果继续完善，重点会放在：
- 更完整的会话管理
- 更细的链切换与权限提示
- 更完善的历史记录与通知体验

### Google 推送 / FCM

当前这版 **不需要 Google Push / FCM**。

原因：
- 转账和签名流程都是本地二维码中转
- 不依赖后台消息唤醒
- 不依赖远程推送通知

只有在你想做下面这些能力时，才需要再评估是否引入推送：
- App 在后台也能收到会话请求
- 更接近正式手机钱包体验

才需要再评估是否引入推送能力。

## 与树莓派的协议

- 请求格式：离线签名请求，经过 `deflate + base64` 编码成 `tpr1:index/total.crc.chunk`
- 响应格式：离线签名响应，包含：
  - `rawTransaction`
  - 或 `signature`

## 构建

### 1. 配置 Android SDK

创建 `local.properties`：

```properties
sdk.dir=/path/to/Android/Sdk
```

### 2. 构建 APK

```bash
cd wallet
./gradlew assembleDebug
```

输出：

```text
app/build/outputs/apk/debug/app-debug.apk
```

如果你就在这台 Ubuntu 机器上构建，建议直接用项目自带脚本。它会先复制到纯英文路径再编，能避开中文目录下的 Gradle/Android SDK 问题：

```bash
cd /home/ak/zero/tp-satochip-signer-main/wallet
./scripts/build_local_ascii.sh
```

输出：

```text
dist/arbitrum-wallet-debug.apk
```

## 依赖

- Android 8.0+ (API 26)
- 网络权限：查余额、广播交易
- 相机权限：扫描请求二维码和树莓派结果二维码

## 维护文档

如果你后面还要继续修改这个项目，建议直接看：

- [docs/开发维护指南.zh-CN.md](docs/开发维护指南.zh-CN.md)

## 推荐开发顺序

如果你后面继续完善，建议顺序是：

1. 先把这版 QR 中转观察钱包稳定下来
2. 继续完善多链资产、活动和 Hyperliquid 交易体验
3. 最后再考虑是否需要推送 / 后台唤醒
