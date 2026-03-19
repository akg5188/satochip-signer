# 3D 打印外壳辅助文件

这里放的是给当前硬件做 3D 打印外壳时的辅助文件。

当前建议路线是：

1. 主机部分先直接打印现成 `Open Pill`
2. 再单独打印顶部读卡器托盘

相关文档：

- [../docs/3D打印外壳改造方案.zh-CN.md](../docs/3D打印外壳改造方案.zh-CN.md)

当前文件：

- `card_reader_tray_template.scad`
  一个参数化读卡器托盘草模

使用方式：

1. 先量白色读卡器的长宽厚
2. 打开 `card_reader_tray_template.scad`
3. 修改顶部参数区
4. 导出 STL
5. 先打印测试件，再打印正式件
