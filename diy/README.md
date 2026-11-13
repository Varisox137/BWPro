# diy/ — 自定义卡牌（Phase 3）

非技术用户请先阅读《[DIY 式神与卡牌指南](DIY指南.md)》；该文件可直接连同式神与卡牌创意交给大模型。

完整的内容分包、机制注册、联机同步与清理方案见《[DIY 扩展架构设计](扩展架构设计.md)》。本地自动发现、可信机制注册、正式/DIY 合并、内置内容与下载内容加载、联机完整包同步和下载清理均已实现。

## 契约

自定义卡牌 DSL / 编辑器只允许编译到已注册原语；新增机制须按扩展架构放入对应内容包或式神目录，不在中央文件中累积：

- 动作：`core.actions.ACTIONS` 注册表内的 op（含按设计注册的 DIY op）
- 事件：`core.events.CORE_EVENTS` ∪ `db/events.yaml` 及 DIY 内容目录声明的事件
- 目标：`core.targets` 的 kind/pool 体系
- 结算：EffectBlock 的 `mode`（interleaved/atomic）与 `timing`（insert/queue）

## 安全约束

- 产出物是**数据**（YAML/JSON），不是可执行代码；绝不 eval 玩家输入。
- 加载即校验：走 `db.loader.CardDatabase.validate()`，未知 op/事件/目标池直接拒绝。
- 引擎侧已有 `MAX_QUEUE_ITERATIONS` 死循环保护；DSL 编译器另加步骤数/嵌套深度上限。

## 规划

1. 卡牌 YAML 模板 + `db.validate` 校验（现已可用，玩家手写 YAML 即可 DIY）。
2. DSL 编译器：更友好的效果描述语法 → EffectBlock。
3. 平衡辅助：费用曲线统计、对局模拟。
