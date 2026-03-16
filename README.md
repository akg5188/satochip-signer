# Arbitrum One 观察钱包 (Android)

这是一个配合树莓派离线签名器使用的 Arbitrum One 观察钱包 Android App。

当前定位是：
- 观察地址
- 查询 ETH / USDC / USDC.e / USDT 余额
- 构造转账请求并生成树莓派静态中转二维码
- 扫描树莓派签名结果并广播交易
- 生成 `personal_sign` / `signTypedDataV4` 请求，交给树莓派签名
- 展示签名结果，供复制使用

## 现在已经支持的链路

### 1. 观察钱包转账

1. 添加 Arbitrum One 观察地址
2. 查询余额
3. 构造 ETH / USDC / USDT / USDC.e 转账请求
4. App 生成 `tpr1` 静态二维码
5. 树莓派扫描并签名
6. App 扫描树莓派结果二维码
7. 自动广播到 Arbitrum One

### 2. 消息 / TypedData 签名

1. 选择当前观察地址
2. 输入普通消息，生成 `personal_sign` 请求
3. 或粘贴 `signTypedDataV4` 的 JSON，生成 TypedData 请求
4. App 生成 `tpr1` 静态二维码
5. 树莓派扫描并签名
6. App 扫描树莓派结果二维码
7. 显示签名字符串，供复制给上游应用

### 3. 扫描外部 DApp 请求二维码

支持：
- 单张请求二维码
- `tp:multiFragment-...` 动态分片二维码

App 会自动拼片、解析请求、展示摘要，然后转成适合树莓派扫描的静态 `tpr1` 二维码。

## 还没做的部分

### WalletConnect

这版 **还没有接 WalletConnect v2**。

这意味着：
- 现在可以做“二维码中转签名”
- 也可以做“手动输入 personal_sign / signTypedDataV4”
- 但 **还不能让外部 DApp 直接把这个 App 当成钱包连接**

如果你要“像正常 Web3 钱包一样给外部 DApp 直连签名”，下一阶段就要接 WalletConnect。

### Google 推送 / FCM

当前这版 **不需要 Google Push / FCM**。

原因：
- 转账和签名流程都是本地二维码中转
- 不依赖后台消息唤醒
- 不依赖远程推送通知

只有在后面接 WalletConnect，并且你想做：
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
cd arbitrum-wallet-android
./gradlew assembleDebug
```

输出：

```text
app/build/outputs/apk/debug/app-debug.apk
```

如果你就在这台 Ubuntu 机器上构建，建议直接用项目自带脚本。它会先复制到纯英文路径再编，能避开中文目录下的 Gradle/Android SDK 问题：

```bash
cd /home/ak/树莓派/arbitrum-wallet-android
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
2. 再接 WalletConnect v2 会话
3. 最后再考虑是否需要推送 / 后台唤醒
