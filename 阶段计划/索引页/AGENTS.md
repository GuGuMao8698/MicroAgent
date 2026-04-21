- 本目录下的阶段索引文件用于标记“对应能力的实际代码状态”；状态标识仅使用`Implemented in Code`、`Partially Implemented in Code`、`Not Implemented in Code`。
- 默认优先继续读取索引中状态标识为`Partially Implemented in Code`的条目；该状态表示“当前活动条目”；代码可能尚未开始，也可能已部分落地。仅在需要核对已落地行为时，才按需展开`Implemented in Code`的条目。`Not Implemented in Code`只表示尚未进入当前阅读批次，不应主动展开。
<示例>
`[aaa](aaa.md)` 已进入当前实现批次，`[bbb](bbb.md)` 尚未进入当前实现批次:
> 1. [aaa](aaa.md): `Partially Implemented in Code`
  2. [bbb](bbb.md): `Not Implemented in Code`

`[aaa](aaa.md)` 已完成，`[bbb](bbb.md)` 成为新的当前活动条目:
> 1. [aaa](aaa.md): `Implemented in Code`
  2. [bbb](bbb.md): `Partially Implemented in Code`
</示例>