# diy/ — 自定义卡牌（Phase 4）

## 契约

自定义卡牌 DSL / 编辑器只允许编译到以下既有原语，**引擎不需要为 DIY 升级**：

- 动作：`core.actions.ACTIONS` 注册表内的 op（damage / heal / draw / buff_attack / gain_armor / emit / ...）
- 事件：`core.events.CORE_EVENTS` ∪ `db/events.yaml` 声明的自定义事件
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
